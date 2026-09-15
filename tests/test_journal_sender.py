import asyncio
import hashlib
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from logsentinel.portal import collect
from logsentinel.portal.app import create_app
from logsentinel.portal.forward import forward
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.store import Store

REAL_CLIENT = httpx.AsyncClient
pytestmark = pytest.mark.usefixtures("idle_sender_disk")


@pytest.fixture
def central(tmp_path, monkeypatch):
    app = create_app(tmp_path/'central', background=False)
    store = app.state.store
    machine = store.put('machine', Machine(name='GPU host').model_dump())
    sid = store.put('source', Source(name='Journal', kind='push', enabled=True, machine_id=machine).model_dump())
    store.set_meta('push:'+sid, hashlib.sha256(b'synthetic').hexdigest())
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: client(transport=transport, **{k:v for k,v in kwargs.items() if k!='transport'}))
    return app, store, sid


@pytest.mark.asyncio
async def test_journal_skips_history_and_preserves_metadata_and_cursor(central, tmp_path, monkeypatch):
    app, store, sid = central
    lines=[dict(__CURSOR='c0', MESSAGE='old event', SYSLOG_IDENTIFIER='old-service', PRIORITY='6')]

    def journal(cmd, limit):
        if '--cursor' in cmd:
            index=next(i for i,e in enumerate(lines) if e['__CURSOR']==cmd[cmd.index('--cursor')+1])
            chosen=lines[index:]
        elif '-n' in cmd:
            chosen=lines[-1:]
        else:
            chosen=lines
        return ''.join(json.dumps(e)+'\n' for e in chosen).encode(), False

    monkeypatch.setattr(collect,'read_journal',journal)
    spool=tmp_path/'spool'
    await forward(None,'http://localhost',sid,'synthetic',spool,once=True,journal=True,new_only=True)
    assert store.events()==[]
    assert Store(spool).cursor('sender','journal')=={'cursor':'c0'}
    lines.append(dict(__CURSOR='c1',MESSAGE='write operation failed',_SYSTEMD_UNIT='backup.service',PRIORITY='3',_PID='741',_HOSTNAME='gpu-host',__REALTIME_TIMESTAMP='1788990000123456'))
    await forward(None,'http://localhost',sid,'synthetic',spool,once=True,journal=True,new_only=True)
    event=store.events()[0]
    assert event['message']=='write operation failed'
    assert event['service']=='backup'
    assert event['priority']==3
    assert event['pid']==741
    assert event['hostname']=='gpu-host'
    assert event['metadata']['timestamp_inferred'] is False
    assert '2026-' in event['timestamp']
    assert Store(spool).cursor('sender','journal')=={'cursor':'c1'}
    await forward(None,'http://localhost',sid,'synthetic',spool,once=True,journal=True,new_only=True)
    assert len(store.events())==1
    with pytest.raises(ValueError,match='another path'):
        await forward('/var/log/other','http://localhost',sid,'synthetic',spool,once=True)


@pytest.mark.asyncio
async def test_new_only_file_survives_restarts_and_rotation(central,tmp_path):
    _,store,sid=central
    file=tmp_path/'auth.log';file.write_text('old\n');spool=tmp_path/'spool'
    await forward(str(file),'http://localhost',sid,'synthetic',spool,once=True,new_only=True)
    assert store.events()==[]
    with file.open('a') as f:f.write('new\n')
    await forward(str(file),'http://localhost',sid,'synthetic',spool,once=True,new_only=True)
    file.rename(tmp_path/'auth.log.1');file.write_text('after rotation\n')
    await forward(str(file),'http://localhost',sid,'synthetic',spool,once=True,new_only=True)
    assert {e['message'] for e in store.events()}=={'new','after rotation'}


@pytest.mark.parametrize('payload',[
    [], {'format':'unexpected','events':[]},
    {'format':'journal','events':[{'id':'x','raw':'[]'}]},
    {'format':'journal','events':[{'id':'x','raw':'{"MESSAGE": {"secret":"ignored"}}'}]},
])
def test_invalid_journal_batches_are_rejected_atomically(central,payload):
    app,store,sid=central
    with TestClient(app) as c:
        r=c.post('/ingest/'+sid,json=payload,headers={'Authorization':'Bearer synthetic'})
        assert r.status_code==400
    assert store.events()==[]


@pytest.mark.asyncio
async def test_older_receiver_does_not_ack_journal_as_plain_text(central,tmp_path,monkeypatch):
    _,_,sid=central
    spool=Store(tmp_path/'spool')
    source=Source(name='Journal',machine_id='sender',kind='journald',enabled=True,history=False)
    spool.put('source',source.model_dump(),'sender')
    spool.ingest(spool.get('source','sender'),[dict(origin='one',service='kernel',message='new',raw='{"MESSAGE":"new"}')])
    monkeypatch.setattr(collect.Collector,'journal',lambda *_:0)
    async def old_api(request):return httpx.Response(404)
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:REAL_CLIENT(transport=httpx.MockTransport(old_api)))
    with pytest.raises(RuntimeError,match='spool retained'):
        await forward(None,'http://localhost',sid,'synthetic',spool.directory,once=True,journal=True,new_only=True)
    assert len(spool.events(status='pending'))==1
