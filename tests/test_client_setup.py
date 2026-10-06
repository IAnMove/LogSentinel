import json
import os
from pathlib import Path
import subprocess
import time

import pytest

from logsentinel import client_setup as setup


@pytest.fixture
def package(tmp_path):
    cert=tmp_path/'ca.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
                    '-subj','/CN=localhost','-keyout',str(tmp_path/'key.pem'),'-out',str(cert)],check=True,capture_output=True)
    return dict(logsentinel_enrollment=1,receiver='https://127.0.0.1:8767',source_id='source-01',code='synthetic-one-use',
                ca_certificate=cert.read_text(),expires=int(time.time()+3600))


def test_plan_is_unprivileged_and_does_not_mutate_or_reveal_the_code(package,tmp_path,monkeypatch,capsys):
    path=tmp_path/'alta.json';path.write_text(json.dumps(package))
    monkeypatch.setattr(setup,'CONFIG',tmp_path/'config')
    monkeypatch.setattr(setup.os,'geteuid',lambda:1000)
    monkeypatch.setattr(setup,'bootstrap',lambda *_:pytest.fail('plan must not install'))
    monkeypatch.setattr(setup,'receiver_check',lambda *_:pytest.fail('plan must not send requests'))
    setup.main(['--package',str(path),'--plan'])
    output=capsys.readouterr().out
    assert 'journal del sistema' in output
    assert 'solo entradas nuevas' in output
    assert package['code'] not in output
    assert path.exists() and not (tmp_path/'config').exists()


@pytest.mark.parametrize('url',['http://host:8767','https://user:secret@host','https://host/?token=secret','https://host/#fragment','https://host/\nline'])
def test_package_refuses_unsafe_receiver_addresses(package,tmp_path,url):
    package['receiver']=url;path=tmp_path/'alta.json';path.write_text(json.dumps(package))
    with pytest.raises(ValueError):setup.read_package(path)


@pytest.mark.parametrize('name',['../etc','x y','x\nExecStart=/bin/sh','x%h','x$HOME','-x','X'])
def test_instance_names_cannot_change_paths_or_units(package,name):
    with pytest.raises(ValueError):setup.selection(name,package)


def test_package_refuses_symlinks_and_oversize_files(tmp_path):
    target=tmp_path/'private';target.write_text('x'*100_001)
    with pytest.raises(ValueError,match='grande'):setup.read_package(target)
    link=tmp_path/'alta';link.symlink_to(target)
    with pytest.raises(OSError):setup.read_package(link)


def test_existing_identity_cannot_be_replaced_and_history_setting_does_not_reset_it(package,tmp_path,monkeypatch):
    desired=setup.selection('logs',package);path=tmp_path/'logs.json'
    path.write_text(json.dumps(desired));path.chmod(0o640)
    # Ownership is tested separately; CI may run without uid 0.
    real=Path.stat
    from types import SimpleNamespace
    monkeypatch.setattr(Path,'stat',lambda p,*a,**kw:SimpleNamespace(st_uid=0,st_mode=real(p,*a,**kw).st_mode) if p==path else real(p,*a,**kw))
    assert setup.validate_existing(path,dict(desired,new_only=False))['new_only'] is True
    with pytest.raises(ValueError,match='otro emisor'):
        setup.validate_existing(path,dict(desired,source_id='another-source'))
    assert json.loads(path.read_text())==desired


def test_private_json_does_not_follow_a_preexisting_link(tmp_path):
    target=tmp_path/'valuable';target.write_text('preserve')
    link=tmp_path/'staged';link.symlink_to(target)
    with pytest.raises(FileExistsError):setup.private_json(link,{'code':'synthetic'})
    assert target.read_text()=='preserve'


def test_private_json_uses_descriptor_ownership_before_writing(tmp_path,monkeypatch):
    monkeypatch.setattr(setup.os,'chown',lambda *_:pytest.fail('never chown a sender-controlled pathname'))
    setup.private_json(tmp_path/'new',{'ok':True},uid=os.getuid(),gid=os.getgid())
    assert (tmp_path/'new').stat().st_mode & 0o777==0o600


def test_rotation_grant_refuses_replaced_file_and_parent_links(tmp_path,monkeypatch):
    monkeypatch.setattr(setup.os,'geteuid',lambda:0)
    monkeypatch.setattr(setup,'command',lambda *_a,**_k:pytest.fail('must not grant access through a symlink'))
    original=tmp_path/'original';original.mkdir();(original/'app.log').write_text('private')
    link=tmp_path/'link';link.symlink_to(original,target_is_directory=True)
    cfg={'path':str(link/'app.log'),'account':'ls-logs','spool':str(tmp_path/'spool')}
    with pytest.raises(OSError):setup.grant_file(cfg)
    cfg['path']=str(tmp_path/'file-link');Path(cfg['path']).symlink_to(original/'app.log')
    with pytest.raises(OSError):setup.grant_file(cfg)


def test_rotation_update_preserves_actions_and_upgrades_only_its_hook(tmp_path,monkeypatch):
    path=tmp_path/'rotation';original='/var/log/app.log {\n postrotate\n  /usr/bin/existing-action\n endscript\n}\n';path.write_text(original)
    real=Path.stat
    from types import SimpleNamespace
    monkeypatch.setattr(Path,'stat',lambda p,*a,**kw:SimpleNamespace(st_uid=0,st_mode=real(p,*a,**kw).st_mode) if p==path else real(p,*a,**kw))
    config=Path('/etc/logsentinel-clients/logs.json')
    first=setup.rotation_update(path,config,Path('/opt/logsentinel-client/runtime-first'))
    assert '/usr/bin/existing-action' in first and first.count('client_setup grant')==1
    path.write_text(first)
    second=setup.rotation_update(path,config,Path('/opt/logsentinel-client/runtime-second'))
    assert 'runtime-first' not in second and second.count('client_setup grant')==1
    assert '/usr/bin/existing-action' in second


def test_managed_directory_rejects_writable_parent_before_creating_child(tmp_path):
    parent=tmp_path/'unsafe';parent.mkdir();parent.chmod(0o777)
    with pytest.raises(ValueError):setup.managed_directory(parent/'new')
    assert not (parent/'new').exists()


def test_reusing_enrollment_command_cannot_bypass_safe_upgrade(package,tmp_path,monkeypatch):
    from types import SimpleNamespace
    desired=setup.selection('logs',package)
    units=tmp_path/'units';units.mkdir()
    (units/'logsentinel-client-logs.service').write_text('existing service')
    monkeypatch.setattr(setup,'UNITS',units)
    monkeypatch.setattr(setup,'validate_existing',lambda *_:dict(desired))
    calls=[]
    monkeypatch.setattr(setup,'upgrade_client',lambda args,old,runtime:calls.append((args.name,old,runtime)))
    monkeypatch.setattr(setup,'receiver_check',lambda *_:pytest.fail('upgrade must not enroll or depend on expired package'))
    runtime=tmp_path/'runtime'
    setup.configure(SimpleNamespace(name='logs'),desired,package,runtime)
    assert calls==[('logs',desired,runtime)]


def test_a_package_given_on_an_upgrade_is_said_to_be_unused_with_the_rotation_route(package,tmp_path,monkeypatch,capsys):
    from types import SimpleNamespace
    desired=setup.selection('logs',package)
    units=tmp_path/'units';units.mkdir()
    (units/'logsentinel-client-logs.service').write_text('existing service')
    monkeypatch.setattr(setup,'UNITS',units)
    monkeypatch.setattr(setup,'validate_existing',lambda *_:dict(desired))
    monkeypatch.setattr(setup,'upgrade_client',lambda args,old,runtime:None)
    setup.configure(SimpleNamespace(name='logs',package='/tmp/alta-nueva.json'),desired,package,tmp_path/'runtime')
    output=capsys.readouterr().out
    assert 'NO se canjea' in output
    assert 'logsentinel enroll /tmp/alta-nueva.json --spool '+desired['spool'] in output
    assert desired['account'] in output


def test_plan_shows_the_certificate_fingerprint_to_compare(package,tmp_path,monkeypatch,capsys):
    path=tmp_path/'alta.json';path.write_text(json.dumps(package))
    monkeypatch.setattr(setup,'CONFIG',tmp_path/'config')
    setup.main(['--package',str(path),'--plan'])
    assert setup.ca_fingerprint(package['ca_certificate']) in capsys.readouterr().out


@pytest.mark.parametrize('style',[str,lambda f:f.upper().replace('SHA256:','sha256:'),lambda f:f.removeprefix('sha256:'),
                                  lambda f:':'.join(f.removeprefix('sha256:')[i:i+2] for i in range(0,64,2)).upper()])
def test_the_fingerprint_can_be_given_in_any_common_format(package,style):
    actual=setup.ca_fingerprint(package['ca_certificate'])
    assert setup.confirm_ca(package,style(actual))==actual


def test_a_swapped_package_is_refused_even_though_its_own_fingerprint_matches(package):
    with pytest.raises(ValueError,match='no coincide'):setup.confirm_ca(package,'sha256:'+'0'*64)


def test_without_a_fingerprint_a_script_cannot_proceed(package):
    with pytest.raises(ValueError,match='--ca-fingerprint'):setup.confirm_ca(package,None,interactive=False)


def test_a_terminal_operator_pastes_the_fingerprint_from_the_central(package,monkeypatch):
    actual=setup.ca_fingerprint(package['ca_certificate'])
    monkeypatch.setattr('builtins.input',lambda *_:actual)
    assert setup.confirm_ca(package,None,interactive=True)==actual
    monkeypatch.setattr('builtins.input',lambda *_:'sha256:'+'f'*64)
    with pytest.raises(ValueError,match='no coincide'):setup.confirm_ca(package,None,interactive=True)
    monkeypatch.setattr('builtins.input',lambda *_:'not a fingerprint')
    with pytest.raises(ValueError,match='64 dígitos'):setup.confirm_ca(package,None,interactive=True)


def test_enroll_command_checks_the_fingerprint_before_redeeming(package,tmp_path,monkeypatch):
    from typer.testing import CliRunner
    from logsentinel import cli
    from logsentinel.portal import enrollment_client
    calls=[]
    monkeypatch.setattr(enrollment_client,'claim',lambda *a:calls.append(a) or dict(
        source_id='s',receiver='https://127.0.0.1:8767',token_path=str(tmp_path/'t'),ca_path='',fingerprint=''))
    path=tmp_path/'alta.json';path.write_text(json.dumps(package))
    run=lambda *extra:CliRunner().invoke(cli.app,['enroll',str(path),'--spool',str(tmp_path/'spool'),*extra])
    assert run().exit_code!=0 and not calls
    assert run('--ca-fingerprint','sha256:'+'0'*64).exit_code==1 and not calls
    assert run('--ca-fingerprint','nonsense').exit_code!=0 and not calls
    assert run('--ca-fingerprint',setup.ca_fingerprint(package['ca_certificate'])).exit_code==0
    assert len(calls)==1
