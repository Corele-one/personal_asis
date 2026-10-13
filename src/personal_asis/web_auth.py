"""Single-owner web authentication; no local-node credentials are reused."""

import base64
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import sqlite3
import struct
import time

from .coordinator import ProtocolError, fingerprint


def otp(secret, step, digits=6):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    mac = hmac.digest(key, struct.pack(">Q", step), "sha1")
    offset = mac[-1] & 15
    value = int.from_bytes(mac[offset:offset + 4], "big") & 0x7fffffff
    return str(value % 10 ** digits).zfill(digits)


def matching_step(secret, code, at, last=-1):
    if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
        return None
    current = int(at // 30)
    for step in (current, current - 1, current + 1):
        if step > last and hmac.compare_digest(code, otp(secret, step)):
            return step
    return None


def password_hash(password, salt):
    if not isinstance(password, str) or not 14 <= len(password) <= 256:
        raise ProtocolError("password_length_14_to_256")
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=32768, r=8, p=1,
                          maxmem=64 * 1024 * 1024).hex()


class WebAuth:
    def __init__(self, home, clock=time.time, otp_required=True):
        self.clock = clock
        self.otp_required = otp_required
        path = Path(home) / "web-auth.sqlite3"
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        os.chmod(path, 0o600)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS owner (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                salt TEXT, password_hash TEXT, otp_secret TEXT, last_step INTEGER NOT NULL DEFAULT -1
            );
            INSERT OR IGNORE INTO owner(singleton) VALUES(1);
            CREATE TABLE IF NOT EXISTS bootstrap (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                token_hash TEXT NOT NULL, expires REAL NOT NULL, pending_secret TEXT
            );
            CREATE TABLE IF NOT EXISTS web_sessions (
                token_hash TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires REAL NOT NULL, seen REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS failures (
                id INTEGER PRIMARY KEY, client TEXT NOT NULL, at REAL NOT NULL
            );
        """)
        self.db.execute("DELETE FROM failures WHERE at<?", (self.clock() - 900,))
        self.db.execute("DELETE FROM web_sessions WHERE expires<=? OR seen<=?",
                        (self.clock(), self.clock() - 1800))

    def __enter__(self): return self
    def __exit__(self, *_): self.db.close()

    def initialized(self):
        return bool(self.db.execute("SELECT password_hash FROM owner WHERE singleton=1").fetchone()[0])

    def bootstrap(self, reset=False):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if self.initialized() and not reset:
                raise ProtocolError("owner_already_configured", 409)
            token = secrets.token_urlsafe(32)
            if reset:
                self.db.execute("UPDATE owner SET salt=NULL,password_hash=NULL,otp_secret=NULL,last_step=-1")
                self.db.execute("DELETE FROM web_sessions")
            self.db.execute("INSERT OR REPLACE INTO bootstrap VALUES(1,?,?,NULL)",
                            (fingerprint(token), self.clock() + 3600))
            self.db.execute("COMMIT")
            return {"setup_token": token, "expires_in": 3600}
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def _bootstrap(self, token):
        row = self.db.execute("SELECT * FROM bootstrap WHERE singleton=1").fetchone()
        if (self.initialized() or not isinstance(token, str) or len(token) > 128 or row is None
                or row["expires"] <= self.clock() or not hmac.compare_digest(row["token_hash"], fingerprint(token))):
            raise ProtocolError("invalid_setup_token", 401)
        return row

    def _rate(self, client):
        attempts = self.db.execute("SELECT count(*) FROM failures WHERE client=? AND at>?",
                                   (client, self.clock() - 900)).fetchone()[0]
        total = self.db.execute("SELECT count(*) FROM failures WHERE at>?", (self.clock() - 60,)).fetchone()[0]
        if attempts >= 5 or total >= 30:
            raise ProtocolError("login_rate_limited", 429)

    def _failure(self, client):
        self.db.execute("INSERT INTO failures(client,at) VALUES(?,?)", (client, self.clock()))

    def setup_start(self, token, client):
        self._rate(client)
        try:
            row = self._bootstrap(token)
        except ProtocolError:
            self._failure(client)
            raise
        if not self.otp_required:
            return {"otp_required": False}
        secret = row["pending_secret"] or base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
        self.db.execute("UPDATE bootstrap SET pending_secret=? WHERE singleton=1 AND token_hash=?",
                        (secret, fingerprint(token)))
        return {"otp_required": True, "secret": secret, "otpauth_uri": f"otpauth://totp/PersonalAsis:owner?secret={secret}&issuer=PersonalAsis&digits=6&period=30"}

    def _session(self):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.db.execute("INSERT INTO web_sessions VALUES(?,?,?,?)",
                        (fingerprint(token), csrf, self.clock() + 12 * 3600, self.clock()))
        return {"token": token, "csrf": csrf, "expires_in": 12 * 3600}

    def setup_finish(self, token, password, code, client):
        self._rate(client)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self._bootstrap(token)
            step = ((matching_step(row["pending_secret"], code, self.clock()) if row["pending_secret"] else None)
                    if self.otp_required else -1)
            if step is None:
                raise ProtocolError("invalid_credentials", 401)
            salt = secrets.token_bytes(32).hex()
            hashed = password_hash(password, salt)
            self.db.execute("UPDATE owner SET salt=?,password_hash=?,otp_secret=?,last_step=? WHERE singleton=1",
                            (salt, hashed, row["pending_secret"], step))
            self.db.execute("DELETE FROM bootstrap")
            result = self._session()
            self.db.execute("COMMIT")
            return result
        except BaseException:
            self.db.execute("ROLLBACK")
            self._failure(client)
            raise

    def login(self, password, code, client):
        self._rate(client)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT * FROM owner WHERE singleton=1").fetchone()
            if not row["password_hash"]:
                raise ProtocolError("owner_not_configured", 401)
            try:
                hashed = password_hash(password, row["salt"])
            except ProtocolError:
                hashed = ""
            step = matching_step(row["otp_secret"], code, self.clock(), row["last_step"]) if self.otp_required else -1
            if not hmac.compare_digest(hashed, row["password_hash"]) or step is None:
                raise ProtocolError("invalid_credentials", 401)
            self.db.execute("UPDATE owner SET last_step=? WHERE singleton=1", (step,))
            self.db.execute("DELETE FROM failures WHERE client=?", (client,))
            result = self._session()
            self.db.execute("COMMIT")
            return result
        except BaseException:
            self.db.execute("ROLLBACK")
            self._failure(client)
            raise

    def session(self, token, csrf=None):
        if not isinstance(token, str) or len(token) > 128:
            raise ProtocolError("unauthorized", 401)
        row = self.db.execute("SELECT * FROM web_sessions WHERE token_hash=? AND expires>? AND seen>?",
                              (fingerprint(token), self.clock(), self.clock() - 1800)).fetchone()
        if not row:
            raise ProtocolError("unauthorized", 401)
        if csrf is not None and (not isinstance(csrf, str) or not hmac.compare_digest(csrf, row["csrf"])):
            raise ProtocolError("csrf_rejected", 403)
        self.db.execute("UPDATE web_sessions SET seen=? WHERE token_hash=?", (self.clock(), fingerprint(token)))
        return {"csrf": row["csrf"], "authenticated": True}

    def logout(self, token):
        self.db.execute("DELETE FROM web_sessions WHERE token_hash=?", (fingerprint(token),))
