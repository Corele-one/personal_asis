"""Independent loopback MCP supervisor; no account data or secrets in plists/logs."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import secrets
import signal
import subprocess
import sys

from .credentials import CredentialStore, CredentialNotFound
from .reading import private_file
from .reading_sources import SourceError
from .social_reading import process_env
from .xhs_accounts import account_id, credential, SERVICE


LABEL = 'local.personal-asis.xiaohongshu'


def plist(home, binary, account='default', port=18060):
    account_id(account)
    if type(port) is not int or not 1024 <= port <= 65535 or (account != 'default' and port == 18060):
        raise ValueError('xhs_invalid_account_endpoint')
    return {'Label': LABEL + ('' if account == 'default' else '.' + account), 'ProgramArguments': [sys.executable, '-m', 'personal_asis.xhs_service',
        '--home', str(Path(home)), '--binary', str(Path(binary)), '--account', account, '--port', str(port)],
        'EnvironmentVariables': {'PYTHONPATH': str(Path(__file__).resolve().parents[1]),
                                 'PYTHONUNBUFFERED': '1'},
        'RunAtLoad': True, 'KeepAlive': {'SuccessfulExit': False}, 'ThrottleInterval': 30,
        'StandardOutPath': '/dev/null', 'StandardErrorPath': '/dev/null'}


def install(home, binary, account='default', port=18060):
    if sys.platform != 'darwin':
        raise SourceError('xhs_mcp_service_macos_only')
    home, binary = Path(home).resolve(), Path(binary).resolve()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise SourceError('xhs_mcp_binary_unavailable')
    raw = plist(home, binary, account, port)
    label = raw['Label']
    store = CredentialStore(credential(account, 'mcp'), SERVICE)
    try:
        token = store.get()
        if not token:
            raise SourceError('xhs_mcp_credential_unavailable')
    except CredentialNotFound:
        store.set(secrets.token_urlsafe(32))
    path = Path.home()/'Library/LaunchAgents'/f'{label}.plist'
    if path.exists():
        private_file(home/'upgrade-rollback'/f'{label}.plist', path.read_bytes())
    private_file(path, plistlib.dumps(raw))
    target = f'gui/{os.getuid()}'
    subprocess.run(['launchctl', 'bootout', target+'/'+label], capture_output=True, timeout=20)
    result = subprocess.run(['launchctl', 'bootstrap', target, str(path)], capture_output=True, timeout=20)
    if result.returncode:
        raise SourceError('xhs_mcp_service_start_failed')
    result = subprocess.run(['launchctl', 'kickstart', target+'/'+label], capture_output=True, timeout=20)
    if result.returncode:
        raise SourceError('xhs_mcp_service_start_failed')
    filename = 'xhs-mcp-service' + ('' if account == 'default' else '-' + account) + '.json'
    private_file(home/filename, (json.dumps({'label': label,
        'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
        'bind': f'127.0.0.1:{port}', 'auth': 'os_keychain',
        'session_storage': 'os_keychain', 'background_fetch_enabled': False})+'\n').encode())
    return {'service_installed': True, 'label': label, 'bind': f'127.0.0.1:{port}',
            'account_verified': False, 'background_fetch_enabled': False}


def run(home, binary, account='default', port=18060):
    plist(home, binary, account, port)  # Validate even when invoked directly.
    home = Path(home).resolve()
    os.umask(0o077)
    env = process_env()
    env.update({'AUTH_TOKEN': CredentialStore(credential(account, 'mcp'), SERVICE).get(),
        'ASIS_XHS_ACCOUNT': account,
        'ASIS_XHS_KEYCHAIN': '1', 'ASIS_XHS_PYTHON': sys.executable,
        'PYTHONPATH': str(Path(__file__).resolve().parents[1]),
        'ASIS_XHS_BROWSER_CACHE': str(home/'reading-tools/xiaohongshu/browser-cache')})
    child = subprocess.Popen([str(Path(binary).resolve()), '-port', f'127.0.0.1:{port}'],
        env=env, cwd=home, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, start_new_session=True)
    def stop(*args):
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    return child.wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--account', default='default')
    parser.add_argument('--port', type=int, default=18060)
    args = parser.parse_args()
    try:
        sys.exit(run(args.home, args.binary, args.account, args.port))
    except (OSError, ValueError, subprocess.SubprocessError):
        sys.stderr.write('xhs_mcp_supervisor_failed\n')
        sys.exit(1)
