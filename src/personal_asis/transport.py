"""Loopback coordinator listener; public TLS termination is deployment-owned."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sqlite3

from .coordinator import Coordinator, ProtocolError, exact


MAX_BODY = 512 * 1024


def server(path, port=8765, nodes=("mac", "rog")):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass  # No request URLs, tokens or query payloads in logs.

        def send_json(self, value, status=200):
            raw = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(raw)
            self.close_connection = True

        def do_GET(self):
            self.send_json({"error": "not_found"}, 404)

        def do_POST(self):
            self.connection.settimeout(15)
            try:
                if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
                    raise ProtocolError("invalid_body")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    raise ProtocolError("invalid_body_size", 413)
                if self.headers.get_content_type() != "application/json":
                    raise ProtocolError("json_required", 415)
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ProtocolError("invalid_body")
                data = json.loads(raw)
                with Coordinator(path, nodes) as c:
                    if self.path == "/v1/enroll":
                        exact(data, ("node_id", "pairing_code", "credential"))
                        result = c.enroll(data["node_id"], data["pairing_code"], data["credential"])
                    elif self.path == "/v1/session":
                        exact(data, ("node_id", "credential"))
                        result = c.session(data["node_id"], data["credential"])
                    else:
                        authorization = self.headers.get("Authorization", "")
                        if not authorization.startswith("Bearer "):
                            raise ProtocolError("unauthorized", 401)
                        node = c.authenticate(authorization[7:])
                        if self.path == "/v1/poll":
                            exact(data, ("policy_hash",))
                            result = c.poll(node, data["policy_hash"])
                        elif self.path == "/v1/complete":
                            exact(data, ("task_id", "lease", "result"))
                            result = c.complete(node, data["task_id"], data["lease"], data["result"])
                        else:
                            raise ProtocolError("not_found", 404)
                self.send_json(result)
            except ProtocolError as exc:
                self.send_json({"error": str(exc)}, exc.status)
            except (ValueError, TypeError, UnicodeError, RecursionError):
                self.send_json({"error": "invalid_request"}, 400)
            except (OSError, sqlite3.Error):
                self.send_json({"error": "temporarily_unavailable"}, 503)

    result = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    result.daemon_threads = True
    return result
