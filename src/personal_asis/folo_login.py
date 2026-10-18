"""Folo's official browser exchange, with session storage only in the OS keychain.

Protocol: RSSNext/Folo apps/cli/src/browser-login.ts (folocli 0.0.5).
Never invoke `folo auth login`, which persists a plaintext config.json.
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import re
import secrets
import subprocess
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, unquote, urlencode, urlsplit
from urllib.request import Request, build_opener

from .credentials import CredentialStore
from .reading_sources import NoRedirect, SourceError


API = 'https://api.folo.is'
MAX_RESPONSE = 1024 * 1024


def valid_token(value):
    return (isinstance(value, str) and 0 < len(value) <= 8192
            and not any(c.isspace() or ord(c) < 33 or ord(c) > 126 or c in ';,' for c in value))


def request(path, token=None, body=None):
    """Fixed auth endpoints, no redirects, remote payloads or errors in diagnostics."""
    if path not in ('apply', 'verify', 'get-session'):
        raise SourceError('folo_login_endpoint_denied')
    endpoint = '/better-auth/' + ('one-time-token/' if path != 'get-session' else '') + path
    headers = {'Content-Type': 'application/json',
               'User-Agent': 'PersonalAsis/1.0 (Folo browser login)'}
    if token is not None:
        if not valid_token(token):
            raise SourceError('folo_login_invalid_token')
        headers.update(Authorization='Bearer ' + token,
                       Cookie=f'__Secure-better-auth.session_token={token}; better-auth.session_token={token}')
    raw = json.dumps(body).encode() if body is not None else None
    req = Request(API + endpoint, data=raw, headers=headers, method='POST' if body is not None else 'GET')
    try:
        with build_opener(NoRedirect()).open(req, timeout=25) as response:
            data = response.read(MAX_RESPONSE + 1)
            if len(data) > MAX_RESPONSE:
                raise SourceError('folo_login_response_too_large')
            cookies = response.headers.get_all('Set-Cookie', [])
            return response.status, cookies, json.loads(data)
    except HTTPError as exc:
        status = exc.code
        exc.close()
        return status, [], {}
    except Exception:
        raise SourceError('folo_login_network_or_response_error') from None


def exchange(one_time_token, transport=request):
    if not valid_token(one_time_token):
        raise SourceError('folo_login_invalid_token')
    status, cookies, data = transport('apply', body={'token': one_time_token})
    if status == 404:
        status, cookies, data = transport('verify', body={'token': one_time_token})
    token = None
    if 200 <= status < 300:
        for cookie in cookies:
            match = re.search(r'(?:^|[,;]\s*)(?:__Secure-)?better-auth\.session_token=([^;]+)', cookie)
            if match:
                token = match[1]
                break
        if token is None and isinstance(data, dict) and isinstance(data.get('session'), dict):
            token = data['session'].get('token')
        if not valid_token(token):
            raise SourceError('folo_login_missing_session_token')
    else:
        # The official CLI also supports a callback containing an existing session.
        token = one_time_token
    # Matches cli/src/client.ts normalizeToken before fetchAuthSession.
    token = unquote(token)
    if not valid_token(token):
        raise SourceError('folo_login_invalid_token')
    status, _, session = transport('get-session', token=token)
    if (status != 200 or not isinstance(session, dict)
            or not session.get('user') or not session.get('session')):
        raise SourceError('folo_login_session_rejected')
    return token


def callback_handler(state):
    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Request URLs contain credentials.

        def do_GET(self):
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            expected_host = f'127.0.0.1:{self.server.server_port}'
            accepted = (len(self.path) < 16000 and parsed.path == '/callback'
                        and self.headers.get('Host') == expected_host
                        and query.get('state') == [state['nonce']]
                        and len(query.get('token', [])) == 1
                        and valid_token(query['token'][0]) and 'token' not in state)
            if accepted:
                state['token'] = query['token'][0]
            self.send_response(200 if accepted else 400)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'none'")
            self.end_headers()
            message = ('Folo login received. Return to Personal Asis for verification.' if accepted
                       else 'Invalid login callback. Return to Personal Asis.')
            self.wfile.write(message.encode())

    return Callback


def login(timeout=600, notify=print, store=None, browser=None):
    if not 30 <= timeout <= 900:
        raise SourceError('folo_login_invalid_timeout')
    store = store or CredentialStore('folo', 'local.personal-asis.reading')
    state = {'nonce': secrets.token_urlsafe(24)}
    with HTTPServer(('127.0.0.1', 0), callback_handler(state)) as server:
        server.timeout = 1
        callback = f'http://127.0.0.1:{server.server_port}/callback?' + urlencode({'state': state['nonce']})
        url = 'https://app.folo.is/login?' + urlencode({'cli_callback': callback})
        notify('Folo login URL: ' + url)
        if browser is None:
            subprocess.run(['/usr/bin/open', url], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=10, check=False)
        else:
            browser(url)
        deadline = time.monotonic() + timeout
        while 'token' not in state and time.monotonic() < deadline:
            server.handle_request()
        if 'token' not in state:
            raise SourceError('folo_login_timeout')
    token = exchange(state.pop('token'))
    store.set(token)
    return {'source': 'folo', 'credential_stored': True, 'session_verified': True,
            'storage': 'os_keychain', 'plaintext_config_written': False}
