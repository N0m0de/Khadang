"""Offline private access checks; no real credentials or outbound requests."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from secretary.private_auth import OwnerAuth, password_hash

temp = Path(tempfile.mkdtemp())
password = "private-test-password"
os.environ.update(SECRETORY_PRIVATE_AUTH="1", SECRETORY_PASSWORD_HASH=password_hash(password),
                  TG_BOT_TOKEN="", OWNER_USER_ID="0", OPENROUTER_API_KEY="",
                  ANTHROPIC_API_KEY="", DB_PATH=str(temp / "test.db"),
                  PROMPTS_DIR=str(temp / "prompts"), SECRETORY_CONFIG_FILE=str(temp / ".env"))
import httpx
from secretary import db
from secretary.dashboard import auth
from secretary.dashboard.app import create_app


async def main():
    await db.init_db()
    app = create_app(SimpleNamespace(username=""), lambda: None, temp / ".env")
    base = "http://127.0.0.1:18764"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base) as client:
        assert (await client.get("/")).status_code == 303
        assert (await client.post("/login", data={"password": password})).status_code == 403
        assert (await client.post("/login", data={"password": password}, headers={"origin": "null"})).status_code == 403
        assert (await client.get("/login")).headers["referrer-policy"] == "same-origin"
        headers = {"origin": base}
        review_path = "/contacts/7/imports/" + "a" * 32
        redirect = await client.get(review_path)
        assert "next=" in redirect.headers["location"]
        form = await client.get(redirect.headers["location"])
        assert review_path in form.text and 'name="next"' in form.text
        follow = await client.post("/login", data={"password":password,"next":review_path}, headers=headers)
        assert follow.status_code == 303 and follow.headers["location"] == review_path
        hostile = await client.post("/login", data={"password":password,"next":"//attacker.test"}, headers=headers)
        assert hostile.headers["location"] == "/"
        await client.post("/logout", headers=headers)
        token = await auth.create_login_token()
        assert (await client.post("/login", data={"token": token}, headers=headers)).status_code == 401
        assert (await client.get("/", headers={"x-platform-auth": "anything"})).status_code == 303
        assert (await client.get("/login", headers={"host": "attacker.test"})).status_code == 400
        result = await client.post("/login", data={"password": password}, headers=headers)
        assert result.status_code == 303
        assert "HttpOnly" in result.headers["set-cookie"] and "SameSite=strict" in result.headers["set-cookie"]
        for page in ("/", "/contacts", "/drafts", "/prompts", "/settings"):
            result = await client.get(page)
            assert result.status_code == 200, page
            assert "nonce-" in result.headers["content-security-policy"]
            assert result.headers["cache-control"] == "no-store"
            assert "Finish connecting Khadang" in result.text
        previous = client.cookies.get(OwnerAuth.COOKIE)
        await client.post("/login", data={"password": password}, headers=headers)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base,
                                   cookies={OwnerAuth.COOKIE: previous}) as old:
            assert (await old.get("/")).status_code == 303
        assert (await client.post("/logout", headers=headers)).status_code == 303
        assert (await client.get("/")).status_code == 303
    # Private mode fails closed even when its hash is missing.
    os.environ.pop("SECRETORY_PASSWORD_HASH")
    locked = create_app(SimpleNamespace(username=""), lambda: None)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=locked), base_url=base) as client:
        assert (await client.get("/")).status_code == 303
        assert (await client.post("/login", data={"password": password}, headers=headers)).status_code == 401
    gate = OwnerAuth(password_hash(password), required=True)
    for _ in range(5):
        assert gate.login("wrong")[0] is None
    assert gate.login(password)[0] is None
    await db.close_db()
    print("Private access checks passed: CSRF, password, token/proxy bypass, sessions, pages, fail-closed and lockout.")


asyncio.run(main())
