"""Check configured paths and the actual descriptors used to collect local logs."""

import os
from pathlib import Path
import stat


class UnsafeSourcePath(ValueError):
    pass


SENSITIVE_NAMES = {"id_rsa", "id_ed25519", "id_ecdsa", "id_dsa", "shadow", "gshadow", "sudoers"}


def validate_source_path(path, directory):
    original = Path(path).expanduser()
    resolved = original.resolve()
    for candidate in (original, resolved):
        name = candidate.name
        while Path(name).suffix in (".gz", ".xz", ".bz2", ".zip", ".tar", ".zst"):
            name = Path(name).stem
        if name in SENSITIVE_NAMES or candidate == Path("/etc/passwd") or candidate.is_relative_to("/etc/sudoers.d"):
            raise UnsafeSourcePath("Refusing to ingest this path as a log source")
    if resolved.is_relative_to(Path(directory).resolve()):
        raise UnsafeSourcePath("The application data directory cannot be a log source")
    return resolved


def validate_source_handle(handle, directory):
    if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
        raise UnsafeSourcePath("A file log source must be a regular file")
    # Linux exposes the opened target, including after a symlink swap or rotation.
    target = os.readlink(f"/proc/self/fd/{handle.fileno()}")
    validate_source_path(target.removesuffix(" (deleted)"), directory)


def open_source(path, directory):
    validate_source_path(path, directory)
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
    handle = os.fdopen(fd, "rb")
    try:
        validate_source_handle(handle, directory)
    except BaseException:
        handle.close()
        raise
    return handle
