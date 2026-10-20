"""Bound Telegram polling and expose content-free receiver health."""
import asyncio
import json
import time
import os
import threading
from telegram.error import TimedOut
from telegram.request import HTTPXRequest
from . import db
from .outgoing import attributed
from .config import settings

_active = None
REQUEST_DEADLINE = 50


def arm_shutdown(seconds=30, exit_function=os._exit):
    """A daemon thread also enforces the deadline if async cleanup stops progressing."""
    timer = threading.Timer(seconds, exit_function, args=(75,))
    timer.daemon = True
    timer.start()
    return timer


class MonitoredRequest(HTTPXRequest):
    def __init__(self, **kwargs):
        global _active
        super().__init__(**kwargs)
        self.last_success = time.monotonic()
        self.last_success_at = None
        self.last_error = None
        _active = self

    async def do_request(self, *args, **kwargs):
        try:
            async with asyncio.timeout(REQUEST_DEADLINE):
                result = await super().do_request(*args, **kwargs)
        except Exception as error:
            self.last_error = type(error).__name__
            if isinstance(error, TimeoutError):
                raise TimedOut('Telegram polling exceeded its bounded timeout') from None
            raise
        if result[0] == 200:
            self.last_success = time.monotonic()
            self.last_success_at = int(time.time())
            self.last_error = None
            await db.set_state('telegram_polling_health', json.dumps(health()))
        return result


def health():
    if _active is None:
        return {'state': 'unknown', 'last_success_at': None}
    age = time.monotonic() - _active.last_success
    return {'state': 'stalled' if age > 90 else ('retrying' if _active.last_error else 'ok'),
            'last_success_at': _active.last_success_at, 'error_type': _active.last_error,
            'age_seconds': int(age)}


async def watch(request, request_stop, bot):
    while True:
        await asyncio.sleep(15)
        snapshot = health()
        await db.set_state('telegram_polling_health', json.dumps(snapshot))
        if time.monotonic() - request.last_success > 180:
            now = int(time.time())
            last = int(await db.get_state('telegram_health_notice', '0'))
            if now - last > 3600:
                await db.set_state('telegram_health_notice', str(now))
                try:
                    async with asyncio.timeout(12):
                        await bot.send_message(chat_id=settings.owner_user_id, text=attributed(
                            '⚠️ Telegram message reception has stalled. The assistant is reconnecting. '
                            'Reports may be incomplete until queued messages are recovered.'))
                except Exception:
                    pass
            request_stop()
            return


def delayed(message, now=None):
    date = getattr(message, 'date', None)
    return bool(date and (time.time() if now is None else now) - date.timestamp() > 900)
