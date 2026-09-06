"""Optional sender: durable local queue, stable event IDs and receiver ACKs.

Run through a loopback SSH tunnel or HTTPS. No source file is modified.
"""
import asyncio
import json
import os
from urllib.parse import urlsplit
import httpx
from .collect import Collector
from .models import Source,check_url
from .store import Store

async def forward(path,receiver,source_id,token,directory,once=False):
    check_url(receiver)
    if urlsplit(receiver).scheme!='https' and urlsplit(receiver).hostname not in ('localhost','127.0.0.1','::1'):
        raise ValueError('Use HTTPS or a loopback SSH tunnel')
    store=Store(directory);collector=Collector(store)
    source=store.get('source','sender')
    if source is None:
        model=Source(name='Forwarded file',machine_id='sender',path=path,enabled=True,history=True)
        store.put('source',model.model_dump(),'sender');source=store.get('source','sender')
    elif source['path']!=path:
        raise ValueError('This spool belongs to another path; choose a different spool directory')
    try:
        async with httpx.AsyncClient(timeout=20,trust_env=False,follow_redirects=False) as client:
            while True:
                await asyncio.to_thread(collector.poll,source)
                rows=store.events(source_id='sender',status='pending',limit=100)
                if rows:
                    payload={'events':[]};size=0
                    for e in rows:
                        item={'id':e['id'],'raw':e.get('raw',e['message'])};cost=len(json.dumps(item).encode())
                        if size+cost>3_000_000:break
                        payload['events'].append(item);size+=cost
                    try:
                        response=await client.post(receiver.rstrip('/')+'/ingest/'+source_id,headers={'Authorization':'Bearer '+token},json=payload)
                        response.raise_for_status();result=response.json()
                        ids=[e['id'] for e in payload['events']]
                        if result.get('status')!='durable' or set(result.get('acknowledged',[]))!=set(ids):raise ValueError('Receiver did not acknowledge the complete batch')
                        store.mark(ids,'sent')
                        store.discard_sent()
                    except (httpx.HTTPError,ValueError):
                        if once:raise RuntimeError('Forwarding failed; spool retained for retry') from None
                if once:return
                await asyncio.sleep(2)
    finally:
        collector.close()
