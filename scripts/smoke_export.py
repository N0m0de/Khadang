"""Export parser, evidence validation and private review tests with invented dialogue."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

temp=Path(tempfile.mkdtemp())
os.environ.update(DB_PATH=str(temp/'test.db'),SECRETORY_CONFIG_FILE=str(temp/'.env'),
                  PROMPTS_DIR=str(temp/'prompts'),AI_PROVIDER='openai',OPENAI_API_KEY='fake',TG_BOT_TOKEN='',OWNER_USER_ID='111')
os.environ.pop('SECRETORY_PRIVATE_AUTH',None)
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from secretary import db,prompts
from secretary.export_parser import TelegramHTML,read_html_folder,read_json_export
from secretary.export_import import write_json,job_path,validate_facts,batches
from secretary.dashboard.app import create_app
from secretary.dashboard import auth

sample='''<div class="message default" id="message1"><div class="body"><div class="from_name">Owner</div><div class="date" title="01.01.2025 12:00:00 UTC+00:00"></div><div class="text">Hi<br>there &amp; welcome</div></div></div>
<div class="message default joined" id="message2"><div class="text">second message</div></div>
<div class="message default" id="message3"><div class="from_name">Contact</div><div class="text">I like reading books.</div></div>
<div class="message service" id="message4"><div class="text">joined</div></div>
<div class="message default" id="message5"><div class="from_name">Contact</div><div class="forwarded body"><div class="from_name">Someone</div><div class="text">Not evidence</div></div></div>'''

async def main():
    (temp/'messages.html').write_text(sample,encoding='utf-8')
    (temp/'messages2.html').write_text('<div class="message default joined" id="message6"><div class="text">also contact</div></div>',encoding='utf-8')
    rows=read_html_folder(temp)
    assert len(rows)==4 and rows[0]['text']=='Hi\nthere & welcome'
    assert rows[1]['sender']=='Owner' and rows[-1]['sender']=='Contact'
    evidence=[{'id':'1','role':'owner','date':'2025-01-01','text':'She likes swimming'},
              {'id':'2','role':'contact','date':'2025-01-02','text':'I like reading books.'}]
    response={'facts':[{'kind':'preference','content':'Likes reading','source_id':'2','quote':'reading books'},
                       {'kind':'fact','content':'Likes swimming','source_id':'1','quote':'likes swimming'},
                       {'kind':'fact','content':'Unsupported','source_id':'2','quote':'invented evidence'}]}
    facts=validate_facts(response,evidence)
    assert len(facts)==1 and facts[0]['source_date']=='2025-01-02'
    assert len(batches(evidence,limit=30))==2
    export=temp/'export.json'
    export.write_text(json.dumps({'messages':[{'id':1,'type':'message','from':'Owner','from_id':'user111','text':['hello ',{'type':'bold','text':'world'}],'date':'2025-01-01'}, {'id':2,'type':'message','from':'Other','text':'forwarded','forwarded_from':'Other'}]}))
    assert read_json_export(export)[0]['text']=='hello world' and len(read_json_export(export))==1
    await db.init_db()
    await db.upsert_connection(conn_id='c',owner_user_id=111,owner_chat_id=111,can_reply=True,is_enabled=True,rights=None)
    job_id='a'*32
    folder=job_path(job_id)
    write_json(folder/'status.json',{'status':'ready','chat_id':7,'owner_messages':20,'contact_messages':20})
    write_json(folder/'proposal.json',{'style':{'avg_length':25,'style_guidance':['Keep replies short'],'imported_profile':True},
                                     'facts':facts,'accepted_facts':[],'style_applied':False})
    app=create_app(SimpleNamespace(username='fake'),lambda:None)
    base='http://127.0.0.1:18763'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=base) as client:
        assert (await client.get(f'/contacts/7/imports/{job_id}')).status_code==303
        token=await auth.create_login_token()
        await client.post('/login',data={'token':token},headers={'Origin':base})
        assert (await client.get(f'/contacts/8/imports/{job_id}')).status_code==404
        page=await client.get(f'/contacts/7/imports/{job_id}')
        assert page.status_code==200 and 'reading books' in page.text and 'name="facts" value="0"' in page.text
        assert not await db.list_memory(conn_id='c',chat_id=7)
        data={'apply_style':'on','style_json':json.dumps({'avg_length':25,'style_guidance':['short']}),'facts':'0','fact_0':'Likes reading'}
        result=await client.post(f'/contacts/7/imports/{job_id}/apply',data=data,headers={'Origin':base})
        assert result.status_code==303
        assert len(await db.list_memory(conn_id='c',chat_id=7))==1
        await client.post(f'/contacts/7/imports/{job_id}/apply',data=data,headers={'Origin':base})
        assert len(await db.list_memory(conn_id='c',chat_id=7))==1
        override=await db.get_override(conn_id='c',chat_id=7)
        assert 'imported_profile' in override['style_fingerprint']
        assert 'takes priority' in prompts.load_system_prompt(chat_id=7,relationship='gf',style_fingerprint=override['style_fingerprint'])
    await db.close_db()
    print('Export checks passed: HTML pages/joined senders, forwarding exclusion, rich JSON, exact contact evidence, dated facts, private review, explicit activation and idempotent apply.')

asyncio.run(main())
