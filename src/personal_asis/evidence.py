"""Ephemeral encrypted reader relay. No plaintext, key or payload enters SQLite."""

import base64
import json
import os
from pathlib import Path
import secrets
import socket
import socketserver
import threading
import time
import uuid

from .coordinator import ProtocolError, exact, identifier


def context(job):
    return "\n".join(str(job[k]) for k in ("document_id", "content_hash", "mode", "cursor", "client_nonce")).encode()


def encrypt(value, job):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    public = serialization.load_der_public_key(base64.b64decode(job["public_key"], validate=True))
    if not isinstance(public, rsa.RSAPublicKey) or public.key_size != 2048:
        raise ValueError("invalid_reader_key")
    key, nonce = AESGCM.generate_key(bit_length=256), secrets.token_bytes(12)
    ciphertext = AESGCM(key).encrypt(nonce, json.dumps(value, ensure_ascii=False).encode(), context(job))
    wrapped = public.encrypt(key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    encode = lambda raw: base64.b64encode(raw).decode()
    return {"wrapped_key": encode(wrapped), "nonce": encode(nonce), "ciphertext": encode(ciphertext)}


class Relay:
    def __init__(self, clock=time.monotonic, ttl=90):
        self.clock, self.ttl = clock, ttl
        self.jobs, self.lock = {}, threading.Lock()

    def _prune(self):
        for key in [key for key, value in self.jobs.items() if self.clock() >= value["expires"]]:
            del self.jobs[key]

    def request(self, data):
        exact(data, ("node_id", "document_id", "content_hash", "mode", "cursor", "client_nonce", "public_key", "query"))
        identifier(data["node_id"])
        try:
            if str(uuid.UUID(data["document_id"])) != data["document_id"]:
                raise ValueError()
            if len(bytes.fromhex(data["content_hash"])) != 32:
                raise ValueError()
            public = base64.b64decode(data["public_key"], validate=True)
            nonce = base64.b64decode(data["client_nonce"], validate=True)
            if not 200 <= len(public) <= 600 or len(nonce) != 16:
                raise ValueError()
        except (ValueError, TypeError):
            raise ProtocolError("invalid_reader_request") from None
        if data["mode"] not in {"excerpt", "text"} or type(data["cursor"]) is not int or not 0 <= data["cursor"] <= 4_000_000:
            raise ProtocolError("invalid_reader_request")
        if not isinstance(data["query"], str) or len(data["query"]) > 512:
            raise ProtocolError("invalid_reader_request")
        with self.lock:
            self._prune()
            if len(self.jobs) >= 32:
                raise ProtocolError("reader_busy", 429)
            key = str(uuid.uuid4())
            self.jobs[key] = {**data, "request_id": key, "expires": self.clock() + self.ttl,
                              "lease": None, "lease_until": 0, "status": "waiting", "envelope": None}
            return {"request_id": key, "status": "waiting", "expires_in": self.ttl}

    def poll(self, node):
        with self.lock:
            self._prune()
            for value in self.jobs.values():
                if value["node_id"] == node and value["status"] == "waiting" and self.clock() >= value["lease_until"]:
                    value["lease"], value["lease_until"] = secrets.token_urlsafe(24), self.clock() + 45
                    return {"job": {k: value[k] for k in ("request_id", "document_id", "content_hash", "mode", "cursor",
                                                         "client_nonce", "public_key", "query", "lease")}}
            return {"job": None}

    def complete(self, node, data):
        exact(data, ("request_id", "lease", "status", "envelope"))
        if data["status"] not in {"ready", "denied", "stale", "missing", "failed"}:
            raise ProtocolError("invalid_reader_result")
        envelope = data["envelope"]
        if data["status"] == "ready":
            exact(envelope, ("wrapped_key", "nonce", "ciphertext"))
            try:
                sizes = [len(base64.b64decode(envelope[k], validate=True)) for k in ("wrapped_key", "nonce", "ciphertext")]
                if sizes[0] != 256 or sizes[1] != 12 or not 16 <= sizes[2] <= 80_000:
                    raise ValueError()
            except (TypeError, ValueError):
                raise ProtocolError("invalid_reader_ciphertext") from None
        elif envelope is not None:
            raise ProtocolError("invalid_reader_result")
        with self.lock:
            self._prune()
            value = self.jobs.get(data["request_id"])
            if (not value or value["node_id"] != node or value["lease"] != data["lease"]
                    or self.clock() >= value["lease_until"] or value["status"] != "waiting"):
                raise ProtocolError("reader_lease_expired", 409)
            value["status"], value["envelope"] = data["status"], envelope
            return {"accepted": True}

    def get(self, request_id):
        with self.lock:
            self._prune()
            value = self.jobs.get(request_id)
            if value is None:
                raise ProtocolError("reader_expired", 404)
            return {"request_id": request_id, "status": value["status"], "envelope": value["envelope"]}

    def invalidate(self, node):
        with self.lock:
            for key in [key for key, value in self.jobs.items() if value["node_id"] == node]:
                del self.jobs[key]


def control_server(home, relay):
    path = Path(home) / "evidence.sock"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("evidence_socket_path_in_use")
    if path.exists():
        if not path.is_socket():
            raise ValueError("evidence_socket_path_in_use")
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.connect(str(path))
        except (ConnectionRefusedError, FileNotFoundError):
            path.unlink(missing_ok=True)
        else:
            raise ValueError("evidence_relay_already_running")
        finally:
            probe.close()
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.connection.settimeout(10)
            try:
                raw = self.rfile.readline(16_385)
                if len(raw) > 16_384:
                    raise ProtocolError("invalid_reader_request")
                data = json.loads(raw)
                op = data.pop("op")
                if op == "request":
                    result = relay.request(data)
                elif op == "get":
                    exact(data, ("request_id",))
                    result = relay.get(data["request_id"])
                else:
                    raise ProtocolError("invalid_reader_request")
            except (ProtocolError, ValueError, TypeError, KeyError, OSError) as exc:
                result = {"error": str(exc) if isinstance(exc, ProtocolError) else "reader_unavailable"}
            self.wfile.write(json.dumps(result).encode() + b"\n")
    class Server(socketserver.ThreadingUnixStreamServer):
        def service_actions(self):
            # Expired ciphertext must leave RAM even if all nodes go offline.
            with relay.lock:
                relay._prune()
    server = Server(str(path), Handler)
    server.daemon_threads = True
    os.chmod(path, 0o600)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, path


def control(home, data):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(10)
        connection.connect(str(Path(home) / "evidence.sock"))
        connection.sendall(json.dumps(data).encode() + b"\n")
        with connection.makefile("rb") as source:
            result = json.loads(source.readline(120_000))
    if "error" in result:
        raise ProtocolError(result["error"], 404 if result["error"] == "reader_expired" else 503)
    return result
