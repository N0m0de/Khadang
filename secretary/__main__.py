import asyncio
import logging
import os
import signal
from types import SimpleNamespace

from dotenv import load_dotenv
load_dotenv(os.getenv('SECRETORY_CONFIG_FILE', '.env'))
os.environ.setdefault('SECRETORY_PRIVATE_AUTH', '1')

from telegram import Update
from telegram.error import NetworkError
from telegram.ext import (
    Application,
    BusinessConnectionHandler,
    BusinessMessagesDeletedHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import commands, handlers, memory, db, reporting, followups, polling
from .config import settings
from .dashboard.app import create_app, make_server, run_server
from .db import close_db, init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# httpx logs every request URL at INFO, and Telegram API URLs embed the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("secretary")


async def _on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    # Never log the update itself: it carries contact message text.
    kind = next((k for k, v in update.to_dict().items() if k != "update_id" and v is not None), None) \
        if isinstance(update, Update) else None
    log.error("unhandled error (update_id=%s kind=%s)",
              getattr(update, "update_id", None), kind)


async def main() -> None:
    await init_db()
    await db.set_state('runtime_mode', 'starting')
    if os.getenv("SECRETORY_PRIVATE_AUTH") == "1":
        if settings.hosted or settings.dashboard_host != "127.0.0.1":
            raise RuntimeError("Private Khadang requires a loopback dashboard without hosted mode")
        if not os.getenv("SECRETORY_PASSWORD_HASH"):
            raise RuntimeError("Private Khadang requires its owner password hash")
        for key in ("paused", "approval_mode"):
            if await db.get_state(key) is None:
                await db.set_state_bool(key, True)
        if not (settings.tg_bot_token and settings.owner_user_id > 0
                and settings.provider_key):
            await db.set_state('runtime_mode', 'unconfigured')
            await _configuration_dashboard()
            return

    # Concurrent updates: the reply pipeline sleeps for the race-guard delay, so
    # serial processing would hide the owner's own messages (and commands) until
    # the delay ended. Bursts in one chat are collapsed in handlers._chat_gen.
    builder = Application.builder().token(settings.tg_bot_token).concurrent_updates(True)
    polling_request = polling.MonitoredRequest(proxy=settings.telegram_proxy_url or None,
        read_timeout=35, connect_timeout=10, write_timeout=10, pool_timeout=5,
        httpx_kwargs={'trust_env': False})
    builder = builder.get_updates_request(polling_request)
    if settings.telegram_proxy_url:
        builder = builder.proxy(settings.telegram_proxy_url)
    if settings.hosted:
        builder = builder.updater(None)  # hosting router feeds updates via /_tg/update
        if not settings.dashboard_enabled:
            log.error("Hosted mode needs the dashboard enabled: updates arrive on /_tg/update")
    app = builder.build()

    app.add_handler(BusinessConnectionHandler(handlers.on_business_connection))
    app.add_handler(
        MessageHandler(
            filters.UpdateType.BUSINESS_MESSAGE & filters.TEXT,
            handlers.on_business_message,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.UpdateType.BUSINESS_MESSAGE & filters.VOICE,
            handlers.on_business_voice,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.UpdateType.BUSINESS_MESSAGE & ~filters.TEXT & ~filters.VOICE,
            handlers.on_business_non_text,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.UpdateType.EDITED_BUSINESS_MESSAGE,
            handlers.on_business_edited,
        )
    )
    app.add_handler(BusinessMessagesDeletedHandler(handlers.on_business_deleted))
    app.add_handler(CommandHandler("start", handlers.on_start))
    commands.register(app)
    followups.register(app)
    app.add_error_handler(_on_error)

    try:
        await app.initialize()
    except Exception as error:
        await db.set_state('startup_error_type', type(error).__name__)
        if isinstance(error, (NetworkError, OSError, TimeoutError)):
            # Let the supervisor retry; a transient network failure must not leave
            # the process permanently serving configuration instead of receiving.
            await db.set_state('runtime_mode', 'startup_network_failure')
            raise RuntimeError('Telegram startup connection failed; supervisor restart required') from None
        if os.getenv("SECRETORY_PRIVATE_AUTH") != "1":
            raise
        # Keep credential repair available without logging token-bearing errors.
        await db.set_state('runtime_mode', 'configuration_connection_failure')
        await _configuration_dashboard(connection_failed=True)
        return
    await reporting.initialize()
    await app.start()
    if app.updater is not None:
        await app.updater.start_polling(
            timeout=20,
            allowed_updates=[
                "business_connection",
                "business_message",
                "edited_business_message",
                "deleted_business_messages",
                "message",
                "callback_query",
            ],
            drop_pending_updates=False,
        )

    log.info("Secretary bot online. Model=%s. Ctrl+C to stop.", settings.reply_model)
    await db.set_state('runtime_mode', 'receiving')

    worker_task = asyncio.create_task(memory.extract_worker())
    reporting_task = asyncio.create_task(reporting.run(app.bot))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _request_stop() -> None:
        if not stop.is_set():
            polling.arm_shutdown()
        stop.set()

    # SIGINT/SIGTERM may not be available on Windows event loop policy in some setups.
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except (NotImplementedError, RuntimeError):
            pass

    dash_server = None
    dash_task = None
    if settings.dashboard_enabled:
        dash_server = make_server(create_app(app.bot, _request_stop, update_queue=app.update_queue),
                                  settings.dashboard_port, settings.dashboard_host)
        dash_task = asyncio.create_task(run_server(dash_server))
        log.info("Dashboard on %s:%d — send /dashboard to the bot for a login link",
                 settings.dashboard_host, settings.dashboard_port)
        if settings.dashboard_host not in ("127.0.0.1", "localhost", "::1"):
            log.warning("Dashboard is publicly bound; over plain http the session can be sniffed. "
                        "Prefer an https reverse proxy or the ssh tunnel.")

    monitor_task = asyncio.create_task(polling.watch(polling_request, _request_stop, app.bot)) if app.updater else None
    try:
        await stop.wait()
    except KeyboardInterrupt:
        pass
    finally:
        log.info("Shutting down…")
        if monitor_task:
            monitor_task.cancel()
            try:
                await monitor_task
            except (asyncio.CancelledError, Exception):
                pass
        if dash_server is not None and dash_task is not None:
            dash_server.should_exit = True
            await dash_task
        reporting_task.cancel()
        try:
            await reporting_task
        except (asyncio.CancelledError, Exception):
            pass
        worker_task.cancel()
        try:
            await worker_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        if app.updater is not None:
            await app.updater.stop()
        await app.stop()
        await app.shutdown()
        await close_db()


async def _configuration_dashboard(connection_failed: bool = False) -> None:
    """Serve owner setup without constructing or polling a Telegram bot."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    dashboard = create_app(SimpleNamespace(username=""), stop.set)
    dashboard.state.private_unconfigured = True
    dashboard.state.connection_failed = connection_failed
    server = make_server(dashboard, settings.dashboard_port, "127.0.0.1")
    serving = asyncio.create_task(run_server(server))
    stopping = asyncio.create_task(stop.wait())
    try:
        await asyncio.wait((serving, stopping), return_when=asyncio.FIRST_COMPLETED)
    finally:
        server.should_exit = True
        await serving
        stopping.cancel()
        await close_db()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
