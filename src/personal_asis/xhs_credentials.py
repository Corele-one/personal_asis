"""Explicit owner import and a private stdin bridge for independent XHS MCP."""

import json
import re
import sys

from .credentials import CredentialStore, CredentialNotFound
from .reading_sources import SourceError


ACCOUNT = 'xiaohongshu-session'
SERVICE = 'local.personal-asis.reading'
MAX_SESSION = 128 * 1024


def normalize_cookies(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 200:
        raise SourceError('xhs_cookie_export_invalid')
    result = []
    for row in value:
        if not isinstance(row, dict):
            raise SourceError('xhs_cookie_export_invalid')
        domain = str(row.get('domain', '')).lstrip('.').lower()
        if domain != 'xiaohongshu.com' and not domain.endswith('.xiaohongshu.com'):
            continue
        name, cookie = row.get('name'), row.get('value')
        if (not isinstance(name, str) or not re.fullmatch(r'[!#$%&\'*+.^_`|~0-9A-Za-z-]{1,100}', name)
                or not isinstance(cookie, str) or len(cookie) > 16384
                or any(ord(c) < 32 or ord(c) > 126 for c in cookie)):
            raise SourceError('xhs_cookie_export_invalid')
        path = row.get('path', '/')
        if not isinstance(path, str) or not path.startswith('/') or len(path) > 200:
            raise SourceError('xhs_cookie_export_invalid')
        expiry = row.get('expires', row.get('expirationDate', -1))
        if row.get('session') or expiry in (None, 0):
            expiry = -1
        if not isinstance(expiry, (int, float)) or isinstance(expiry, bool):
            raise SourceError('xhs_cookie_export_invalid')
        result.append({'name': name, 'value': cookie, 'domain': '.' + domain,
            'path': path, 'secure': bool(row.get('secure', True)),
            'httpOnly': bool(row.get('httpOnly', False)), 'expires': expiry})
    if not result or not any(c['name'] == 'web_session' and c['value'] for c in result):
        raise SourceError('xhs_cookie_export_missing_session')
    return result


def import_export(raw, store=None):
    if not isinstance(raw, str) or not 1 <= len(raw) <= MAX_SESSION:
        raise SourceError('xhs_cookie_export_invalid')
    raw = raw.strip()
    if raw.startswith('['):
        try:
            cookies = json.loads(raw)
        except ValueError:
            raise SourceError('xhs_cookie_export_invalid') from None
    else:
        # Cookie-Editor's Header String export: owner explicitly exports this domain.
        if raw.lower().startswith('cookie:'):
            raw = raw[7:].strip()
        cookies = []
        if '\n' in raw or '\r' in raw:
            raise SourceError('xhs_cookie_export_single_line_required')
        for part in raw.split(';'):
            if not part.strip():
                continue
            if '=' not in part:
                raise SourceError('xhs_cookie_export_invalid')
            name, value = part.strip().split('=', 1)
            cookies.append({'name': name, 'value': value, 'domain': '.xiaohongshu.com'})
    session = {'version': 2, 'cookies': normalize_cookies(cookies)}
    store = store or CredentialStore(ACCOUNT, SERVICE)
    try:
        previous = json.loads(store.get())
        seed = previous.get('seed') if isinstance(previous, dict) else None
        if type(seed) is int and seed > 0:
            session['seed'] = seed
    except CredentialNotFound:
        pass
    store.set(json.dumps(session, separators=(',', ':')))
    return {'source': 'xiaohongshu', 'session_imported': True, 'storage': 'os_keychain',
            'account_verified': False}


def bridge(request, store=None):
    store = store or CredentialStore(ACCOUNT, SERVICE)
    if not isinstance(request, dict) or request.get('action') not in ('read', 'write'):
        raise SourceError('xhs_keychain_operation_denied')
    if request['action'] == 'read':
        try:
            session = json.loads(store.get())
        except CredentialNotFound:
            session = {'version': 2, 'cookies': []}
        return {'session': session}
    session = request.get('session')
    if not isinstance(session, dict) or session.get('version') != 2:
        raise SourceError('xhs_keychain_session_invalid')
    cookies = session.get('cookies') or []
    if cookies:
        session['cookies'] = normalize_cookies(cookies)
    if len(json.dumps(session)) > MAX_SESSION:
        raise SourceError('xhs_keychain_session_invalid')
    store.set(json.dumps(session, separators=(',', ':')))
    return {'stored': True}


if __name__ == '__main__':
    try:
        if sys.stdin.isatty() or sys.stdout.isatty():
            raise SourceError('xhs_keychain_private_pipe_required')
        raw = sys.stdin.buffer.read(MAX_SESSION + 1)
        if len(raw) > MAX_SESSION:
            raise SourceError('xhs_keychain_session_invalid')
        sys.stdout.write(json.dumps(bridge(json.loads(raw))))
    except Exception:
        sys.stderr.write('xhs_keychain_bridge_failed\n')
        sys.exit(1)
