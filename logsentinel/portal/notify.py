"""Persistent per-destination outbox; no network calls when saving settings."""
from __future__ import annotations
import asyncio
import hashlib
import hmac
import html
import json
import os
from pathlib import Path
import shutil
import time
import httpx
from .rules import matches,redact,sanitize
from .store import uid,dumps

RANK={'LOW':1,'MEDIUM':2,'HIGH':3,'CRITICAL':4}

def enqueue(store,problem_id):
    problem=store.problem(problem_id)
    if not problem:return
    evidence=problem['evidence']
    muted=False
    for rule in store.objects('rule'):
        if rule['action']!='mute':continue
        try:
            if evidence and all(matches(rule,e,problem_id) for e in evidence):muted=True
        except Exception:store.set_meta('rule_error:'+rule['id'],'Mute filter failed; not applied')
    payload={'schema_version':1,'event_type':'problem.updated','problem_id':problem_id,'machine_id':problem['machine_id'],
             'title':redact(problem['title']),'summary':redact(problem['data']['summary']),'severity':problem['severity'],'count':problem['count'],'first_seen':problem['first_seen'],'last_seen':problem['last_seen']}
    machine=store.get('machine',problem['machine_id']);payload['machine']=redact(machine['name'] if machine else 'Unknown')
    for dest in store.objects('destination'):
        if not dest.get('enabled'):continue
        if dest.get('machine_id') and dest['machine_id']!=problem['machine_id']:continue
        if dest.get('source_id') and dest['source_id'] not in {e['source_id'] for e in evidence}:continue
        if RANK[problem['severity']]<RANK[dest['min_severity']]:continue
        with store.connect() as db:
            recent=db.execute("SELECT payload FROM deliveries WHERE destination_id=? AND problem_id=? AND created>? ORDER BY created DESC LIMIT 1",(dest['id'],problem_id,time.time()-dest['cooldown_seconds'])).fetchone()
            cooldown=recent and RANK[json.loads(recent[0])['severity']]>=RANK[problem['severity']]
            id=uid();message=dict(payload,delivery_id=id)
            db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?,?,?,?,?,?)',(id,dest['id'],problem_id,dumps(message),'muted' if muted or cooldown else 'pending',0,time.time(),time.time(),time.time(),None))

class Outbox:
    def __init__(self,store):self.store=store;self.lock=asyncio.Lock()

    async def send(self,dest,payload):
        payload=sanitize(payload,(dest.get('token'),dest.get('secret'),self.store.settings().llm.api_key))
        text=f"[{payload.get('severity','INFO')}] {payload.get('machine','LogSentinel')}\n{payload.get('title','Prueba de notificación')}\n{payload.get('summary','Configuración de LogSentinel comprobada.')}\nProblema: {payload.get('problem_id','test')}"
        text=redact(text,(dest.get('token'),dest.get('secret')))
        kind=dest['kind']
        if kind=='file':
            name=dest.get('path') or 'alerts.jsonl'
            if Path(name).name!=name:raise ValueError('File destination must be a filename within notifications/')
            folder=self.store.directory/'notifications';folder.mkdir(mode=0o700,exist_ok=True)
            path=folder/name
            with path.open('a',encoding='utf-8') as f:f.write(dumps(payload)+'\n');f.flush();os.fsync(f.fileno())
            os.chmod(path,0o600)
            return 'delivered'
        if kind=='system':
            binary=shutil.which('notify-send')
            if not binary or not any(os.environ.get(k) for k in ('DISPLAY','WAYLAND_DISPLAY','DBUS_SESSION_BUS_ADDRESS')):
                raise ValueError('No desktop notification session is available')
            proc=await asyncio.create_subprocess_exec(binary,'--app-name=LogSentinel','--', 'LogSentinel',text[:3000],stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
            try:await asyncio.wait_for(proc.wait(),10)
            finally:
                if proc.returncode is None:proc.kill();await proc.wait()
            if proc.returncode:raise ValueError('Desktop notification was rejected')
            return 'accepted'
        headers=dict(dest.get('headers',{}));url=dest.get('url','');body=payload
        if kind=='telegram':
            url=f"https://api.telegram.org/bot{dest['token']}/sendMessage"
            body={'chat_id':dest['chat_id'],'text':text[:4000]}
        elif kind=='slack':body={'text':text[:3500],'mrkdwn':False,'unfurl_links':False,'unfurl_media':False}
        elif kind=='discord':body={'content':text[:1900],'allowed_mentions':{'parse':[]}}
        raw=dumps(body).encode();headers['Content-Type']='application/json'
        if kind=='hermes':
            ts=str(int(time.time()))
            headers['X-Webhook-Timestamp']=ts
            headers['X-Webhook-Signature-V2']=hmac.new(dest['secret'].encode(),ts.encode()+b'.'+raw,hashlib.sha256).hexdigest()
            headers['X-Request-ID']=payload['delivery_id']
        else:headers['X-Request-ID']=payload['delivery_id']
        async with httpx.AsyncClient(timeout=15,follow_redirects=False,trust_env=False) as client:
            response=await client.post(url,content=raw,headers=headers)
        if response.status_code==429:raise RuntimeError('Rate limited; retry later')
        if response.status_code>=500:raise RuntimeError('Destination unavailable')
        if not 200<=response.status_code<300:raise ValueError(f'Destination rejected request (HTTP {response.status_code})')
        if kind=='telegram' and response.json().get('ok') is not True:raise ValueError('Telegram rejected message')
        if kind=='hermes':
            status=response.json().get('status')
            if status in ('delivered','duplicate'):return 'delivered'
            if status=='ignored':return 'ignored'
        return 'accepted' if kind in ('hermes','n8n','webhook') else 'delivered'

    async def drain(self):
        async with self.lock:
            with self.store.connect() as db:
                rows=[dict(r) for r in db.execute("SELECT * FROM deliveries WHERE status IN ('pending','retry') AND next_try<=? ORDER BY created LIMIT 20",(time.time(),))]
            for row in rows:
                dest=self.store.get('destination',row['destination_id'])
                status='cancelled';error=None;cancelled=False
                if dest and dest.get('enabled'):
                    with self.store.connect() as db:db.execute("UPDATE deliveries SET status='sending',attempts=attempts+1 WHERE id=?",(row['id'],))
                    try:status=await self.send(dest,json.loads(row['payload']))
                    except (asyncio.CancelledError,httpx.TimeoutException) as exc:
                        cancelled=isinstance(exc,asyncio.CancelledError)
                        status='unknown';error='Delivery interrupted or timed out; remote acceptance unknown'
                    except Exception as exc:
                        status='retry' if isinstance(exc,RuntimeError) and row['attempts']<2 else 'failed'
                        error=f'{type(exc).__name__}: delivery failed; verify destination configuration'
                with self.store.connect() as db:
                    db.execute('UPDATE deliveries SET status=?,error=?,updated=?,next_try=? WHERE id=?',(status,error,time.time(),time.time()+min(300,10*2**row['attempts']),row['id']))
                if cancelled:raise asyncio.CancelledError

    async def test(self,dest):
        id=uid();payload={'schema_version':1,'delivery_id':id,'event_type':'test','title':'Prueba de LogSentinel','summary':'Este es un mensaje de prueba solicitado desde el portal.'}
        status='failed';error=None
        try:status=await self.send(dest,payload)
        except Exception as exc:error=type(exc).__name__+': verify credentials, connectivity and destination'
        with self.store.connect() as db:
            db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?,?,?,?,?,?)',(id,dest['id'],'test',dumps(payload),status,1,time.time(),time.time(),time.time(),error))
        return {'status':status,'error':error}
