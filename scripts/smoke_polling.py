"""Offline receiver health / watchdog / delayed timestamps checks; no Telegram requests."""
import asyncio
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

os.environ.update(DB_PATH=str(Path(tempfile.mkdtemp())/'test.db'), OWNER_USER_ID='111', OWNER_FIRST_NAME='Alex')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from secretary import db, polling
from telegram.error import TimedOut
from telegram.request import HTTPXRequest
import runpy


async def main():
    await db.init_db()
    with patch.object(polling.threading, 'Timer') as timer:
        exit_function=Mock()
        polling.arm_shutdown(exit_function=exit_function)
        assert timer.call_args.args==(30,exit_function)
        assert timer.call_args.kwargs['args']==(75,)
        assert timer.return_value.daemon is True and timer.return_value.start.called
    guard=runpy.run_path(str(Path(__file__).parent/'service_healthcheck.py'))['needs_restart']
    assert not guard('unconfigured',None,500,1000)
    assert not guard('receiving',None,100,1000)
    assert not guard('receiving',990,500,1000)
    assert guard('configuration_connection_failure',500,500,1000)
    assert guard('receiving',500,500,1000)
    # Reproduce the original failure: transient startup errors must exit for the
    # supervisor to retry, never park permanently in the setup-only dashboard.
    from secretary import __main__ as entry
    from telegram.ext import Application, ApplicationBuilder
    apps=[]
    real_build=ApplicationBuilder.build
    def capture_build(builder):
        app=real_build(builder)
        apps.append(app)
        return app
    with patch.dict(os.environ,{'SECRETORY_PRIVATE_AUTH':'0'}), \
         patch.object(entry.settings,'tg_bot_token','0:synthetic'), \
         patch.object(ApplicationBuilder,'build',capture_build), \
         patch.object(Application,'initialize',AsyncMock(side_effect=TimedOut('synthetic startup timeout'))):
        try:
            await entry.main()
            raise AssertionError('Startup network failure was swallowed')
        except RuntimeError as error:
            assert 'supervisor restart' in str(error)
    assert await db.get_state('runtime_mode')=='startup_network_failure'
    for app in apps:
        await app.bot.request.shutdown()
    if polling._active:
        await polling._active.shutdown()
    request = polling.MonitoredRequest()
    with patch.object(HTTPXRequest, 'do_request', AsyncMock(return_value=(200,b'{}'))):
        assert (await request.do_request(url='unused',method='POST'))[0] == 200
        assert polling.health()['state'] == 'ok'
        assert json.loads(await db.get_state('telegram_polling_health'))['last_success_at']
    async def hang(*args,**kwargs):
        await asyncio.sleep(10)
    with patch.object(HTTPXRequest,'do_request',hang), patch.object(polling,'REQUEST_DEADLINE',.01):
        try:
            await request.do_request(url='unused',method='POST')
            raise AssertionError('Hung request did not time out')
        except TimedOut:
            pass
    request.last_success -= 300
    assert polling.health()['state'] == 'stalled'
    stop = Mock()
    bot = SimpleNamespace(send_message=AsyncMock())
    with patch.object(polling.asyncio,'sleep',AsyncMock()):
        await polling.watch(request, stop, bot)
    assert stop.called and bot.send_message.call_args.kwargs['chat_id']==111
    # A quiet chat is not a stalled receiver: successful empty polls refresh heartbeat.
    with patch.object(HTTPXRequest, 'do_request', AsyncMock(return_value=(200,b'{}'))):
        await request.do_request(url='unused',method='POST')
    assert polling.health()['state']=='ok'
    now = datetime.now(timezone.utc)
    assert polling.delayed(SimpleNamespace(date=now-timedelta(hours=2)))
    assert not polling.delayed(SimpleNamespace(date=now))
    assert not polling.delayed(SimpleNamespace())
    await db.append_message(conn_id='test',chat_id=1,role='user',content='invented',created_at=123)
    cur=await db._db().execute('SELECT created_at FROM messages')
    assert (await cur.fetchone())[0]==123
    await request.shutdown()
    await db.close_db()
    print('Receiver checks passed: bounded hangs, heartbeat, watchdog, quiet polls, stale-message gate, original timestamps.')

asyncio.run(main())
