"""Owner-only review of proposed export learning; proposals never enter replies automatically."""
import json
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import FileResponse
from .. import db,commands,prompts
from ..export_import import job_path,read_json,write_json,clean_style,KINDS
from .web import render,back

router=APIRouter()

def load(chat_id,job_id):
    try:
        folder=job_path(job_id)
        meta=read_json(folder/'status.json')
        if meta.get('chat_id')!=chat_id: raise ValueError('Wrong contact')
        proposal=read_json(folder/'proposal.json') if (folder/'proposal.json').exists() else None
        return folder,meta,proposal
    except (OSError,ValueError): raise HTTPException(404,'Import not found') from None

@router.get('/contacts/{chat_id}/imports/{job_id}')
async def review(request: Request,chat_id:int,job_id:str):
    folder,meta,proposal=load(chat_id,job_id)
    return render(request,'import_review.html',chat_id=chat_id,job_id=job_id,meta=meta,proposal=proposal,
                  style_json=json.dumps(proposal['style'],ensure_ascii=False,indent=2) if proposal else '')

@router.post('/contacts/{chat_id}/imports/{job_id}/apply')
async def apply(request:Request,chat_id:int,job_id:str):
    folder,meta,proposal=load(chat_id,job_id)
    target=f'/contacts/{chat_id}/imports/{job_id}'
    if meta.get('status')!='ready' or not proposal: return back(target,err='Analysis is not ready yet.')
    conn_id=await commands._active_conn_id()
    if conn_id is None: return back(target,err='Connect your Telegram account first.')
    form=await request.form()
    selected=form.getlist('facts')
    prepared=[]
    try:
        for value in selected:
            index=int(value)
            if not 0<=index<len(proposal['facts']): raise ValueError()
            item=proposal['facts'][index]
            text=str(form.get(f'fact_{index}',item['content'])).strip()
            if item['kind'] not in KINDS or not 3<=len(text)<=1200: raise ValueError()
            prepared.append((index,item,text))
        style=None
        if form.get('apply_style')=='on':
            raw=json.loads(str(form.get('style_json','{}')))
            if not isinstance(raw,dict): raise ValueError()
            style=clean_style(raw)
            style['owner_examples']=[str(value)[:240] for value in raw.get('owner_examples',[])[:12] if isinstance(value,str)]
    except (ValueError,TypeError,KeyError): return back(target,err='Invalid selection or style JSON; nothing applied.')
    if style is not None:
        await db.set_style_fingerprint(conn_id=conn_id,chat_id=chat_id,json_str=json.dumps(style,ensure_ascii=False))
        proposal['style_applied']=True
    added=0
    accepted=set(proposal.get('accepted_facts',[]))
    for index,item,text in prepared:
        if index in accepted: continue
        content=f"{text} (stated in historical chat on {item['source_date'][:10]}; check whether still current)"
        if not await db.memory_duplicate_exists(conn_id=conn_id,chat_id=chat_id,kind=item['kind'],content=content):
            await db.add_memory(conn_id=conn_id,chat_id=chat_id,kind=item['kind'],content=content)
            added+=1
        accepted.add(index)
    proposal['accepted_facts']=sorted(accepted)
    write_json(folder/'proposal.json',proposal)
    prompts.clear_cache()
    return back(target,msg=f"Applied {'writing style and ' if style is not None else ''}{added} selected memories. Unselected suggestions remain inactive.")

@router.get('/contacts/{chat_id}/imports/{job_id}/candidates')
async def candidates(chat_id:int,job_id:str):
    folder,meta,proposal=load(chat_id,job_id)
    path=folder/'facts-all.json'
    if not path.exists(): raise HTTPException(404,'Full candidate archive is not ready')
    return FileResponse(path,media_type='application/json',filename='export-memory-candidates.json')
