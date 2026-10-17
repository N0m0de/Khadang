"""Learning readiness/status/error regression checks with synthetic messages only."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

temp=Path(tempfile.mkdtemp())
os.environ.update(DB_PATH=str(temp/'test.db'), SECRETORY_CONFIG_FILE=str(temp/'.env'),
                  PROMPTS_DIR=str(temp/'prompts'), AI_PROVIDER='openai', OPENAI_API_KEY='fake',
                  TG_BOT_TOKEN='', OWNER_USER_ID='111')
os.environ.pop('SECRETORY_PRIVATE_AUTH',None)
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from secretary import db,memory
from secretary.dashboard import auth
from secretary.dashboard.app import create_app

async def process_one(chat_id):
    worker=asyncio.create_task(memory.extract_worker())
    try:
        for _ in range(50):
            state=json.loads(await db.get_state(db.learning_key('c',chat_id)) or '{}')
            if state.get('status') in ('complete','failed','waiting'): return state
            await asyncio.sleep(.1)
        raise AssertionError('Learning worker did not report its result')
    finally:
        worker.cancel()
        try: await worker
        except asyncio.CancelledError: pass

async def main():
    await db.init_db()
    await db.upsert_connection(conn_id='c',owner_user_id=111,owner_chat_id=111,can_reply=True,is_enabled=True,rights=None)
    for _ in range(4): await db.append_message(conn_id='c',chat_id=1,role='user',content='sample')
    app=create_app(SimpleNamespace(username='fake'),lambda:None)
    base='http://127.0.0.1:18763'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=base) as client:
        token=await auth.create_login_token()
        await client.post('/login',data={'token':token},headers={'Origin':base})
        reply=await client.post('/contacts/1/extract',headers={'Origin':base})
        assert reply.status_code==303 and 'Only+4+recorded' in reply.headers['location']
        assert await db.claim_next() is None
        page=await client.get('/contacts/1')
        assert '4 recorded messages' in page.text and 'does not download old Telegram history' in page.text
        assert '15 messages you wrote' in page.text
    for _ in range(6): await db.append_message(conn_id='c',chat_id=1,role='user',content='sample')
    calls=[]
    async def successful(*args,**kwargs):
        calls.append(True)
        return '{"memories":[{"kind":"fact","content":"Likes reading","expires_at":null}]}'
    memory._chat=successful
    await db.enqueue(conn_id='c',chat_id=1)
    state=await process_one(1)
    assert state['status']=='complete' and state['messages_processed']==10 and state['facts_added']==1
    assert (await db.learning_counts(conn_id='c',chat_id=1))['new_messages']==0
    for _ in range(10): await db.append_message(conn_id='c',chat_id=2,role='user',content='sample')
    async def failed(*args,**kwargs): raise RuntimeError('private data must not be stored in error state')
    memory._chat=failed
    await db.enqueue(conn_id='c',chat_id=2)
    state=await process_one(2)
    assert state['status']=='failed' and state['error_type']=='RuntimeError'
    assert 'private data' not in json.dumps(state)
    assert (await db.learning_counts(conn_id='c',chat_id=2))['new_messages']==10
    for _ in range(15): await db.append_message(conn_id='c',chat_id=3,role='assistant',content='AI output',via_bot=True)
    assert (await db.learning_counts(conn_id='c',chat_id=3))['owner_messages']==0
    await db.close_db()
    print('Learning checks passed: insufficient data explained, no empty jobs, progress/success/failure stored safely, failed data retained, AI outputs excluded from owner examples.')

asyncio.run(main())
