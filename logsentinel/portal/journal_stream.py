"""Read bounded subprocess output without staging the journal on disk."""

import os
import selectors
import subprocess
import time


class JournalReadError(OSError):
    def __init__(self, code, returncode=None):
        self.code, self.returncode = code, returncode
        super().__init__(code)


def read_journal(command, limit, timeout=3):
    output = bytearray()
    error = bytearray()
    limited = False
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with selectors.DefaultSelector() as selector:
            for stream in (proc.stdout, proc.stderr):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
            deadline = time.monotonic() + timeout
            while selector.get_map() and time.monotonic() < deadline:
                for key, _ in selector.select(
                    max(0, min(0.1, deadline - time.monotonic()))
                ):
                    is_output = key.fileobj is proc.stdout
                    size = min(65536, limit - len(output)) if is_output else 8192
                    chunk = os.read(key.fd, size)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    if is_output:
                        output.extend(chunk)
                    elif len(error) < 8192:
                        error.extend(chunk[: 8192 - len(error)])
                if len(output) >= limit:
                    limited = True
                    break
            timed_out = bool(selector.get_map()) and not limited
        if proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        if proc.returncode not in (0, -15):
            message = bytes(error).lower()
            code = "journal_read_failed"
            if (
                b"permission denied" in message
                or b"insufficient permissions" in message
            ):
                code = "permission_denied"
            elif b"cursor" in message and (b"seek" in message or b"failed" in message):
                code = "journal_retention_gap"
            raise JournalReadError(code, proc.returncode)
        if timed_out and not output:
            raise TimeoutError("journalctl read timed out")
        return bytes(output), limited
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        proc.stdout.close()
        proc.stderr.close()
