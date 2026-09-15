"""Install a Linux log sender from a checkout, using only stdlib until bootstrapped."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import ssl
import stat
import subprocess
import sys
import tempfile
import time
import urllib.parse

INSTALL = Path('/opt/logsentinel-client')
CONFIG = Path('/etc/logsentinel-clients')
DATA = Path('/var/lib/logsentinel-client')
UNITS = Path('/etc/systemd/system')


def command(*args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def private_json(path, value, uid=0, gid=0, mode=0o600):
    path = Path(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, 'w') as f:
        os.fchown(f.fileno(), uid, gid)
        os.fchmod(f.fileno(), mode)
        json.dump(value, f, indent=2)


def read_package(path):
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise ValueError('El alta debe ser un archivo regular.')
        raw=f.read(100_001)
    if len(raw)>100_000:
        raise ValueError('El archivo de alta es demasiado grande.')
    package = json.loads(raw)
    if not isinstance(package, dict) or package.get('logsentinel_enrollment') != 1:
        raise ValueError('Selecciona el JSON de alta generado por el central.')
    url = package.get('receiver', '')
    if not isinstance(url, str) or any(ord(c) < 32 for c in url):
        raise ValueError('Dirección de recepción inválida.')
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('El alta debe indicar un receptor HTTPS sin credenciales en la URL.')
    for key in ('source_id', 'code', 'ca_certificate'):
        if not isinstance(package.get(key), str) or not package[key]:
            raise ValueError('El alta está incompleta: falta ' + key)
    if type(package.get('expires')) is not int:
        raise ValueError('El alta necesita una fecha de caducidad válida.')
    if not re.fullmatch(r'[a-zA-Z0-9:_-]{1,200}', package['source_id']):
        raise ValueError('Identificador de fuente inválido.')
    ssl.create_default_context(cadata=package['ca_certificate'])
    return package


def selection(name, package, file=None, history=False):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,19}', name):
        raise ValueError('El nombre debe tener 1–20 letras minúsculas, números o guiones y empezar por letra.')
    return dict(name=name, account='ls-' + name, receiver=package['receiver'].rstrip('/'),
                source_id=package['source_id'], journal=file is None,
                path=str(Path(file).expanduser().resolve()) if file else None,
                new_only=not history, spool=str(DATA/name))


def managed_directory(path, mode=0o755):
    path = Path(path)
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError('Una ruta de instalación es un enlace simbólico: ' + str(parent))
        if not parent.exists():
            continue
        info = parent.stat()
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('La ruta de instalación debe pertenecer a root y no permitir escritura ajena: ' + str(parent))
    path.mkdir(mode=mode, parents=True, exist_ok=True)


def validate_existing(config_path, desired):
    """Never convert another service, credential or cursor into this enrollment."""
    if not config_path.exists():
        return None
    if config_path.is_symlink() or config_path.stat().st_uid != 0 or config_path.stat().st_mode & 0o022:
        raise ValueError('La configuración existente no está protegida por root.')
    old = json.loads(config_path.read_text())
    if any(old.get(k) != desired.get(k) for k in ('account', 'receiver', 'source_id', 'journal', 'path', 'spool')):
        raise ValueError('Este nombre pertenece a otro emisor. Usa otro --name; no se cambia su cola ni su credencial.')
    return old


def runtime_for(repo):
    digest = hashlib.sha256()
    digest.update(sys.version.encode())
    inputs = [repo/'pyproject.toml', *list((repo/'logsentinel').rglob('*.py'))]
    constraints = repo/'constraints-tested-py312.txt'
    if sys.version_info[:2] == (3, 12) and constraints.is_file():
        inputs.append(constraints)
    for path in sorted(inputs):
        digest.update(str(path.relative_to(repo)).encode())
        digest.update(path.read_bytes())
    return INSTALL / ('runtime-' + digest.hexdigest()[:16])


def bootstrap(repo):
    managed_directory(INSTALL)
    runtime = runtime_for(repo)
    if (runtime/'ready').is_file() and not runtime.is_symlink():
        managed_directory(runtime)
        return runtime
    managed_directory(runtime)
    # Reusing an incomplete, unpublished runtime is safe: no service references it.
    python = runtime/'bin/python'
    build = subprocess.run([sys.executable, '-m', 'venv', str(runtime)], capture_output=True, text=True)
    if build.returncode:
        if shutil.which('apt-get'):
            command('apt-get', 'install', '-y', 'python3-venv')
            command(sys.executable, '-m', 'venv', runtime)
        else:
            raise ValueError('Instala el soporte venv/pip de Python de tu distribución y repite el comando.')
    args = [str(python), '-m', 'pip', 'install', '--upgrade']
    constraints = repo/'constraints-tested-py312.txt'
    if sys.version_info[:2] == (3, 12) and constraints.is_file():
        args += ['-c', str(constraints)]
    # Build outside the checkout, avoiding stale build/ artifacts and root-owned files in it.
    with tempfile.TemporaryDirectory(prefix='logsentinel-client-build-') as temp:
        source = Path(temp)/'source'
        source.mkdir()
        for name in ('pyproject.toml', 'README.md', 'LICENSE'):
            shutil.copyfile(repo/name, source/name)
        shutil.copytree(repo/'logsentinel', source/'logsentinel', ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        print('Instalando LogSentinel en un entorno Python aislado...', flush=True)
        with (runtime/'install.log').open('w') as log:
            try:
                command(*args, source, stdout=log, stderr=subprocess.STDOUT)
            except subprocess.CalledProcessError:
                raise ValueError('Falló la instalación. Consulta '+str(runtime/'install.log')) from None
    (runtime/'ready').write_text('installed\n')
    return runtime


def receiver_check(package, journal):
    from .portal.enrollment_client import validate
    from .portal.models import check_url
    from .portal.network import CheckedTransport
    import httpx
    validate(package)
    check_url(package['receiver'])
    context = ssl.create_default_context(cadata=package['ca_certificate'])
    with httpx.Client(transport=CheckedTransport(verify=context), trust_env=False, timeout=15) as client:
        health = client.get(package['receiver'].rstrip('/')+'/healthz')
        health.raise_for_status()
        if journal:
            info = client.get(package['receiver'].rstrip('/')+'/ingest-info')
            data = info.json() if info.status_code == 200 else {}
            if not isinstance(data,dict) or not isinstance(data.get('formats'),list) or 'journal' not in data['formats']:
                raise ValueError('El receptor necesita actualizarse para recibir el journal.')


def unit_text(config_path, runtime, desired):
    # All interpolated paths derive from the validated instance name or managed runtime.
    return f'''[Unit]
Description=LogSentinel log sender ({desired['name']})
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User={desired['account']}
Group={desired['account']}
ExecStart={runtime}/bin/python -m logsentinel.client_setup run --config {config_path}
Restart=on-failure
RestartSec=60
Nice=10
IOWeight=10
IOSchedulingClass=idle
UMask=0077
NoNewPrivileges=yes
CapabilityBoundingSet=
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes
ReadWritePaths={desired['spool']}

[Install]
WantedBy=multi-user.target
'''


def rotation_hook(config_path, runtime):
    return f'\t\t{runtime}/bin/python -m logsentinel.client_setup grant --config {config_path}\n'


def rotation_update(path, config_path, runtime):
    """Add to one explicit postrotate block; preserve every existing action."""
    text = path.read_text()
    if path.is_symlink() or path.stat().st_uid != 0 or path.stat().st_mode & 0o022:
        raise ValueError('La configuración de logrotate debe estar protegida por root.')
    pattern = r'(?m)^(\s*)postrotate[ \t]*$'
    if len(re.findall(pattern, text)) != 1:
        raise ValueError('El archivo de logrotate debe tener un único bloque postrotate; selecciona uno explícito.')
    if str(config_path) in text:
        # Already managed; updates replace only our invocation.
        return re.sub(r'(?m)^.* -m logsentinel\.client_setup grant --config '+re.escape(str(config_path))+r'$', rotation_hook(config_path, runtime).rstrip('\n'), text)
    return re.sub(pattern, lambda match: match.group(0)+'\n'+rotation_hook(config_path,runtime).rstrip('\n'), text, count=1)


def grant_file(cfg):
    from .portal.source_paths import validate_source_handle
    if os.geteuid() != 0:
        raise ValueError('La concesión de lectura necesita root.')
    # A replaced log must never turn the privileged rotation hook into a grant on a symlink target.
    path = Path(cfg['path'])
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('La fuente debe ser una ruta absoluta normalizada.')
    parent_fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = next_fd
        fd = os.open(path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent_fd)
    finally:
        os.close(parent_fd)
    with os.fdopen(fd, 'rb') as handle:
        validate_source_handle(handle, cfg['spool'])
        command('setfacl', '-m', 'u:'+cfg['account']+':r', '/proc/self/fd/'+str(handle.fileno()), pass_fds=(handle.fileno(),))


def configure(args, desired, package, runtime):
    from . import hostprep
    from .portal.source_paths import validate_source_path
    config_path = CONFIG/(args.name+'.json')
    old = validate_existing(config_path, desired)
    unit = UNITS/('logsentinel-client-'+args.name+'.service')
    if old and unit.exists():
        # Re-running the original enrollment command is also an upgrade. It must
        # not bypass the coherent backup or restart a deliberately stopped unit.
        return upgrade_client(args, old, runtime)
    spool = Path(desired['spool'])
    account = desired['account']
    if not old and (unit.exists() or spool.exists()):
        raise ValueError('Ya existe un servicio o spool sin esta configuración. Consérvalo y usa otro --name.')
    if not old and (hostprep.account_exists(account) or hostprep.group_exists(account)):
        raise ValueError('La cuenta ya existía fuera de este instalador. Usa otro --name.')
    if not desired['journal']:
        path = validate_source_path(desired['path'], spool)
        if not path.is_file() or Path(desired['path']).is_symlink():
            raise ValueError('Selecciona un archivo regular, sin enlace simbólico.')
        if not args.logrotate_config:
            raise ValueError('Para un archivo, indica --logrotate-config con su bloque postrotate; el journal no necesita este ajuste.')
        rotation = Path(args.logrotate_config).resolve(strict=True)
        replacement = rotation_update(rotation, config_path, runtime)
    print('Comprobando receptor y certificado HTTPS...', flush=True)
    receiver_check(package, desired['journal'])
    if not old and package.get('expires', 0) < time.time():
        raise ValueError('El alta ha caducado. Genera otra en el central.')
    if not desired['journal'] and not shutil.which('setfacl'):
        if shutil.which('apt-get'):
            command('apt-get','install','-y','acl')
        else:
            raise ValueError('Instala el paquete acl y repite el comando.')
    if desired['journal'] and (not shutil.which('journalctl') or not hostprep.group_exists('systemd-journal')):
        raise ValueError('Este equipo no tiene un journal systemd accesible. Selecciona un archivo.')
    if old:
        entry = pwd.getpwnam(account)
        if entry.pw_uid == 0 or entry.pw_shell not in ('/usr/sbin/nologin','/sbin/nologin','/bin/false'):
            raise ValueError('La cuenta existente ya no es una cuenta limitada.')
    else:
        hostprep.apply(hostprep.plan(account, [], journal=desired['journal'], group=account))
    entry = pwd.getpwnam(account)
    managed_directory(CONFIG)
    managed_directory(DATA)
    if not old:
        spool.mkdir(mode=0o700)
        os.chown(spool,entry.pw_uid,entry.pw_gid)
        private_json(config_path, desired, gid=entry.pw_gid, mode=0o640)
    elif spool.is_symlink() or not spool.is_dir() or spool.stat().st_uid != entry.pw_uid:
        raise ValueError('El spool existente no tiene su propietario esperado.')
    if not desired['journal']:
        grant_file(desired)
        if not all(row['readable'] for row in hostprep.verify(account,[Path(desired['path'])])):
            raise ValueError('La cuenta no puede recorrer los directorios del archivo. Revisa prepare-host antes de continuar.')
    else:
        if not all(row['readable'] for row in hostprep.verify(account,[],journal=True)):
            raise ValueError('No se pudo leer el journal con la cuenta limitada.')
    if not (spool/'push-token').is_file():
        # Only enrollment runs under the sender identity; never hand a root-created token to the wrong owner.
        staged = spool/'setup-enrollment.json'
        if staged.exists():
            raise ValueError('Hay un alta temporal pendiente en el spool; revisa ese intento antes de sustituirla.')
        private_json(staged,package,uid=entry.pw_uid,gid=entry.pw_gid)
        try:
            print('Canjeando el alta y guardando la credencial privada...', flush=True)
            result = subprocess.run(['runuser', '-u', account, '--', str(runtime/'bin/logsentinel'),
                                     'enroll', str(staged), '--spool', str(spool)], capture_output=True, text=True)
            if result.returncode:
                raise ValueError('No se pudo canjear el alta. Comprueba la conexión; si el código caducó o ya se usó, genera otro en el central.')
        finally:
            staged.unlink(missing_ok=True)
    # Prove collection and an authenticated heartbeat before enabling the service.
    if not unit.exists():
        command('runuser','-u',account,'--',runtime/'bin/python','-m','logsentinel.client_setup','run','--config',config_path,'--once')
    backup = INSTALL/('backup-'+args.name+'-'+str(time.time_ns()))
    backup.mkdir(mode=0o700)
    previous = unit.read_bytes() if unit.exists() else None
    if previous is not None:
        (backup/'service.before').write_bytes(previous)
    rotation_before = None
    try:
        if not desired['journal']:
            rotation_before = rotation.read_bytes()
            (backup/'logrotate.before').write_bytes(rotation_before)
            rotation.write_text(replacement)
            command('logrotate','--debug',rotation,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        unit.write_text(unit_text(config_path,runtime,desired));unit.chmod(0o644)
        command('systemd-analyze','verify',unit,stdout=subprocess.DEVNULL)
        command('systemctl','daemon-reload')
        command('systemctl','enable','--now',unit.name)
        if old:
            command('systemctl','restart',unit.name)
        command('systemctl','is-active','--quiet',unit.name)
    except BaseException:
        if previous is None:
            subprocess.run(['systemctl','disable','--now',unit.name],capture_output=True)
            unit.unlink(missing_ok=True)
        else:
            unit.write_bytes(previous)
        if rotation_before is not None:
            rotation.write_bytes(rotation_before)
        subprocess.run(['systemctl','daemon-reload'],capture_output=True)
        if previous is not None:
            subprocess.run(['systemctl','restart',unit.name],capture_output=True)
        raise
    try:
        Path(args.package).unlink(missing_ok=True)
    except OSError:
        print('El cliente está activo; elimina manualmente el archivo de alta ya utilizado.', file=sys.stderr)
    print('\nCliente configurado. Conserva la cola y el cursor al reiniciar.')
    print('Servicio:',unit.name,'\nCola:',spool,'\nConfiguración:',config_path)
    print('Estado: sudo systemctl status '+unit.stem)
    print('Errores: sudo journalctl -u '+unit.stem+' -n 30 --no-pager')
    print('Comprueba en el Histórico del central la recepción y, después, la cobertura del análisis.')


def run_sender(config_path, once=False):
    import asyncio
    from .portal.forward import forward
    cfg=json.loads(Path(config_path).read_text())
    token=(Path(cfg['spool'])/'push-token').read_text().strip()
    asyncio.run(forward(cfg['path'],cfg['receiver'],cfg['source_id'],token,cfg['spool'],once,
                        journal=cfg['journal'],new_only=cfg['new_only'],limits=cfg.get('limits')))


def backup_sender(config_path, target):
    """Runs as the sender account; root never opens a sender-controlled database."""
    import sqlite3
    cfg=json.loads(Path(config_path).read_text())
    source=Path(cfg['spool'])/'sentinel.db'
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,timeout=3) as db, sqlite3.connect(target) as dest:
        db.backup(dest,pages=256,sleep=.05)


def upgrade_client(args, desired, runtime):
    """Install a new runtime without enrolling again or resuming a stopped service."""
    config_path=CONFIG/(args.name+'.json')
    validate_existing(config_path,desired)
    unit=UNITS/('logsentinel-client-'+args.name+'.service')
    if not unit.is_file() or unit.is_symlink() or unit.stat().st_uid != 0 or unit.stat().st_mode & 0o022:
        raise ValueError('La unidad existente debe estar protegida por root.')
    entry=pwd.getpwnam(desired['account'])
    if entry.pw_uid==0 or entry.pw_shell not in ('/usr/sbin/nologin','/sbin/nologin','/bin/false'):
        raise ValueError('La cuenta del emisor debe seguir siendo una cuenta limitada.')
    spool=Path(desired['spool'])
    if spool.is_symlink() or not spool.is_dir() or spool.stat().st_uid != entry.pw_uid:
        raise ValueError('La cola existente no tiene su propietario esperado.')
    was_active=subprocess.run(['systemctl','is-active','--quiet',unit.name]).returncode==0
    command('systemctl','stop',unit.name)
    from .portal.sender_safety import io_pressure
    pressure=io_pressure()
    if pressure is not None and pressure>=25:
        raise ValueError('El disco sigue bajo presión de E/S. Cliente detenido; repite la actualización cuando se estabilice.')
    # Budget the coherent backup and the additive index before touching the unit.
    size=sum(p.stat().st_size for p in spool.glob('sentinel.db*') if p.is_file())
    if shutil.disk_usage(INSTALL).free < size*2 + 256*1024**2:
        raise ValueError('Falta espacio para copia y actualización. El cliente queda detenido y conserva su cola.')
    if shutil.disk_usage(spool).free < size + 256*1024**2:
        raise ValueError('Falta espacio en el volumen de la cola para adaptar el índice. El cliente queda detenido; no se elimina evidencia.')
    backup=INSTALL/('backup-'+args.name+'-'+str(time.time_ns()))
    backup.mkdir(mode=0o710)
    os.chown(backup,0,entry.pw_gid)
    previous=unit.read_bytes()
    (backup/'service.before').write_bytes(previous)
    shutil.copyfile(config_path,backup/'config.before.json')
    (backup/'config.before.json').chmod(0o600)
    target=backup/'sentinel.db'
    fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    os.fchown(fd,entry.pw_uid,entry.pw_gid);os.close(fd)
    try:
        low_priority=['nice','-n','10']
        if shutil.which('ionice'):
            low_priority+=['ionice','-c','3']
        command('runuser','-u',desired['account'],'--',*low_priority,runtime/'bin/python','-m','logsentinel.client_setup','backup','--config',config_path,'--target',target)
        os.chown(target,0,0)
        command('runuser','-u',desired['account'],'--',*low_priority,runtime/'bin/python','-m','logsentinel.client_setup','migrate','--config',config_path)
        unit.write_text(unit_text(config_path,runtime,desired));unit.chmod(0o644)
        command('systemd-analyze','verify',unit,stdout=subprocess.DEVNULL)
        command('systemctl','daemon-reload')
        if was_active:
            command('systemctl','start',unit.name)
            command('systemctl','is-active','--quiet',unit.name)
    except BaseException:
        # Do not replace a live queue with its backup: new durable events may exist.
        subprocess.run(['systemctl','stop',unit.name],capture_output=True)
        unit.write_bytes(previous)
        subprocess.run(['systemctl','daemon-reload'],capture_output=True)
        print('Actualización incompleta: cliente detenido; cola intacta. Copia:',backup,file=sys.stderr)
        raise
    finally:
        os.chown(target,0,0)
        backup.chmod(0o700)
    print('Cliente actualizado. Runtime:',runtime)
    print('Copia coherente:',backup)
    print('Se conservan configuración, credenciales, CA, cursor y cola.')
    print('Servicio:', 'activo; obedecerá la pausa del central' if was_active else 'sigue detenido; no se ha reanudado')


def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ('run','grant','backup','migrate'):
        parser=argparse.ArgumentParser()
        parser.add_argument('action');parser.add_argument('--config',required=True);parser.add_argument('--once',action='store_true');parser.add_argument('--target')
        args=parser.parse_args(argv)
        if args.action=='run':
            return run_sender(args.config,args.once)
        if args.action=='backup':
            if not args.target:
                raise ValueError('Falta la ruta de copia.')
            return backup_sender(args.config,args.target)
        if args.action=='migrate':
            from .portal.store import Store
            from .portal.sender import spool_lock
            cfg=json.loads(Path(args.config).read_text())
            store=Store(cfg['spool'])
            binding=json.loads(store.meta('sender_binding'))
            with spool_lock(store,binding):
                store.prepare_sender()
            return
        path=Path(args.config)
        if path.parent!=CONFIG or path.is_symlink() or path.stat().st_uid!=0 or path.stat().st_mode & 0o022:
            raise ValueError('La configuración de permisos debe estar protegida por root.')
        return grant_file(json.loads(path.read_text()))
    parser=argparse.ArgumentParser(description='Configura un emisor Linux. Por defecto: journal y solo entradas nuevas.')
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--package',help='JSON de alta generado por el central')
    mode.add_argument('--upgrade',action='store_true',help='Actualiza una instalación existente sin nueva alta; conserva su estado detenido/activo')
    parser.add_argument('--name',default='logs',help='Nombre de esta instalación (por defecto: logs)')
    parser.add_argument('--file',help='Un archivo en lugar del journal')
    parser.add_argument('--logrotate-config',help='Configuración de rotación del archivo, con un único postrotate')
    parser.add_argument('--include-history',action='store_true',help='Importar también historial en una instalación nueva')
    parser.add_argument('--plan',action='store_true',help='Mostrar el recorrido sin instalar ni enviar nada')
    parser.add_argument('--prepared',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args(argv)
    if sys.platform!='linux' or sys.version_info<(3,10):
        raise ValueError('Se requiere Linux con systemd y Python 3.10 o posterior.')
    if args.upgrade:
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,19}',args.name):
            raise ValueError('Nombre de instalación inválido.')
        config_path=CONFIG/(args.name+'.json')
        if config_path.is_symlink() or config_path.stat().st_uid!=0 or config_path.stat().st_mode & 0o022:
            raise ValueError('La configuración existente debe estar protegida por root.')
        desired=json.loads(config_path.read_text())
        expected=selection(args.name,desired,None if desired['journal'] else desired['path'],not desired['new_only'])
        validate_existing(config_path,expected)
        package=None
    else:
        args.package=str(Path(args.package).expanduser().absolute())
        package=read_package(args.package)
        desired=selection(args.name,package,args.file,args.include_history)
    validate_existing(CONFIG/(args.name+'.json'),desired)
    print('Receptor:',desired['receiver'],'\nLogs:',desired['path'] or 'journal del sistema (todos los servicios)')
    print('Cuenta sin login:',desired['account'],'\nInicio:', 'con histórico' if args.include_history else 'solo entradas nuevas; se conservan cursores existentes',flush=True)
    if args.plan:
        print('Plan: actualizar runtime con copia coherente; conservar identidad y estado del servicio. No se ha cambiado nada.' if args.upgrade else 'Plan: instalar Python aislado, conceder lectura, canjear el alta HTTPS y activar un servicio emisor. No se ha cambiado nada.')
        return
    if os.geteuid()!=0:
        raise ValueError('Ejecuta el mismo comando con sudo. El emisor funcionará después sin root.')
    os.umask(0o022)
    if not Path('/run/systemd/system').is_dir():
        raise ValueError('Este instalador necesita systemd ejecutándose como gestor del sistema.')
    if not args.prepared:
        repo=Path(__file__).resolve().parents[1]
        runtime=bootstrap(repo)
        os.execv(str(runtime/'bin/python'),[str(runtime/'bin/python'),'-m','logsentinel.client_setup',*argv,'--prepared'])
    runtime=Path(sys.prefix)
    if runtime.parent!=INSTALL or not (runtime/'ready').is_file():
        raise ValueError('Usa setup-client.sh desde el repositorio para preparar el instalador.')
    if args.upgrade:
        upgrade_client(args,desired,runtime)
    else:
        configure(args,desired,package,runtime)


if __name__=='__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Interrumpido. Se conservan la cola y las credenciales ya creadas.',file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        # Never print an enrollment object, token or remote response body in logs.
        if sys.argv[1:2]==['run']:
            from .portal.sender_safety import error_detail
            print('Error operativo del cliente: '+json.dumps(error_detail(exc))+'. Cola y cursor conservados.',file=sys.stderr)
        elif isinstance(exc,ValueError) and not isinstance(exc,json.JSONDecodeError):
            print(str(exc),file=sys.stderr)
        else:
            print('No se completó la configuración ('+type(exc).__name__+'). La cola se conserva; revisa el último paso mostrado.',file=sys.stderr)
        sys.exit(1)
