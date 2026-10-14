"""Private state-first web console. TLS is terminated by the owning VPS proxy."""

from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit

from .coordinator import Coordinator, ProtocolError, exact
from .web_auth import WebAuth
from .evidence import control as evidence_control


COOKIE = "__Host-asis"
ASSETS = {"/": ("index.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/app.css": ("app.css", "text/css; charset=utf-8"),
          "/sw.js": ("sw.js", "text/javascript; charset=utf-8"),
          "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
          "/icon.svg": ("icon.svg", "image/svg+xml")}


def settings(home):
    data = json.loads((Path(home) / "pwa.json").read_text())
    origin = data.get("origin")
    if not isinstance(origin, str):
        raise ValueError("PWA 需要显式配置 HTTPS origin")
    url = urlsplit(origin)
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.path or url.query or url.fragment or data.get("auth_method") not in {"password", "password_totp"}):
        raise ValueError("PWA 需要无路径的 HTTPS origin 和明确的登录配置")
    return data


def server(home, port=8766, origin=None, auth_method=None):
    home = Path(home)
    if origin is None:
        config = settings(home)
        origin, auth_method = config["origin"], config["auth_method"]
    if auth_method not in {"password", "password_totp"}:
        raise ValueError("需要明确配置 PWA 登录方式")
    host = urlsplit(origin).netloc
    asset_root = Path(__file__).with_name("web")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_): pass

        def write(self, value, status=200, content_type="application/json; charset=utf-8", cookie=None):
            raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(raw)
            self.close_connection = True

        def validate(self, post=False):
            self.connection.settimeout(15)
            if self.headers.get("Host") != host or self.headers.get("X-Forwarded-Proto") != "https":
                raise ProtocolError("https_origin_required", 403)
            if post and self.headers.get("Origin") != origin:
                raise ProtocolError("origin_rejected", 403)
            if urlsplit(self.path).query:
                raise ProtocolError("query_string_not_supported")

        def token(self):
            cookies = SimpleCookie()
            try:
                cookies.load(self.headers.get("Cookie", ""))
            except Exception:
                return ""
            return cookies[COOKIE].value if COOKIE in cookies else ""

        def client(self):
            value = self.headers.get("X-Real-IP", self.client_address[0])
            return hashlib.sha256(value.encode()).hexdigest()

        def body(self):
            if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
                raise ProtocolError("invalid_body")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 16 * 1024:
                raise ProtocolError("invalid_body_size", 413)
            if self.headers.get_content_type() != "application/json":
                raise ProtocolError("json_required", 415)
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ProtocolError("invalid_body")
            return json.loads(raw)

        def do_GET(self):
            try:
                self.validate()
                route = urlsplit(self.path).path
                if route in ASSETS:
                    filename, mime = ASSETS[route]
                    return self.write((asset_root / filename).read_bytes(), content_type=mime)
                with WebAuth(home, otp_required=auth_method == "password_totp") as auth:
                    if route == "/auth/status":
                        try:
                            status = auth.session(self.token())
                        except ProtocolError:
                            status = {"authenticated": False}
                        return self.write({"initialized": auth.initialized(), "auth_method": auth_method, **status})
                    auth.session(self.token())
                with Coordinator(home / "coordinator.sqlite3", nodes=("mac",)) as c:
                    if route == "/api/state":
                        nodes = [{"node_id": r["id"], "online": r["last_seen"] is not None and c.clock() - r["last_seen"] < c.offline_after}
                                 for r in c.db.execute("SELECT * FROM nodes WHERE enabled=1 ORDER BY id")]
                        tasks = [{"task_id": r["id"], "query": r["query"], "channel": r["channel"], "created": r["created"],
                                  "state": c.view(r["id"])["state"]}
                                 for r in c.db.execute("SELECT * FROM tasks ORDER BY created DESC LIMIT 30").fetchall()]
                        return self.write({"nodes": nodes, "tasks": tasks, "metadata_only": True})
                    if route.startswith("/api/tasks/"):
                        task_id = route.removeprefix("/api/tasks/")
                        return self.write(c.view(task_id))
                    if route == "/api/audit":
                        return self.write(c.audit())
                raise ProtocolError("not_found", 404)
            except ProtocolError as exc:
                self.write({"error": str(exc)}, exc.status)
            except (ValueError, TypeError, UnicodeError, RecursionError):
                self.write({"error": "invalid_request"}, 400)
            except (OSError, sqlite3.Error):
                self.write({"error": "temporarily_unavailable"}, 503)

        def do_POST(self):
            try:
                self.validate(post=True)
                route = urlsplit(self.path).path
                data = self.body()
                token = self.token()
                with WebAuth(home, otp_required=auth_method == "password_totp") as auth:
                    if route == "/auth/setup/start":
                        exact(data, ("setup_token",))
                        return self.write(auth.setup_start(data["setup_token"], self.client()))
                    if route == "/auth/setup/finish":
                        exact(data, ("setup_token", "password", "code"))
                        result = auth.setup_finish(data["setup_token"], data["password"], data["code"], self.client())
                    elif route == "/auth/login":
                        exact(data, ("password", "code"))
                        result = auth.login(data["password"], data["code"], self.client())
                    else:
                        csrf = self.headers.get("X-CSRF-Token", "")
                        auth.session(token, csrf)
                        if route == "/auth/logout":
                            exact(data, ())
                            auth.logout(token)
                            return self.write({"logged_out": True}, cookie=f"{COOKIE}=; Secure; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
                        if route == "/api/search":
                            exact(data, ("query", "request_id"))
                            with Coordinator(home / "coordinator.sqlite3", nodes=("mac",)) as c:
                                return self.write(c.submit(data["query"], "pwa", 20, data["request_id"]))
                        if route == "/api/reader/request":
                            exact(data, ("task_id", "document_id", "content_hash", "mode", "cursor", "client_nonce", "public_key"))
                            with Coordinator(home / "coordinator.sqlite3", nodes=("mac",)) as c:
                                view = c.view(data["task_id"])
                                hit = next((h for group in view["results"] for h in group["replicas"]
                                    if h["document_id"] == data["document_id"] and h["content_hash"] == data["content_hash"]), None)
                                if not hit or not hit.get("reader_allowed"):
                                    raise ProtocolError("reader_denied", 403)
                                query = c.db.execute("SELECT query FROM tasks WHERE id=?", (data["task_id"],)).fetchone()[0]
                            return self.write(evidence_control(home, {"op": "request", "node_id": hit["node_id"],
                                "query": query, **{k:v for k,v in data.items() if k != "task_id"}}))
                        if route == "/api/reader/result":
                            exact(data, ("request_id",))
                            return self.write(evidence_control(home, {"op": "get", "request_id": data["request_id"]}))
                        raise ProtocolError("not_found", 404)
                    secret = result.pop("token")
                    self.write(result, cookie=f"{COOKIE}={secret}; Secure; HttpOnly; SameSite=Strict; Path=/; Max-Age={result['expires_in']}")
            except ProtocolError as exc:
                self.write({"error": str(exc)}, exc.status)
            except (ValueError, TypeError, UnicodeError, RecursionError):
                self.write({"error": "invalid_request"}, 400)
            except (OSError, sqlite3.Error):
                self.write({"error": "temporarily_unavailable"}, 503)

    http = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    http.daemon_threads = True
    return http
