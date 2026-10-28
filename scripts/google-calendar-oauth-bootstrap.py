#!/usr/bin/env python3
"""Create a Google Calendar read-only token for the private AstrBot MCP install.

This helper runs on the VPS. It binds only to loopback, uses PKCE, requests only
calendar.readonly, never prints OAuth codes/tokens, and refuses to overwrite an
existing token file.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path


PRIVATE_DIR = Path("/home/mac/astrbot/data/google-calendar-mcp")
CLIENT_FILE = PRIVATE_DIR / "gcp-oauth.keys.json"
TOKEN_FILE = PRIVATE_DIR / "tokens.json"
HOST = "127.0.0.1"
PORT = 8085
CALLBACK_PATH = "/oauth2callback"
SCOPE = "https://www.googleapis.com/auth/calendar.readonly"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def load_client() -> tuple[str, str]:
    try:
        data = json.loads(CLIENT_FILE.read_text(encoding="utf-8"))
        installed = data["installed"]
        client_id = installed["client_id"]
        client_secret = installed["client_secret"]
        auth_uri = installed.get("auth_uri", "https://accounts.google.com/o/oauth2/auth")
        token_uri = installed.get("token_uri", "https://oauth2.googleapis.com/token")
    except (OSError, ValueError, KeyError, TypeError):
        raise RuntimeError("OAuth client JSON is missing or not a Desktop app file") from None
    if not client_id or not client_secret:
        raise RuntimeError("OAuth client JSON is incomplete")
    if auth_uri != "https://accounts.google.com/o/oauth2/auth":
        raise RuntimeError("Unexpected OAuth authorization endpoint")
    if token_uri != "https://oauth2.googleapis.com/token":
        raise RuntimeError("Unexpected OAuth token endpoint")
    return client_id, client_secret


def write_token(token: dict[str, object]) -> None:
    if TOKEN_FILE.exists():
        raise RuntimeError("tokens.json already exists; refusing to overwrite it")
    fd, temp_name = tempfile.mkstemp(prefix=".tokens.", dir=PRIVATE_DIR)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"normal": token}, stream, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp_name, TOKEN_FILE)
        os.chmod(TOKEN_FILE, 0o600)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def main() -> int:
    if not CLIENT_FILE.is_file():
        print("OAuth client JSON is not present in the private VPS directory.", file=sys.stderr)
        return 2
    PRIVATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(PRIVATE_DIR, 0o700)
    client_id, client_secret = load_client()
    verifier = b64url(secrets.token_bytes(48))
    challenge = b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    state = b64url(secrets.token_bytes(32))
    redirect_uri = f"http://localhost:{PORT}{CALLBACK_PATH}"
    auth_uri = "https://accounts.google.com/o/oauth2/v2/auth"
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )

    result: dict[str, str] = {}

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, _format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != CALLBACK_PATH:
                self.send_error(404)
                return
            params = urllib.parse.parse_qs(parsed.query)
            if params.get("state", [""])[0] != state:
                self.send_error(400, "OAuth state check failed")
                return
            if params.get("error"):
                result["error"] = "Google authorization was declined or failed"
            else:
                result["code"] = params.get("code", [""])[0]
                if not result["code"]:
                    result["error"] = "Google returned no authorization code"
            body = (
                b"Authorization finished. You may close this tab and return to the VPS terminal."
                if not result.get("error")
                else b"Authorization did not finish. Return to the VPS terminal."
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            server.done = True

    server = http.server.HTTPServer((HOST, PORT), CallbackHandler)
    server.timeout = 1
    server.done = False
    print("OAuth callback is listening on VPS loopback port 8085.")
    print("Open this URL in your browser and verify the requested scope before approving:")
    print(f"{auth_uri}?{query}", flush=True)
    try:
        while not server.done:
            server.handle_request()
    except KeyboardInterrupt:
        print("\nAuthorization cancelled; no token was saved.")
        return 130
    finally:
        server.server_close()

    if result.get("error"):
        print(result["error"], file=sys.stderr)
        return 1

    body = urllib.parse.urlencode(
        {
            "code": result["code"],
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        }
    ).encode("ascii")
    request = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            token_response = json.loads(response.read())
    except Exception:
        print("Token exchange failed; no token was saved. Check VPS network and OAuth client setup.", file=sys.stderr)
        return 1

    granted_scopes = set(str(token_response.get("scope", "")).split())
    if granted_scopes != {SCOPE}:
        print("Google returned a scope set other than calendar.readonly; no token was saved.", file=sys.stderr)
        return 1
    if not token_response.get("refresh_token") or not token_response.get("access_token"):
        print("Google did not return the required offline token; no token was saved.", file=sys.stderr)
        return 1

    token = {
        "access_token": token_response["access_token"],
        "refresh_token": token_response["refresh_token"],
        "scope": SCOPE,
        "token_type": token_response.get("token_type", "Bearer"),
        "expiry_date": int(time.time() * 1000) + int(token_response.get("expires_in", 3600)) * 1000,
    }
    try:
        write_token(token)
    except Exception as exc:
        print(f"Token was not saved: {exc}", file=sys.stderr)
        return 1
    print("Read-only OAuth token saved privately with mode 0600.")
    print("Granted scope verified: calendar.readonly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
