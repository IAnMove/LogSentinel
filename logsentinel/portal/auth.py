"""Session issuance and revocation share one credential generation and lock."""

import hashlib
import hmac
import secrets
import threading
import time


class SessionAuth:
    def __init__(self, store):
        self.store = store
        self.sessions = {}
        self.generations = {}
        self.lock = threading.RLock()

    @staticmethod
    def generation(credential):
        return hashlib.sha256(credential.encode()).digest()

    def prune(self):
        with self.lock:
            now = time.time()
            for session, expires in list(self.sessions.items()):
                if expires <= now:
                    self.logout(session)

    def login(self, credential):
        if not isinstance(credential, str):
            return None
        with self.lock:
            current = self.store.meta("admin_token")
            if not hmac.compare_digest(credential, current):
                return None
            session = secrets.token_urlsafe(32)
            self.sessions[session] = time.time() + 86400
            self.generations[session] = self.generation(current)
            return session

    def valid(self, session):
        with self.lock:
            if self.sessions.get(session, 0) <= time.time():
                self.logout(session)
                return False
            # Also reject credentials rotated by another Store/process.
            current = self.generation(self.store.meta("admin_token"))
            if self.generations.get(session) != current:
                self.logout(session)
                return False
            return True

    def logout(self, session):
        with self.lock:
            self.sessions.pop(session, None)
            self.generations.pop(session, None)

    def rotate(self):
        with self.lock:
            try:
                return self.store.rotate_admin_token()
            finally:
                self.sessions.clear()
                self.generations.clear()
