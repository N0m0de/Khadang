"""Owner dashboard: a FastAPI app served inside the bot process on 127.0.0.1."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import secrets
import re
from urllib.parse import quote
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from telegram import Update

from .. import db
from ..config import settings
from ..setup import ENV_PATH
from ..private_auth import OwnerAuth
from . import auth, contacts, drafts, pages, imports
from .web import render, t

log = logging.getLogger(__name__)
_HERE = Path(__file__).resolve().parent


def safe_next(path: str) -> str:
    # Only known dashboard pages; no external, encoded, query or backslash redirects.
    return path if re.fullmatch(r"/(?:contacts(?:/-?\d+(?:/imports/[a-f0-9]{32})?)?|settings|prompts|drafts)?", path) else "/"


def create_app(bot: Any, request_stop: Callable[[], None], env_path: Path = ENV_PATH,
               update_queue: asyncio.Queue | None = None) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.bot = bot
    app.state.update_queue = update_queue
    app.state.request_stop = request_stop
    app.state.env_path = env_path
    app.state.started_at = time.time()
    private = os.getenv("SECRETORY_PRIVATE_AUTH") == "1"
    owner_auth = OwnerAuth(os.getenv("SECRETORY_PASSWORD_HASH"), required=True)
    login_lock = asyncio.Lock()
    app.state.private_unconfigured = private and not (
        settings.tg_bot_token and settings.owner_user_id > 0
        and settings.provider_key
    )
    app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")

    @app.middleware("http")
    async def guard(request: Request, call_next):
        request.state.csp_nonce = secrets.token_urlsafe(24)
        if settings.hosted and not private:
            # Only the hosting proxy may talk to us; it already checked the user's
            # session and Origin, so Host/Origin/login checks don't apply here.
            if not auth.proxy_ok(request.headers.get("x-platform-auth")):
                return PlainTextResponse("forbidden", status_code=403)
            request.state.pending = await db.count_open_pending()
            return await call_next(request)
        host = request.headers.get("host", "")
        local_name = host.rsplit(":", 1)[0].lower()
        if (private and local_name not in ("127.0.0.1", "localhost", "[::1]")) or not auth.host_ok(host):
            return PlainTextResponse("bad host", status_code=400)
        if request.method == "POST" and not auth.origin_ok(request.headers.get("origin"), host):
            return PlainTextResponse("bad origin", status_code=403)
        path = request.url.path
        if path != "/login" and not path.startswith("/static/"):
            valid = (owner_auth.valid(request.cookies.get(owner_auth.COOKIE)) if private
                     else await auth.session_valid(request.cookies.get(auth.COOKIE)))
            if not valid:
                if request.method == "GET":
                    target = settings.dashboard_root_path + "/login"
                    if private:
                        target += "?next=" + quote(safe_next(request.url.path), safe="")
                    return RedirectResponse(target, status_code=303)
                return PlainTextResponse("login required", status_code=401)
            request.state.pending = await db.count_open_pending()
        response = await call_next(request)
        if private:
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            # no-referrer makes native browser form POSTs send Origin: null,
            # conflicting with our strict CSRF check. Keep referrers same-origin.
            response.headers["Referrer-Policy"] = "same-origin"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self' 'nonce-" + request.state.csp_nonce
                + "'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; "
                "base-uri 'none'; form-action 'self'; object-src 'none'"
            )
        return response

    @app.get("/login")
    async def login_page(request: Request):
        return render(request, "private_login.html" if private else "login.html",
                      next_path=safe_next(request.query_params.get("next", "/")))

    @app.post("/login")
    async def login(request: Request, token: str = Form(""), password: str = Form(""), next_path: str = Form("/", alias="next")):
        if private:
            if len(password) > 512:
                return PlainTextResponse("invalid password", status_code=401)
            async with login_lock:
                session, error = await asyncio.to_thread(owner_auth.login, password)
            if not session:
                return render(request, "private_login.html", status_code=401, err=error, next_path=safe_next(next_path))
            response = RedirectResponse(safe_next(next_path), status_code=303)
            response.set_cookie(owner_auth.COOKIE, session, max_age=owner_auth.ABSOLUTE_TTL,
                                httponly=True, samesite="strict", path="/",
                                secure=request.url.scheme == "https")
            return response
        session = await auth.redeem_login_token(token.strip())
        if session is None:
            return render(
                request, "login.html", status_code=401,
                err=t("That link is invalid, used or expired. Send /dashboard to your bot for a new one."),
            )
        resp = RedirectResponse(settings.dashboard_root_path + "/", status_code=303)
        resp.set_cookie(auth.COOKIE, session, max_age=auth.SESSION_TTL, httponly=True,
                        samesite="strict", path="/",
                        secure=settings.dashboard_public_url.startswith("https://"))
        return resp

    @app.post("/logout")
    async def logout(request: Request):
        if private:
            owner_auth.logout(request.cookies.get(owner_auth.COOKIE))
            response = RedirectResponse("/login", status_code=303)
            response.delete_cookie(owner_auth.COOKIE, path="/")
            return response
        await auth.end_session(request.cookies.get(auth.COOKIE))
        resp = RedirectResponse(settings.dashboard_root_path + "/login", status_code=303)
        resp.delete_cookie(auth.COOKIE, path="/")
        return resp

    if settings.hosted and not private:
        @app.post("/_tg/update")
        async def tg_update(request: Request):
            # The hosting router is the only poller of the shared bot; it pushes
            # this tenant's updates here (guard above already checked X-Platform-Auth).
            if request.headers.get("x-platform-route") != "update":
                return PlainTextResponse("forbidden", status_code=403)  # the /app proxy never sends it
            data = await request.json()
            await request.app.state.update_queue.put(Update.de_json(data, request.app.state.bot))
            return PlainTextResponse("ok")

    app.include_router(pages.router)
    app.include_router(contacts.router)
    app.include_router(drafts.router)
    app.include_router(imports.router)
    return app


class _Server(uvicorn.Server):
    def capture_signals(self):  # type: ignore[override]
        # The bot owns SIGINT/SIGTERM via loop.add_signal_handler; uvicorn must not replace them.
        return contextlib.nullcontext()


def make_server(app: FastAPI, port: int, host: str = "127.0.0.1") -> uvicorn.Server:
    config = uvicorn.Config(app, host=host, port=port, access_log=False,
                            log_config=None, log_level="warning", proxy_headers=False)
    return _Server(config)


async def run_server(server: uvicorn.Server) -> None:
    """Serve until server.should_exit. A busy port logs an error instead of killing the bot."""
    try:
        await server.serve()
    except SystemExit:  # uvicorn calls sys.exit(1) when it can't bind
        log.error("dashboard not started: port %s is busy; the bot keeps running", server.config.port)
