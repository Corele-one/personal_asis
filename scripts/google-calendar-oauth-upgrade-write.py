#!/usr/bin/env python3
"""Upgrade the private Calendar token to read calendars + write owned events.

Run only on the AstrBot VPS. The existing read-only token is retained in a
0600 backup and is replaced only after Google returns exactly both approved
Calendar scopes plus a refresh token.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


PRIVATE_DIR = Path('/home/mac/astrbot/data/google-calendar-mcp')
CLIENT_FILE = PRIVATE_DIR / 'gcp-oauth.keys.json'
TOKEN_FILE = PRIVATE_DIR / 'tokens.json'
HOST = '127.0.0.1'
PORT = 8085
CALLBACK_PATH = '/oauth2callback'
READ_SCOPE = 'https://www.googleapis.com/auth/calendar.readonly'
WRITE_SCOPE = 'https://www.googleapis.com/auth/calendar.events.owned'
EXPECTED_SCOPES = {READ_SCOPE, WRITE_SCOPE}


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def atomic_private_write(path: Path, value: dict[str, object]) -> None:
    fd, temporary = tempfile.mkstemp(prefix='.calendar-token-', dir=PRIVATE_DIR)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main() -> int:
    PRIVATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(PRIVATE_DIR, 0o700)
    try:
        original = TOKEN_FILE.read_bytes()
        old = json.loads(original)['normal']
        if (set(str(old.get('scope', '')).split()) != {READ_SCOPE} or not old.get('refresh_token')
                or TOKEN_FILE.is_symlink() or (TOKEN_FILE.stat().st_mode & 0o777) != 0o600
                or CLIENT_FILE.is_symlink() or (CLIENT_FILE.stat().st_mode & 0o777) != 0o600):
            raise ValueError
        client = json.loads(CLIENT_FILE.read_text(encoding='utf-8'))['installed']
        client_id, client_secret = client['client_id'], client['client_secret']
        if client.get('auth_uri', 'https://accounts.google.com/o/oauth2/auth') != 'https://accounts.google.com/o/oauth2/auth':
            raise ValueError
        if client.get('token_uri', 'https://oauth2.googleapis.com/token') != 'https://oauth2.googleapis.com/token':
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError):
        print('Private OAuth client or existing read-only token is invalid; nothing changed.')
        return 2

    original_hash = hashlib.sha256(original).digest()
    verifier = b64url(secrets.token_bytes(48))
    challenge = b64url(hashlib.sha256(verifier.encode('ascii')).digest())
    state = b64url(secrets.token_bytes(32))
    redirect_uri = f'http://localhost:{PORT}{CALLBACK_PATH}'
    query = urllib.parse.urlencode({
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': ' '.join(sorted(EXPECTED_SCOPES)),
        'access_type': 'offline',
        'include_granted_scopes': 'true',
        'prompt': 'consent',
        'state': state,
        'code_challenge': challenge,
        'code_challenge_method': 'S256',
    })
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
            if params.get('state', [''])[0] != state:
                self.send_error(400, 'OAuth state check failed')
                return
            if params.get('error'):
                result['error'] = 'Google authorization was declined or failed'
            else:
                result['code'] = params.get('code', [''])[0]
                if not result['code']:
                    result['error'] = 'Google returned no authorization code'
            body = (b'Authorization finished. Return to the VPS terminal.' if not result.get('error')
                    else b'Authorization did not finish. Return to the VPS terminal.')
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            server.done = True

    server = http.server.HTTPServer((HOST, PORT), CallbackHandler)
    server.timeout = 1
    server.done = False
    print('OAuth callback is listening on VPS loopback port 8085.')
    print('Review both requested scopes on Google before approving:')
    print(f'https://accounts.google.com/o/oauth2/v2/auth?{query}', flush=True)
    try:
        while not server.done:
            server.handle_request()
    except KeyboardInterrupt:
        print('\nAuthorization cancelled; existing read-only token remains active.')
        return 130
    finally:
        server.server_close()
    if result.get('error'):
        print(result['error'])
        return 1

    body = urllib.parse.urlencode({
        'code': result['code'],
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code',
        'code_verifier': verifier,
    }).encode('ascii')
    request = urllib.request.Request(
        'https://oauth2.googleapis.com/token', data=body,
        headers={'Content-Type': 'application/x-www-form-urlencoded'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            token = json.loads(response.read())
    except Exception:
        print('Token exchange failed; existing read-only token remains active.')
        return 1

    granted = set(str(token.get('scope', '')).split())
    if granted != EXPECTED_SCOPES or not token.get('refresh_token') or not token.get('access_token'):
        print('Google did not grant exactly the reviewed read + owned-event scopes; existing token remains active.')
        return 1
    if hashlib.sha256(TOKEN_FILE.read_bytes()).digest() != original_hash:
        print('Existing token changed during authorization; no token was replaced.')
        return 1

    backup = PRIVATE_DIR / ('tokens.readonly-backup-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ') + '.json')
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(original)
        stream.flush()
        os.fsync(stream.fileno())
    atomic_private_write(TOKEN_FILE, {'normal': token})
    print('Calendar scopes verified; token upgraded privately with mode 0600.')
    print('The previous read-only token was retained in a private 0600 backup.')
    print('Granted scopes: calendar.readonly, calendar.events.owned')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
