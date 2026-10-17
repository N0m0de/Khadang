"""Read Telegram Desktop HTML/JSON text exports without executing HTML or media."""
from html.parser import HTMLParser
from pathlib import Path
from datetime import datetime
import json
import re


class TelegramHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack=[]
        self.messages=[]
        self.current=None
        self.previous_sender=None

    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        classes=set(attrs.get('class','').split())
        node={'tag':tag,'classes':classes}
        if tag=='div' and 'message' in classes:
            if self.current is not None: self.finish()
            self.current={'id':attrs.get('id',''), 'sender':None,'date':'','parts':[],
                          'service':'service' in classes,'forwarded':False}
            node['message']=True
        if self.current:
            if 'forwarded' in classes: self.current['forwarded']=True
            if 'date' in classes and attrs.get('title'): self.current['date']=attrs['title']
            if tag=='br' and any('text' in n['classes'] for n in self.stack): self.current['parts'].append('\n')
        if tag not in ('br','img','input','meta','link','hr','source','wbr'): self.stack.append(node)

    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i]['tag']==tag:
                closing=self.stack[i:]
                del self.stack[i:]
                if any(n.get('message') for n in closing): self.finish()
                break

    def handle_data(self,data):
        if not self.current: return
        if any('from_name' in n['classes'] for n in self.stack):
            if not any('forwarded' in n['classes'] for n in self.stack):
                self.current['sender']=(self.current['sender'] or '')+data
        elif any('text' in n['classes'] for n in self.stack): self.current['parts'].append(data)

    def finish(self):
        if self.current is None: return
        message=self.current
        self.current=None
        sender=(message['sender'] or '').strip()
        if sender: self.previous_sender=sender
        else: sender=self.previous_sender or ''
        text=''.join(message['parts']).strip()
        if not message['service'] and not message['forwarded'] and sender and text:
            self.messages.append({'id':message['id'],'sender':sender,'date':message['date'],'text':text})


def read_html_folder(path: Path) -> list[dict]:
    files=sorted(path.glob('messages*.html'),key=lambda p:int(re.search(r'(\d*)\.html$',p.name).group(1) or 1))
    if not files: raise ValueError('No Telegram HTML message pages found')
    if len(files)>1000 or sum(p.stat().st_size for p in files)>200*1024*1024:
        raise ValueError('Export is too large for this importer')
    parser=TelegramHTML()
    for page in files:
        parser.feed(page.read_text(encoding='utf-8-sig'))
        parser.finish()
    parser.close()
    seen=set()
    messages=[]
    for row in parser.messages:
        key=(row['id'],row['sender'])
        if key not in seen:
            messages.append(row)
            seen.add(key)
    return messages


def read_json_export(path: Path) -> list[dict]:
    if path.stat().st_size>100*1024*1024: raise ValueError('Export exceeds 100 MB')
    export=json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(export,dict) or not isinstance(export.get('messages'),list):
        raise ValueError('Choose the JSON export of one chat')
    result=[]
    for row in export['messages']:
        if row.get('type')!='message' or row.get('forwarded_from') or row.get('via_bot'): continue
        text=row.get('text','')
        if isinstance(text,list): text=''.join(x if isinstance(x,str) else x.get('text','') for x in text)
        if isinstance(text,str) and text.strip() and row.get('from'):
            result.append({'id':str(row.get('id','')),'sender':row['from'],'sender_id':row.get('from_id'),
                           'date':row.get('date',''),'text':text.strip()})
    return result


def inspection(messages: list[dict]) -> dict:
    senders={}
    for row in messages: senders[row['sender']]=senders.get(row['sender'],0)+1
    return {'text_messages':len(messages),'senders':senders,'text_characters':sum(len(r['text']) for r in messages),
            'first_date':messages[0]['date'] if messages else None,'last_date':messages[-1]['date'] if messages else None}
