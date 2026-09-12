from concurrent.futures import ThreadPoolExecutor
import threading

from logsentinel.portal.auth import SessionAuth
from logsentinel.portal.store import Store


def test_login_overlapping_rotation_cannot_issue_a_session_for_old_key(tmp_path):
    store = Store(tmp_path)
    auth = SessionAuth(store)
    old = store.meta("admin_token")
    old_session = auth.login(old)
    replacing = threading.Event()
    release = threading.Event()
    write = store._replace_key_file

    def blocked_write(token):
        replacing.set()
        assert release.wait(5)
        return write(token)

    store._replace_key_file = blocked_write
    with ThreadPoolExecutor(max_workers=2) as pool:
        rotation = pool.submit(auth.rotate)
        assert replacing.wait(5)
        login = pool.submit(auth.login, old)
        release.set()
        new = rotation.result(timeout=5)
        assert login.result(timeout=5) is None
    assert not auth.valid(old_session)
    assert auth.valid(auth.login(new))


def test_external_rotation_revokes_existing_sessions(tmp_path):
    store = Store(tmp_path)
    auth = SessionAuth(store)
    session = auth.login(store.meta("admin_token"))
    assert auth.valid(session)
    Store(tmp_path).rotate_admin_token()
    assert not auth.valid(session)
    assert not auth.sessions and not auth.generations
