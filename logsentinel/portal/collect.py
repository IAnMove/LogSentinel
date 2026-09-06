"""Bounded file imports and journal polling with durable source checkpoints."""
from __future__ import annotations
import gzip
import bz2
import lzma
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from logsentinel.collectors.file_tailer import FileTailerCollector
from logsentinel.collectors.journald import JournaldCollector
from logsentinel.config import JournaldSourceConfig
from .store import dumps

MAX_LINE=256_000

def discovery():
    info={}
    try:
        for line in Path('/etc/os-release').read_text().splitlines():
            if '=' in line:
                k,v=line.split('=',1);info[k]=v.strip('"')
    except OSError:pass
    candidates=['/var/log/auth.log','/var/log/syslog','/var/log/secure','/var/log/messages','/var/log/kern.log']
    return {'hostname':os.uname().nodename,'os':info.get('PRETTY_NAME','Linux'),'journalctl':bool(shutil.which('journalctl')),
            'files':[{'path':p,'readable':os.access(p,os.R_OK)} for p in candidates if Path(p).is_file()]}

def normalize(line,path,origin):
    entry=FileTailerCollector.parse_log_line(line,source_path=path)
    return dict(entry.model_dump(mode='json'),origin=origin)

class Collector:
    def __init__(self,store):self.store=store

    def poll(self,source):
        if not source['enabled']:return 0
        total=0
        try:
            if source['kind']=='journald':total=self.journal(source)
            elif source['kind']=='push':return 0
            else:
                root=Path(source['path']).expanduser().resolve()
                paths=[root] if source['kind']=='file' else sorted(root.glob(source['pattern']))[:100]
                if not paths:raise OSError('No matching readable files')
                for path in paths:
                    if source['kind']=='folder' and (path.is_symlink() or not path.resolve().is_relative_to(root)):
                        continue
                    if path.is_file():total+=self.file(source,path)
            self.store.set_meta('health:'+source['id'],dumps({'status':'ok','checked':time.time(),'new_events':total}))
        except Exception as exc:
            self.store.set_meta('health:'+source['id'],dumps({'status':'error','checked':time.time(),'error':str(exc)[:300]}))
        return total

    def file(self,source,path):
        stat=path.stat();key=str(path)
        old=self.store.cursor(source['id'],key) or {}
        sig=[stat.st_dev,stat.st_ino];offset=0
        if not old:
            with self.store.connect() as db:
                for row in db.execute('SELECT data FROM cursors WHERE source_id=?',(source['id'],)):
                    candidate=json.loads(row[0])
                    if candidate.get('identity')==sig:
                        old=candidate;break
        if path.suffix in ('.zst','.zip','.tar'):
            raise ValueError('Unsupported archive; supply plain text, gzip, xz or bz2')
        compressed=path.suffix in ('.gz','.xz','.bz2')
        if compressed:
            stamp=[stat.st_size,stat.st_mtime_ns]
            if old.get('stamp')!=stamp:
                self.store.ingest(source,[],key,{'stamp':stamp,'stable':False})
                return 0
            if old.get('done'):return 0
            # A new archive is imported only after an unchanged polling interval.
            if stat.st_size>64*1024*1024:raise ValueError('Archive exceeds 64 MiB input limit')
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            generation='gz:'+digest
            offset=old.get('offset',0)
            opener={'.gz':gzip.open,'.xz':lzma.open,'.bz2':bz2.open}[path.suffix]
        else:
            generation=old.get('generation',f'{stat.st_dev}:{stat.st_ino}:{stat.st_ctime_ns}')
            opener=open
            if old.get('identity')==sig and stat.st_size>=old.get('offset',0):
                offset=old.get('offset',0)
                with path.open('rb') as f:
                    f.seek(max(0,offset-64));check=f.read(min(64,offset))
                if hashlib.sha256(check).hexdigest()!=old.get('tail',hashlib.sha256(b'').hexdigest()):
                    offset=0;generation=f'{stat.st_dev}:{stat.st_ino}:{stat.st_ctime_ns}'
            elif old:
                generation=f'{stat.st_dev}:{stat.st_ino}:{stat.st_ctime_ns}'
            elif not source.get('history'):
                offset=stat.st_size
        entries=[];used=0;done=False
        with opener(path,'rb') as f:
            f.seek(offset)
            while used<source['max_batch_bytes'] and len(entries)<1000:
                begin=f.tell();line=f.readline(MAX_LINE+1)
                if not line:
                    done=True;break
                if len(line)>MAX_LINE:
                    raise ValueError('Event exceeds 256 KB; change source format or explicit source limit policy')
                if not line.endswith(b'\n') and not compressed:
                    f.seek(begin);break
                text=line.decode('utf-8',errors='replace').rstrip('\r\n')
                if source.get('multiline') and text.startswith((' ','\t')) and entries:
                    entries[-1]['message']+='\n'+text
                    entries[-1]['raw']+='\n'+text
                elif text:
                    entries.append(normalize(text,key,f'{generation}:{begin}'))
                used+=len(line)
            end=f.tell()
            tail=''
            if not compressed:
                f.seek(max(0,end-64));tail=hashlib.sha256(f.read(min(64,end))).hexdigest()
        cursor={'identity':sig,'generation':generation,'offset':end,'tail':tail}
        if compressed:cursor.update(stamp=stamp,stable=True,done=done)
        if compressed and end>128*1024*1024:raise ValueError('Archive exceeds 128 MiB expanded limit')
        count=self.store.ingest(source,entries,key,cursor)
        self.store.metric(source['id'],'read_bytes',used)
        return count

    def journal(self,source):
        cursor=self.store.cursor(source['id'],'journal') or {}
        cmd=['journalctl','--no-pager','-o','json']
        if cursor.get('cursor'):cmd+=['--after-cursor',cursor['cursor']]
        else:cmd+=['-n','500' if source.get('history') else '1']
        # Timeout/output bounded using a temporary spool, not communicate on unlimited output.
        import tempfile
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as err:
            proc=subprocess.Popen(cmd,stdout=output,stderr=err)
            deadline=time.monotonic()+3
            while proc.poll() is None and time.monotonic()<deadline and output.tell()<source['max_batch_bytes']:
                time.sleep(.02)
            if proc.poll() is None:proc.terminate()
            try:proc.wait(timeout=2)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
            if proc.returncode not in (0,-15):raise OSError('journalctl failed; check journal permissions/cursor')
            output.seek(0);raw=output.read(source['max_batch_bytes'])
        collector=JournaldCollector(JournaldSourceConfig())
        entries=[];last=None
        for line in raw.splitlines(keepends=True):
            if not line.endswith(b'\n'):break
            data=json.loads(line);last=data.get('__CURSOR')
            e=collector._parse_json_line(line.decode(errors='replace'))
            if e and last:entries.append(dict(e.model_dump(mode='json'),origin='journal:'+last))
        if last:
            if not cursor and not source.get('history'):entries=[]
            return self.store.ingest(source,entries,'journal',{'cursor':last})
        return 0
