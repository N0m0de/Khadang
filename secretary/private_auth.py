"""Single-owner authentication for the private dashboard."""
import hashlib
import hmac
import secrets
import time


def password_hash(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=1,
                            maxmem=64 * 1024 * 1024, dklen=32)
    return f'scrypt${salt.hex()}${digest.hex()}'


def password_matches(password, encoded):
    try:
        scheme, salt, expected = encoded.split('$')
        if scheme != 'scrypt':
            return False
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=32768,
                                r=8, p=1, maxmem=64 * 1024 * 1024, dklen=32)
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


class OwnerAuth:
    COOKIE = 'secretory_session'
    ABSOLUTE_TTL = 8 * 3600
    IDLE_TTL = 30 * 60

    def __init__(self, encoded_password=None, required=False):
        self.encoded_password = encoded_password
        self.enabled = required or bool(encoded_password)
        self.sessions = {}
        self.failures = []

    def login(self, password):
        now = time.time()
        self.failures = [at for at in self.failures if at > now - 900]
        if len(self.failures) >= 5:
            return None, 'Too many failed attempts. Wait 15 minutes before trying again.'
        if not self.encoded_password or not password_matches(password, self.encoded_password):
            self.failures.append(now)
            return None, 'Incorrect password.'
        self.failures = []
        self.prune(now)
        token = secrets.token_urlsafe(48)
        # Only a digest is stored. A new login revokes every previous session.
        self.sessions = {self.digest(token): (now, now)}
        return token, None

    @staticmethod
    def digest(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def prune(self, now):
        self.sessions = {k: (born, seen) for k, (born, seen) in self.sessions.items()
                         if now - born < self.ABSOLUTE_TTL and now - seen < self.IDLE_TTL}

    def valid(self, token, touch=True):
        if not self.enabled:
            return True
        if not token:
            return False
        now = time.time()
        self.prune(now)
        key = self.digest(token)
        session = self.sessions.get(key)
        if not session:
            return False
        if touch:
            self.sessions[key] = (session[0], now)
        return True

    def logout(self, token):
        if token:
            self.sessions.pop(self.digest(token), None)
