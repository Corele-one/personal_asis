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


LABEL = 'local.personal-asis.xiaohongshu'


def plist(home, binary):
    return {'Label': LABEL, 'ProgramArguments': [sys.executable, '-m', 'personal_asis.xhs_service',
        '--home', str(Path(home)), '--binary', str(Path(binary))],
        'EnvironmentVariables': {'PYTHONPATH': str(Path(__file__).resolve().parents[1]),
                                 'PYTHONUNBUFFERED': '1'},
        'RunAtLoad': True, 'KeepAlive': {'SuccessfulExit': False}, 'ThrottleInterval': 30,
        'StandardOutPath': '/dev/null', 'StandardErrorPath': '/dev/null'}


def install(home, binary):
    if sys.platform != 'darwin':
        raise SourceError('xhs_mcp_service_macos_only')
    home, binary = Path(home).resolve(), Path(binary).resolve()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise SourceError('xhs_mcp_binary_unavailable')
    store = CredentialStore('xiaohongshu-mcp', 'local.personal-asis.reading')
    try:
        token = store.get()
        if not token:
            raise SourceError('xhs_mcp_credential_unavailable')
    except CredentialNotFound:
        store.set(secrets.token_urlsafe(32))
    path = Path.home()/'Library/LaunchAgents'/f'{LABEL}.plist'
    if path.exists():
        private_file(home/'upgrade-rollback'/f'{LABEL}.plist', path.read_bytes())
    raw = plist(home, binary)
    private_file(path, plistlib.dumps(raw))
    target = f'gui/{os.getuid()}'
    subprocess.run(['launchctl', 'bootout', target+'/'+LABEL], capture_output=True, timeout=20)
    result = subprocess.run(['launchctl', 'bootstrap', target, str(path)], capture_output=True, timeout=20)
    if result.returncode:
        raise SourceError('xhs_mcp_service_start_failed')
    result = subprocess.run(['launchctl', 'kickstart', target+'/'+LABEL], capture_output=True, timeout=20)
    if result.returncode:
        raise SourceError('xhs_mcp_service_start_failed')
    private_file(home/'xhs-mcp-service.json', (json.dumps({'label': LABEL,
        'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
        'bind': '127.0.0.1:18060', 'auth': 'os_keychain',
        'session_storage': 'os_keychain', 'background_fetch_enabled': False})+'\n').encode())
    return {'service_installed': True, 'label': LABEL, 'bind': '127.0.0.1:18060',
            'account_verified': False, 'background_fetch_enabled': False}


def run(home, binary):
    home = Path(home).resolve()
    os.umask(0o077)
    env = process_env()
    env.update({'AUTH_TOKEN': CredentialStore('xiaohongshu-mcp', 'local.personal-asis.reading').get(),
        'ASIS_XHS_KEYCHAIN': '1', 'ASIS_XHS_PYTHON': sys.executable,
        'PYTHONPATH': str(Path(__file__).resolve().parents[1]),
        'ASIS_XHS_BROWSER_CACHE': str(home/'reading-tools/xiaohongshu/browser-cache')})
    child = subprocess.Popen([str(Path(binary).resolve()), '-port', '127.0.0.1:18060'],
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
    args = parser.parse_args()
    try:
        sys.exit(run(args.home, args.binary))
    except (OSError, ValueError, subprocess.SubprocessError):
        sys.stderr.write('xhs_mcp_supervisor_failed\n')
        sys.exit(1)
