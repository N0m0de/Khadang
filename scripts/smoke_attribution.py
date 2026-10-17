"""Offline recipient attribution checks; no network or private data."""
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ['OWNER_USER_ID'] = '111'
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.update(OWNER_FIRST_NAME='Alex', REPORTS_ENABLED='true', URGENT_ALERTS_ENABLED='true')
from secretary import commands
from secretary.outgoing import attributed, SIGNATURE

assert attributed('hi thank you.') == "hi thank you. -Alex's Assistant"
assert attributed(attributed('سلام ❤️')) == attributed('سلام ❤️')
assert attributed('hello ' + SIGNATURE + ' ' + SIGNATURE).count(SIGNATURE) == 1
long = attributed('😀' * 4096)
assert len(long.encode('utf-16-le')) // 2 <= 4096 and long.endswith(SIGNATURE)


async def main():
    bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=5)))
    pending = {'conn_id': 'test', 'chat_id': 222, 'draft': 'original'}
    with patch.object(commands.db, 'get_pending', AsyncMock(return_value=pending)), \
         patch.object(commands.db, 'claim_pending', AsyncMock(return_value=True)), \
         patch.object(commands, '_record_sent', AsyncMock()) as record:
        for edit in (None, 'edited'):
            await commands._resolve_pending(bot, 1, 'approved', text=edit)
            expected = attributed(edit or 'original')
            assert bot.send_message.call_args.kwargs['text'] == expected
            assert record.call_args.args[1] == expected
    update = SimpleNamespace(effective_user=SimpleNamespace(id=111))
    ctx = SimpleNamespace(args=['222', 'manual', 'message'], bot=bot)
    with patch.object(commands, '_active_conn_id', AsyncMock(return_value='test')), \
         patch.object(commands, '_reply', AsyncMock()), \
         patch.object(commands.db, 'append_message', AsyncMock()) as record:
        await commands.on_say(update, ctx)
        assert bot.send_message.call_args.kwargs['text'] == attributed('manual message')
        assert record.call_args.kwargs['content'] == attributed('manual message')
    print('Attribution checks passed: exact suffix, retries, Unicode limits, approvals, edits, manual sends.')

asyncio.run(main())
