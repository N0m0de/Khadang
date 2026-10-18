"""Synthetic report/alert integration checks: no Telegram or OpenAI network traffic."""
import asyncio
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.update(OWNER_USER_ID='111', DB_PATH=str(Path(tempfile.mkdtemp()) / 'checks.db'),
                  OPENAI_API_KEY='synthetic', AI_PROVIDER='openai')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.update(OWNER_FIRST_NAME='Alex', REPORTS_ENABLED='true', URGENT_ALERTS_ENABLED='true')
from secretary import db, reporting as r
from secretary.outgoing import SIGNATURE


async def add(role, text, tg_id, conn='ours'):
    await db.append_message(conn_id=conn, chat_id=222, role=role, content=text, tg_message_id=tg_id)


async def main():
    noon = datetime(2026, 10, 16, 12, tzinfo=r.TZ)
    midnight = datetime(2026, 10, 17, 0, tzinfo=r.TZ)
    assert r.next_boundary(noon - timedelta(seconds=1)) == noon
    assert r.next_boundary(noon) == midnight
    assert r.next_boundary(midnight) == midnight + timedelta(hours=12)
    assert r.next_boundary(noon.astimezone(timezone.utc)) == midnight
    assert r.report_window(midnight) == (noon.replace(hour=0), midnight)
    assert r.report_window(noon) == (noon.replace(hour=0), noon)
    for text in ['Can we meet tomorrow?', 'فردا ساعت ۵ میای؟', 'جلسه ساعت سه کنسل شد',
                 'می\u200cتونی فردا بیای؟', '[voice transcript] قرار فردا ساعت ۹']:
        assert r.alert_kind(text) == 'Scheduling / deadline request', text
    for text in ['urgent please call', 'I cannot breathe, emergency', 'اورژانس زنگ بزن', 'تصادف کردم']:
        assert r.alert_kind(text) == 'Potential emergency / urgent matter', text
    assert r.alert_kind('سلام خوبی؟') is None

    await db.init_db()
    await db.upsert_connection(conn_id='ours', owner_user_id=111, owner_chat_id=111,
                               can_reply=True, is_enabled=True, rights=None)
    await db.upsert_connection(conn_id='other', owner_user_id=999, owner_chat_id=999,
                               can_reply=True, is_enabled=True, rights=None)
    await add('user', 'old emergency', 1)
    await r.initialize(noon - timedelta(hours=1))
    await r.scan_alerts()
    bot = SimpleNamespace(send_message=AsyncMock())
    await r.deliver(bot, 'alert')
    assert bot.send_message.call_count == 0  # No historical alert flood on installation.
    await add('user', 'Can we meet tomorrow?', 2)
    await add('user', 'Can we meet tomorrow?', 2)  # Telegram redelivery deduplication.
    await add('assistant', 'urgent', 3)
    await add('user', 'emergency', 4, conn='other')
    await add('user', 'تصادف کردم', 5)
    await r.scan_alerts()
    await r.deliver(bot, 'alert')
    assert bot.send_message.call_count == 2
    assert all(c.kwargs['chat_id'] == 111 for c in bot.send_message.call_args_list)
    assert all(c.kwargs['text'].endswith(SIGNATURE) for c in bot.send_message.call_args_list)
    await r.initialize()
    await r.scan_alerts()
    await r.deliver(bot, 'alert')
    assert bot.send_message.call_count == 2  # Restart persistence.

    await add('user', 'urgent', 6)
    await r.scan_alerts()
    bot.send_message.side_effect = RuntimeError('synthetic network failure')
    try:
        await r.deliver(bot, 'alert')
    except RuntimeError:
        pass
    bot.send_message.side_effect = None
    await r.deliver(bot, 'alert')  # Failed sends remain pending.
    assert bot.send_message.call_count == 4

    render = AsyncMock(return_value='synthetic daily report')
    await db.set_state('reports_next', str(int(noon.timestamp())))
    with patch.object(r, 'render_report', render):
        bot.send_message.side_effect = RuntimeError('offline')
        try:
            await r.report_tick(bot, noon)
        except RuntimeError:
            pass
        bot.send_message.side_effect = None
        await r.report_tick(bot, noon + timedelta(seconds=10))
        await r.report_tick(bot, noon + timedelta(minutes=1))
        assert render.call_count == 1  # Cached report survives a delivery failure.
        await r.report_tick(bot, midnight + timedelta(minutes=5))
        await r.report_tick(bot, midnight + timedelta(minutes=6))
        assert render.call_count == 2  # Exactly one for each due boundary.
    assert int(await db.get_state('reports_next')) == int((midnight + timedelta(hours=12)).timestamp())

    # Summary API contract and degraded report use synthetic fixtures only.
    report_end = r.next_boundary(datetime.now(r.TZ))
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"summary":"synthetic summary","requests":[]}'))])
    completion = AsyncMock(return_value=response)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=completion)))
    wrapper = SimpleNamespace(with_options=lambda **kwargs: client)
    with patch.object(r.llm, 'openai_client', wrapper):
        result = await r.render_report(report_end)
        assert 'synthetic summary' in result
        assert completion.call_args.kwargs['store'] is False
        assert completion.call_args.kwargs['max_completion_tokens'] == 1800
        completion.side_effect = RuntimeError('synthetic quota')
        assert 'AI summary unavailable' in await r.render_report(report_end)
    # Coverage lists every chat even when an AI summary mentions only a subset.
    for chat_id in range(300,312):
        await db.append_message(conn_id='ours',chat_id=chat_id,role='user',content='invented coverage example')
    await r.queue_coverage('coverage-test',report_end)
    cur = await db._db().execute('SELECT body FROM owner_notifications WHERE key LIKE ?',('coverage-test:%',))
    pages = [row[0] for row in await cur.fetchall()]
    assert len(pages)>=2
    for chat_id in range(300,312):
        assert f'chat {chat_id}' in '\n'.join(pages)
    await db.close_db()
    print('Reporting checks passed: Tehran boundaries, detection, owner isolation, retries, restart deduplication, summary fallback.')

asyncio.run(main())
