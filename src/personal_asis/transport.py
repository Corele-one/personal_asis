"""Loopback coordinator listener; public TLS termination is deployment-owned."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3

from .coordinator import Coordinator, ProtocolError, exact
from .evidence import Relay, control_server
from .analysis_channel import AnalysisRelay


MAX_BODY = 512 * 1024


def server(path, port=8765, nodes=("mac",)):
    relay = Relay()
    analysis = AnalysisRelay()
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
                            previous = c.db.execute("SELECT policy_hash FROM nodes WHERE id=?", (node,)).fetchone()[0]
                            result = c.poll(node, data["policy_hash"])
                            if previous != data["policy_hash"]:
                                relay.invalidate(node)
                        elif self.path == "/v1/complete":
                            exact(data, ("task_id", "lease", "result"))
                            result = c.complete(node, data["task_id"], data["lease"], data["result"])
                        elif self.path == "/v1/evidence/poll":
                            exact(data, ())
                            result = relay.poll(node)
                        elif self.path == "/v1/evidence/complete":
                            result = relay.complete(node, data)
                        elif self.path == "/v1/analysis/poll":
                            exact(data, ('policy_hash',))
                            if not isinstance(data['policy_hash'],str) or len(data['policy_hash'])!=64:
                                raise ProtocolError('invalid_policy_hash')
                            result = analysis.poll(node,data['policy_hash'])
                        elif self.path == "/v1/analysis/complete":
                            result = analysis.complete(node,data)
                        else:
                            raise ProtocolError("not_found", 404)
                self.send_json(result)
            except ProtocolError as exc:
                self.send_json({"error": str(exc)}, exc.status)
            except (ValueError, TypeError, UnicodeError, RecursionError):
                self.send_json({"error": "invalid_request"}, 400)
            except (OSError, sqlite3.Error):
                self.send_json({"error": "temporarily_unavailable"}, 503)

    class Server(ThreadingHTTPServer):
        control = None
        analysis_control = None
        def server_close(self):
            if self.analysis_control is not None:
                control, path = self.analysis_control
                self.analysis_control = None
                control.shutdown()
                control.server_close()
                path.unlink(missing_ok=True)
            if self.control is not None:
                control, path = self.control
                self.control = None
                control.shutdown()
                control.server_close()
                path.unlink(missing_ok=True)
            super().server_close()
    result = Server(("127.0.0.1", port), Handler)
    try:
        result.control = control_server(Path(path).parent, relay)
        result.analysis_control = control_server(Path(path).parent, analysis, 'analysis.sock')
    except Exception:
        result.server_close()
        raise
    result.daemon_threads = True
    result.relay = relay
    result.analysis = analysis
    return result
