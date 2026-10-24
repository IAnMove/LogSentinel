"""Install a Linux log sender from a checkout, using only stdlib until bootstrapped."""
from __future__ import annotations

import argparse
import fcntl
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


def ca_fingerprint(pem):
    return 'sha256:' + hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()


def normalize_fingerprint(text):
    value = str(text).strip().lower()
    value = value.removeprefix('sha256:').replace(':', '').replace(' ', '')
    if not re.fullmatch(r'[0-9a-f]{64}', value):
        raise ValueError('Una huella SHA-256 tiene 64 dígitos hexadecimales.')
    return 'sha256:' + value


def confirm_ca(package, expected=None, interactive=False):
    """The package names the receiver and the CA to trust, so it cannot vouch
    for itself: whoever swaps the file also swaps the fingerprint inside it.
    The operator compares it with what the central printed, out of band."""
    actual = ca_fingerprint(package['ca_certificate'])
    print('Receptor:', package['receiver'])
    print('Huella del certificado del central:', actual, flush=True)
    if not expected and interactive:
        expected = input('Pega la huella que mostró el central para confirmarla: ')
    if not expected:
        raise ValueError('Indica --ca-fingerprint con la huella que mostró el central al crear el alta '
                         '(o ejecuta el instalador en un terminal para pegarla). Sin ella no se puede saber '
                         'si el archivo de alta fue sustituido.')
    if normalize_fingerprint(expected) != actual:
        raise ValueError('La huella no coincide con la del central. No uses este archivo de alta.')
    return actual


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
CPUQuota=25%
MemoryHigh=192M
MemoryMax=256M
OOMScoreAdjust=500
UMask=0077
NoNewPrivileges=yes
CapabilityBoundingSet=
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
ProtectClock=yes
ProtectHostname=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK
RestrictNamespaces=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
LockPersonality=yes
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
        if getattr(args, 'package', None):
            # The package is not redeemed on an upgrade; saying nothing let a
            # person believe a new package had rotated the credential.
            print('Ya hay un emisor "'+args.name+'" con esta identidad: se actualiza el programa y se conserva su credencial. '
                  'El paquete indicado NO se canjea. Para rotar el token o el certificado, ejecuta como la cuenta '+old['account']+': '
                  'logsentinel enroll '+str(args.package)+' --spool '+str(old['spool'])+' --ca-fingerprint HUELLA; y reinicia '+unit.stem+'.', flush=True)
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
                                     'enroll', str(staged), '--spool', str(spool),
                                     '--ca-fingerprint', ca_fingerprint(package['ca_certificate'])],
                                    capture_output=True, text=True)
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
    # The policy flag is root's (the config is root-owned); the result file is
    # written by the root upgrade job. This process only reads both.
    upgrade=dict(enabled=bool(cfg.get('remote_upgrade')),state_path=INSTALL/('upgrade-'+cfg['name']+'.json'))
    asyncio.run(forward(cfg['path'],cfg['receiver'],cfg['source_id'],token,cfg['spool'],once,
                        journal=cfg['journal'],new_only=cfg['new_only'],limits=cfg.get('limits'),upgrade=upgrade))


def backup_sender(config_path, target):
    """Runs as the sender account; root never opens a sender-controlled database."""
    import sqlite3
    cfg=json.loads(Path(config_path).read_text())
    source=Path(cfg['spool'])/'sentinel.db'
    # The account can only write inside its own spool, so that is where the
    # copy is made; it must be a new file, never one somebody put there.
    os.close(os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600))
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,timeout=3) as db, sqlite3.connect(target) as dest:
        db.backup(dest,pages=256,sleep=.05)


def adopt_backup(staged,target):
    """Move what the unprivileged account wrote into root-owned storage.

    The path is sender-controlled, so it is opened without following links and
    must be a regular file; root never opens a database the sender can change."""
    fd=os.open(staged,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError('La copia preparada por la cuenta del emisor no es un archivo regular.')
        out=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(out,'wb') as dest:
            shutil.copyfileobj(source,dest,1024*1024)
            dest.flush();os.fsync(dest.fileno())
    os.unlink(staged)


def upgrade_lock():
    """One upgrade at a time per host, whether an operator or the timer starts it.

    The timer job holds the lock while it runs this installer, and says so in
    the environment; a manual run meeting a held lock stops instead of
    interleaving with it."""
    if os.environ.get('LOGSENTINEL_UPGRADE_LOCK_HELD'):
        return None
    # INSTALL exists and is root's by now: bootstrap made it before any upgrade.
    fd=os.open(INSTALL/'upgrade.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise ValueError('Otra actualización de LogSentinel está en curso en este equipo. Espera a que termine.') from None
    return fd


def upgrade_client(args, desired, runtime):
    """Install a new runtime without enrolling again or resuming a stopped service."""
    lock=upgrade_lock()
    try:
        return upgrade_client_locked(args,desired,runtime)
    finally:
        if lock is not None:
            os.close(lock)


def upgrade_client_locked(args, desired, runtime):
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
    # A failed attempt leaves the unit stopped. The marker remembers that it was
    # running, so repeating the upgrade restores it instead of leaving a sender
    # silently down; a unit stopped on purpose has no marker and stays stopped.
    resume=INSTALL/('resume-'+args.name)
    was_active=subprocess.run(['systemctl','is-active','--quiet',unit.name]).returncode==0
    if was_active:
        resume.write_text('activo antes de actualizar\n')
    else:
        was_active=resume.is_file() and not resume.is_symlink()
    command('systemctl','stop',unit.name)
    from .portal.sender_safety import io_pressure
    pressure=io_pressure()
    if pressure is not None and pressure>=25:
        raise ValueError('El disco sigue bajo presión de E/S. Cliente detenido; repite la actualización cuando se estabilice (si estaba activo, se reanudará entonces).')
    # Budget the coherent backup and the additive index before touching the unit.
    size=sum(p.stat().st_size for p in spool.glob('sentinel.db*') if p.is_file())
    if shutil.disk_usage(INSTALL).free < size*2 + 256*1024**2:
        raise ValueError('Falta espacio para copia y actualización. El cliente queda detenido y conserva su cola.')
    if shutil.disk_usage(spool).free < size*2 + 256*1024**2:
        raise ValueError('Falta espacio en el volumen de la cola para la copia intermedia y el índice. El cliente queda detenido; no se elimina evidencia.')
    backup=INSTALL/('backup-'+args.name+'-'+str(time.time_ns()))
    backup.mkdir(mode=0o700)
    previous=unit.read_bytes()
    (backup/'service.before').write_bytes(previous)
    shutil.copyfile(config_path,backup/'config.before.json')
    (backup/'config.before.json').chmod(0o600)
    target=backup/'sentinel.db'
    staged=spool/('upgrade-backup-'+str(time.time_ns())+'.db')
    try:
        low_priority=['nice','-n','10']
        if shutil.which('ionice'):
            low_priority+=['ionice','-c','3']
        command('runuser','-u',desired['account'],'--',*low_priority,runtime/'bin/python','-m','logsentinel.client_setup','backup','--config',config_path,'--target',staged)
        adopt_backup(staged,target)
        command('runuser','-u',desired['account'],'--',*low_priority,runtime/'bin/python','-m','logsentinel.client_setup','migrate','--config',config_path)
        unit.write_text(unit_text(config_path,runtime,desired));unit.chmod(0o644)
        command('systemd-analyze','verify',unit,stdout=subprocess.DEVNULL)
        command('systemctl','daemon-reload')
        if was_active:
            command('systemctl','start',unit.name)
            command('systemctl','is-active','--quiet',unit.name)
        resume.unlink(missing_ok=True)
    except BaseException:
        # Do not replace a live queue with its backup: new durable events may exist.
        subprocess.run(['systemctl','stop',unit.name],capture_output=True)
        unit.write_bytes(previous)
        subprocess.run(['systemctl','daemon-reload'],capture_output=True)
        print('Actualización incompleta: cliente detenido; cola intacta. Directorio de respaldo (la copia puede estar incompleta):',backup,file=sys.stderr)
        if was_active:
            print('Estaba activo: se reanudará al repetir la actualización. Para que siga detenido, borra',resume,file=sys.stderr)
        raise
    finally:
        # A half-written intermediate copy is only ever removed, never trusted.
        if staged.is_file() and not staged.is_symlink():
            staged.unlink()
    print('Cliente actualizado. Runtime:',runtime)
    print('Copia coherente:',backup)
    print('Se conservan configuración, credenciales, CA, cursor y cola.')
    print('Servicio:', 'activo; obedecerá la pausa del central' if was_active else 'sigue detenido; no se ha reanudado')


# ---- Remote upgrades: root on this host decides, the central only offers ----
#
# Everything below runs as root with the system Python and nothing but the
# standard library, because it is started by a timer from the checkout it may
# replace. The sender process can only leave a request file in its spool; this
# job reads one validated commit hash from it and nothing else, verifies that
# commit against the repository root cloned when the feature was enabled, and
# then runs the ordinary installer, with its backups and its refusals.

SOURCE = INSTALL/'source'
REQUEST_FILE = 'upgrade-request.json'
COMMIT_RE = re.compile(r'^[0-9a-f]{40}$')
VERSION_RE = re.compile(r'^[A-Za-z0-9_.-]{1,80}$')
DEFER_BASE_SECONDS = 15*60
DEFER_MAX_SECONDS = 24*3600


def version_key(text):
    """Numeric leading parts of a version, for "is this older" comparisons."""
    parts=[]
    for part in str(text).split('.'):
        digits=re.match(r'\d+',part)
        if not digits:
            break
        parts.append(int(digits.group()))
    return tuple(parts)


def state_path(name):
    return INSTALL/('upgrade-'+name+'.json')


def read_state(name):
    try:
        value=json.loads(state_path(name).read_text())
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):
        return {}


def write_state(name, **fields):
    """Root's answer, readable by the sender, which reports it to the central."""
    managed_directory(INSTALL)
    value=dict(fields,observed=time.time())
    fd,temp=tempfile.mkstemp(prefix='.upgrade-',dir=INSTALL)
    with os.fdopen(fd,'w') as handle:
        json.dump(value,handle)
    os.chmod(temp,0o644)
    os.replace(temp,state_path(name))
    return value


def git(*args, cwd=None, timeout=120):
    # Never inherit GIT_DIR or GIT_WORK_TREE: a caller's repository (a hook, a
    # rebase) must not become the one these commands act on.
    env={k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_TERMINAL_PROMPT='0',LC_ALL='C')
    return subprocess.run(['git',*[str(a) for a in args]],cwd=str(cwd or SOURCE),capture_output=True,text=True,timeout=timeout,env=env,stdin=subprocess.DEVNULL)


def read_config(name):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,19}',name):
        raise ValueError('Nombre de instalación inválido.')
    config_path=CONFIG/(name+'.json')
    if config_path.is_symlink() or config_path.stat().st_uid!=0 or config_path.stat().st_mode & 0o022:
        raise ValueError('La configuración existente debe estar protegida por root.')
    return config_path,json.loads(config_path.read_text())


def rewrite_config(config_path, value):
    """Replace root's configuration in place, keeping its owner, group and mode."""
    info=config_path.stat()
    fd,temp=tempfile.mkstemp(prefix='.config-',dir=config_path.parent)
    with os.fdopen(fd,'w') as handle:
        os.fchown(handle.fileno(),info.st_uid,info.st_gid)
        os.fchmod(handle.fileno(),stat.S_IMODE(info.st_mode))
        json.dump(value,handle,indent=2)
    os.replace(temp,config_path)


def upgrade_unit_names(name):
    return 'logsentinel-client-upgrade-'+name+'.service','logsentinel-client-upgrade-'+name+'.timer'


def upgrade_unit_text(name, python):
    return f'''[Unit]
Description=LogSentinel remote upgrade check ({name})
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
ExecStart={python} -I {SOURCE}/logsentinel/client_setup.py remote-upgrade --name {name}
Nice=10
IOSchedulingClass=idle
'''


def upgrade_timer_text(name):
    return f'''[Unit]
Description=LogSentinel remote upgrade timer ({name})

[Timer]
OnBootSec=10min
OnUnitActiveSec=15min
RandomizedDelaySec=5min

[Install]
WantedBy=timers.target
'''


def enable_remote_upgrade(name, checkout):
    """Let this host act on the central's offers, from the repository of this checkout.

    The remote and branch recorded here are the only ones the job will ever
    fetch from: the central names a commit, never a place to get it from."""
    config_path,cfg=read_config(name)
    if not shutil.which('git'):
        raise ValueError('La actualización remota necesita git en este equipo.')
    checkout=Path(checkout).resolve()
    # The operator's checkout belongs to the operator, and git run by root
    # refuses a repository owned by someone else unless told to trust that one
    # path. Trust it, and only it, for the three reads made here.
    trust=('-c','safe.directory='+str(checkout))
    remote=git(*trust,'remote','get-url','origin',cwd=checkout)
    if remote.returncode or not remote.stdout.strip():
        raise ValueError('Esta copia del repositorio no tiene un remoto "origin"; clona desde el repositorio para poder actualizar desde él.')
    url=remote.stdout.strip()
    if any(ord(c)<33 for c in url):
        raise ValueError('La dirección del remoto contiene caracteres no permitidos.')
    head=git(*trust,'rev-parse','HEAD',cwd=checkout)
    if head.returncode or not COMMIT_RE.match(head.stdout.strip()):
        raise ValueError('No se pudo determinar el commit de esta copia.')
    managed_directory(INSTALL)
    if SOURCE.exists():
        existing=git('remote','get-url','origin')
        if existing.returncode or existing.stdout.strip()!=url:
            raise ValueError('Ya hay una copia para actualizaciones en '+str(SOURCE)+' con otro remoto ('+(existing.stdout.strip() or 'desconocido')+'). Bórrala para cambiar de repositorio.')
    else:
        # Objects come from the operator's checkout, so enabling needs no
        # network; the remote recorded is where later fetches go.
        clone=git(*trust,'clone','--quiet','--no-hardlinks',checkout,SOURCE,cwd=INSTALL,timeout=600)
        if clone.returncode:
            raise ValueError('No se pudo preparar la copia para actualizaciones: '+clone.stderr.strip()[-300:])
        set_url=git('remote','set-url','origin',url)
        if set_url.returncode:
            raise ValueError('No se pudo fijar el remoto de la copia para actualizaciones.')
    cfg.update(remote_upgrade=True,source_remote=url,source_branch=cfg.get('source_branch') or 'main')
    rewrite_config(config_path,cfg)
    # The sender reads its permission when it starts, and the upgrade before
    # this already restarted it: restart it again if it is running, and leave
    # a deliberately stopped one stopped.
    command('systemctl','try-restart','logsentinel-client-'+name+'.service')
    write_state(name,status='installed',commit=head.stdout.strip(),version=installed_version(checkout),message='')
    python=shutil.which('python3') or sys.executable
    service,timer=upgrade_unit_names(name)
    (UNITS/service).write_text(upgrade_unit_text(name,python));(UNITS/service).chmod(0o644)
    (UNITS/timer).write_text(upgrade_timer_text(name));(UNITS/timer).chmod(0o644)
    command('systemd-analyze','verify',UNITS/service,stdout=subprocess.DEVNULL)
    command('systemctl','daemon-reload')
    command('systemctl','enable','--now',timer)
    print('Actualización remota permitida en este equipo para "'+name+'": el central puede ofrecer un commit de',url,'(rama',cfg['source_branch']+'); este equipo lo verifica e instala con el temporizador',timer+'.')
    print('Para retirarlo: sudo ./setup-client.sh --upgrade --name',name,'--deny-remote-upgrade')


def quiet(*args):
    """A best-effort system command whose failure must not stop a teardown."""
    return subprocess.run([str(a) for a in args],capture_output=True)


def disable_remote_upgrade(name):
    config_path,cfg=read_config(name)
    service,timer=upgrade_unit_names(name)
    quiet('systemctl','disable','--now',timer)
    (UNITS/timer).unlink(missing_ok=True)
    (UNITS/service).unlink(missing_ok=True)
    quiet('systemctl','daemon-reload')
    cfg['remote_upgrade']=False
    rewrite_config(config_path,cfg)
    command('systemctl','try-restart','logsentinel-client-'+name+'.service')
    write_state(name,status='disabled',commit=read_state(name).get('commit',''),version=read_state(name).get('version',''),message='')
    print('Actualización remota retirada para "'+name+'": el central puede seguir ofreciendo, este equipo no la atiende.')


def installed_version(checkout):
    text=(Path(checkout)/'logsentinel'/'__init__.py').read_text()
    found=re.search(r'__version__\s*=\s*["\']([^"\']+)["\']',text)
    return found.group(1) if found and VERSION_RE.match(found.group(1)) else ''


def read_request(cfg):
    """The sender's request: a regular file it owns, small, with a commit and a version.

    Anything else is not an error to act on, only a reason to do nothing: the
    sender is the less trusted party and its file must not steer root."""
    spool=Path(cfg['spool'])
    try:
        fd=os.open(spool/REQUEST_FILE,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    except OSError:
        return 'unreadable'
    with os.fdopen(fd,'rb') as handle:
        info=os.fstat(handle.fileno())
        owner=pwd.getpwnam(cfg['account']).pw_uid
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=owner or info.st_size>4096:
            return 'unreadable'
        try:
            value=json.loads(handle.read(4096))
        except ValueError:
            return 'unreadable'
    if (not isinstance(value,dict) or not isinstance(value.get('commit'),str) or not COMMIT_RE.match(value['commit'])
            or not isinstance(value.get('version'),str) or not VERSION_RE.match(value['version'])):
        return 'unreadable'
    return dict(commit=value['commit'],version=value['version'])


def disk_pressure():
    try:
        for line in Path('/proc/pressure/io').read_text().splitlines():
            if line.startswith('full '):
                return float(dict(part.split('=') for part in line.split()[1:])['avg10'])
    except (OSError,ValueError,KeyError):
        pass
    return None


def run_installer(name):
    """The ordinary upgrade, from the verified checkout, under the lock this job holds."""
    env=dict(os.environ,LOGSENTINEL_UPGRADE_LOCK_HELD=str(os.getpid()))
    return subprocess.run([sys.executable,'-I',str(SOURCE/'logsentinel'/'client_setup.py'),'--upgrade','--name',name],
                          capture_output=True,text=True,timeout=3600,env=env,stdin=subprocess.DEVNULL)


def remote_upgrade(name):
    """One timer tick: act on the sender's request if, and only if, it checks out."""
    config_path,cfg=read_config(name)
    try:
        lock=upgrade_lock()
    except ValueError:
        return 'busy'
    try:
        return remote_upgrade_locked(name,cfg)
    finally:
        if lock is not None:
            os.close(lock)


def remote_upgrade_locked(name, cfg):
    if not cfg.get('remote_upgrade'):
        write_state(name,status='disabled',commit=read_state(name).get('commit',''),version=read_state(name).get('version',''),message='')
        return 'disabled'
    request=read_request(cfg)
    if request is None:
        return 'idle'
    last=read_state(name)
    if request=='unreadable':
        write_state(name,status='refused',commit='',version='',message='La petición del emisor no es legible o no es suya.')
        return 'refused'
    commit,version=request['commit'],request['version']
    same=last.get('commit')==commit
    if same and last.get('status') in ('installed','installing'):
        return 'done'
    if same and last.get('status')=='failed':
        # Not retried: the installer left a backup and a stopped service that an
        # operator must look at. A different target starts afresh.
        return 'failed'
    if same and last.get('status')=='deferred' and time.time()<float(last.get('next_after') or 0):
        return 'waiting'
    attempts=int(last.get('attempts') or 0) if same else 0

    def defer(message):
        wait=min(DEFER_MAX_SECONDS,DEFER_BASE_SECONDS*2**attempts)
        write_state(name,status='deferred',commit=commit,version=version,message=message,attempts=attempts+1,next_after=time.time()+wait)
        return 'deferred'

    def refuse(message):
        write_state(name,status='refused',commit=commit,version=version,message=message)
        return 'refused'

    installed=last.get('commit') if COMMIT_RE.match(str(last.get('commit') or '')) else ''
    installed_version_text=str(last.get('version') or '')
    if installed_version_text and version_key(version)<version_key(installed_version_text):
        return refuse('Retrocedería de la versión '+installed_version_text+' a la '+version+'.')
    pressure=disk_pressure()
    if pressure is not None and pressure>=25:
        return defer('Disco bajo presión de E/S.')
    branch=cfg.get('source_branch') or 'main'
    fetch=git('fetch','--quiet','origin',branch,timeout=600)
    if fetch.returncode:
        return defer('No se pudo consultar el repositorio: '+fetch.stderr.strip()[-200:])
    if git('cat-file','-e',commit+'^{commit}').returncode:
        return refuse('El commit ofrecido no está publicado en origin/'+branch+' (no se encuentra en el repositorio).')
    if git('merge-base','--is-ancestor',commit,'origin/'+branch).returncode:
        return refuse('El commit ofrecido no está publicado en origin/'+branch+'.')
    if installed and git('merge-base','--is-ancestor',installed,commit).returncode:
        return refuse('El commit ofrecido no desciende del instalado: sería un retroceso.')
    shown=git('show',commit+':logsentinel/__init__.py')
    found=re.search(r'__version__\s*=\s*["\']([^"\']+)["\']',shown.stdout if not shown.returncode else '')
    if not found or found.group(1)!=version:
        return refuse('La versión anunciada ('+version+') no es la del commit ofrecido.')
    checkout=git('checkout','--quiet','--detach',commit)
    if checkout.returncode:
        return defer('No se pudo preparar el commit: '+checkout.stderr.strip()[-200:])
    write_state(name,status='installing',commit=commit,version=version,message='')
    try:
        result=run_installer(name)
    except subprocess.TimeoutExpired:
        write_state(name,status='failed',commit=commit,version=version,message='La instalación no terminó en una hora; revisa el equipo.')
        return 'failed'
    if result.returncode==0:
        write_state(name,status='installed',commit=commit,version=version,message='')
        return 'installed'
    tail=' '.join((result.stderr or result.stdout or '').strip().splitlines()[-2:])[-300:]
    if 'Actualización incompleta' in (result.stderr or ''):
        # After the backup: the installer stopped the service on purpose and
        # restored the previous unit. Nothing automatic should touch it again.
        write_state(name,status='failed',commit=commit,version=version,message=tail)
        return 'failed'
    return defer(tail or 'La comprobación previa falló.')


def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0]=='remote-upgrade':
        parser=argparse.ArgumentParser()
        parser.add_argument('action');parser.add_argument('--name',required=True)
        args=parser.parse_args(argv)
        if os.geteuid()!=0:
            raise ValueError('La actualización remota la ejecuta root desde su temporizador.')
        outcome=remote_upgrade(args.name)
        print('remote-upgrade:',outcome)
        return 1 if outcome in ('failed','refused') else 0
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
    parser.add_argument('--ca-fingerprint',help='Huella SHA-256 del certificado del central, tal como la mostró al crear el alta')
    parser.add_argument('--plan',action='store_true',help='Mostrar el recorrido sin instalar ni enviar nada')
    policy=parser.add_mutually_exclusive_group()
    policy.add_argument('--allow-remote-upgrade',action='store_true',help='Permitir que este equipo instale el commit que ofrezca el central, verificado contra el remoto de esta copia (desactivado por defecto)')
    policy.add_argument('--deny-remote-upgrade',action='store_true',help='Retirar ese permiso y su temporizador')
    parser.add_argument('--prepared',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--source-checkout',help=argparse.SUPPRESS)
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
    if package and args.plan:
        print('Huella del certificado del central:',ca_fingerprint(package['ca_certificate']),'\nComprueba que coincide con la que mostró el central antes de instalar.')
    if args.plan:
        print('Plan: actualizar runtime con copia coherente; conservar identidad y estado del servicio. No se ha cambiado nada.' if args.upgrade else 'Plan: instalar Python aislado, conceder lectura, canjear el alta HTTPS y activar un servicio emisor. No se ha cambiado nada.')
        if args.allow_remote_upgrade:
            print('Además: permitir la actualización remota (copia del repositorio en '+str(SOURCE)+' y temporizador de root).')
        return
    if os.geteuid()!=0:
        raise ValueError('Ejecuta el mismo comando con sudo. El emisor funcionará después sin root.')
    os.umask(0o022)
    if not Path('/run/systemd/system').is_dir():
        raise ValueError('Este instalador necesita systemd ejecutándose como gestor del sistema.')
    if package:
        confirmed=confirm_ca(package,args.ca_fingerprint,interactive=sys.stdin.isatty() and not args.prepared)
        if not args.ca_fingerprint:
            argv+=['--ca-fingerprint',confirmed]
    if not args.prepared:
        repo=Path(__file__).resolve().parents[1]
        runtime=bootstrap(repo)
        os.execv(str(runtime/'bin/python'),[str(runtime/'bin/python'),'-m','logsentinel.client_setup',*argv,'--prepared','--source-checkout',str(repo)])
    runtime=Path(sys.prefix)
    if runtime.parent!=INSTALL or not (runtime/'ready').is_file():
        raise ValueError('Usa setup-client.sh desde el repositorio para preparar el instalador.')
    if args.upgrade:
        upgrade_client(args,desired,runtime)
    else:
        configure(args,desired,package,runtime)
    if args.allow_remote_upgrade:
        enable_remote_upgrade(args.name,args.source_checkout or Path(__file__).resolve().parents[1])
    elif args.deny_remote_upgrade:
        disable_remote_upgrade(args.name)


if __name__=='__main__':
    try:
        sys.exit(main() or 0)
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
