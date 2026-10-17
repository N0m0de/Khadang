"""Synthetic integration checks for durable owner follow-up decisions; no network."""
import asyncio
from datetime import datetime, timedelta
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.update(OWNER_USER_ID='111', DB_PATH=str(Path(tempfile.mkdtemp()) / 'checks.db'),
                  AI_PROVIDER='openai', OPENAI_API_KEY='synthetic')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.update(OWNER_FIRST_NAME='Alex', REPORTS_ENABLED='true', URGENT_ALERTS_ENABLED='true')
from secretary import db, reporting as r, followups as f


def callback(item_id, action, user=111):
    query = SimpleNamespace(from_user=SimpleNamespace(id=user), message=SimpleNamespace(chat=SimpleNamespace(id=111)),
        data=f'fu:{item_id}:{action}', answer=AsyncMock(), edit_message_text=AsyncMock())
    return SimpleNamespace(callback_query=query)


async def main():
    await db.init_db()
    midnight = datetime(2026, 10, 18, 0, tzinfo=r.TZ)
    await r.initialize(midnight - timedelta(hours=1))
    source = dict(id=1, conn_id='ours', chat_id=222, tg_message_id=10, role='user',
                  content='Please check this for me', contact='Test contact', created_at=int(midnight.timestamp()) - 100)
    await f.capture_requests([source], r.alert_kind)
    await f.capture_requests([source], r.alert_kind)
    items = await f.pending()
    assert len(items) == 1
    item_id = items[0]['id']
    meeting = dict(source, id=2, tg_message_id=11, content='Can we meet tomorrow?')
    await f.capture_requests([meeting], r.alert_kind)
    meeting_id = (await f.pending())[1]['id']
    assert 'confirmed' in str(f.keyboard(await f.get(meeting_id)))
    assert 'confirmed' not in str(f.keyboard(await f.get(item_id)))

    outsider = callback(item_id, 'done', 999)
    await f.on_callback(outsider, None)
    assert (await f.get(item_id))['status'] == 'pending'
    assert not outsider.callback_query.edit_message_text.called

    bot = SimpleNamespace(send_message=AsyncMock())
    await db.set_state('reports_next', str(int(midnight.timestamp())))
    with patch.object(r, 'render_report', AsyncMock(return_value='Synthetic midnight report')):
        await r.report_tick(bot, midnight)
    cards = [c for c in bot.send_message.call_args_list if c.kwargs.get('reply_markup')]
    assert len(cards) == 2
    assert all(c.kwargs['chat_id'] == 111 for c in cards)
    await f.on_callback(callback(item_id, 'pending'), None)
    assert len(await f.pending()) == 2

    # New day: open requests persist even when source messages are gone.
    await db._db().execute('DELETE FROM messages')
    await db._db().commit()
    noon = midnight + timedelta(hours=12)
    with patch.object(r, 'render_report', AsyncMock(return_value='No conversations')):
        await r.report_tick(bot, noon)
    assert any('Unresolved requests' in c.kwargs['text'] for c in bot.send_message.call_args_list)
    await db.close_db()
    await db.init_db()
    await r.initialize()
    assert len(await f.pending()) == 2

    # Owner decision resolves only the chosen item; no contact send API is called.
    await f.on_callback(callback(item_id, 'done'), None)
    await f.on_callback(callback(meeting_id, 'confirmed'), None)
    assert len(await f.pending()) == 0
    await f.on_callback(callback(item_id, 'pending'), None)  # Stale keyboard cannot reopen.
    assert (await f.get(item_id))['status'] == 'done'
    await f.capture_requests([source], r.alert_kind)  # Old transcript cannot recreate it.
    assert len(await f.pending()) == 0

    third = dict(source, id=3, tg_message_id=12)
    await f.capture_requests([third], r.alert_kind)
    third_id = (await f.pending())[0]['id']
    await r.queue(f'review:future:{third_id}', 'review', f.card(await f.get(third_id)))
    await f.on_callback(callback(third_id, 'declined'), None)
    count = bot.send_message.call_count
    await r.deliver(bot, 'review')
    assert bot.send_message.call_count == count  # Resolved queued reminders are skipped.

    # Semantic extraction accepts only actual inbound source IDs from the report window.
    await db.upsert_connection(conn_id='ours', owner_user_id=111, owner_chat_id=111,
                               can_reply=True, is_enabled=True, rights=None)
    await db.append_message(conn_id='ours', chat_id=222, role='user', content='The attachment needs your eyes', tg_message_id=20)
    await db.append_message(conn_id='ours', chat_id=222, role='assistant', content='I checked it', tg_message_id=21)
    cur = await db._db().execute('SELECT id,role FROM messages ORDER BY id')
    sources = {row['role']: row['id'] for row in await cur.fetchall()}
    import json
    payload = {'summary': 'Synthetic summary', 'requests': [
        {'source_id': sources['user'], 'kind': 'task', 'description': 'Review the attachment'},
        {'source_id': sources['assistant'], 'kind': 'task', 'description': 'Invalid assistant request'},
        {'source_id': 999999, 'kind': 'meeting', 'description': 'Invalid missing source'}]}
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
    create = AsyncMock(return_value=response)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with patch.object(r.llm, 'openai_client', SimpleNamespace(with_options=lambda **kw: client)):
        await r.render_report(r.next_boundary(datetime.now(r.TZ)))
    items = await f.pending()
    assert len(items) == 1 and items[0]['description'] == 'Review the attachment'
    assert create.call_args.kwargs['response_format'] == {'type': 'json_object'}
    await db.close_db()
    print('Follow-up checks passed: inline decisions, owner-only access, carry-forward, restart/source retention, deduplication, stale buttons.')

asyncio.run(main())
