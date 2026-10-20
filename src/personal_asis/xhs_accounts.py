"""Account identifiers shared by isolated local MCP instances and native Pi."""
import json
import re
from pathlib import Path

SERVICE = 'local.personal-asis.reading'


def account_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9]{0,31}', value):
        raise ValueError('xhs_invalid_account_id')
    return value


def credential(account='default', kind='session'):
    account_id(account)
    if kind not in ('session', 'mcp'):
        raise ValueError('xhs_invalid_credential_kind')
    return 'xiaohongshu-' + kind + ('' if account == 'default' else ':' + account)


def token_variable(account):
    return 'ASIS_XHS_MCP_TOKEN' + ('' if account_id(account) == 'default' else '_' + account.upper())


def additional_accounts(home):
    path = Path(home) / 'xhs-accounts.json'
    if not path.exists():
        return {}
    from .social_reading import xhs_endpoint
    values = json.loads(path.read_text())
    if not isinstance(values, dict):
        raise ValueError('xhs_invalid_accounts')
    endpoints = set()
    for key, value in values.items():
        account_id(key)
        if not isinstance(value, dict) or set(value) != {'label', 'endpoint'}:
            raise ValueError('xhs_invalid_accounts')
        label = value['label']
        if not isinstance(label, str) or not label.strip() or len(label) > 80 or any(ord(c) < 32 for c in label):
            raise ValueError('xhs_invalid_account_label')
        endpoint = xhs_endpoint(value['endpoint'])
        if endpoint in endpoints or (key != 'default' and endpoint == 'http://127.0.0.1:18060/mcp'):
            raise ValueError('xhs_account_endpoint_conflict')
        endpoints.add(endpoint)
    return values


def register(home, account, label, port):
    from .native_sources import private_write, xhs_configuration
    account_id(account)
    if account == 'default' or type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('xhs_invalid_account_endpoint')
    values = additional_accounts(home)
    endpoint = f'http://127.0.0.1:{port}/mcp'
    if endpoint == xhs_configuration(home):
        raise ValueError('xhs_account_endpoint_conflict')
    candidate = {'label': label, 'endpoint': endpoint}
    if account in values and values[account] != candidate:
        raise ValueError('xhs_existing_account_configuration_changed')
    values[account] = candidate
    # Validate before persisting using the same rules as the reader.
    if (not isinstance(label, str) or not label.strip() or len(label) > 80
            or any(ord(c) < 32 for c in label)
            or port == 18060
            or len({v['endpoint'] for v in values.values()}) != len(values)):
        raise ValueError('xhs_invalid_account_configuration')
    private_write(Path(home) / 'xhs-accounts.json', json.dumps(values, ensure_ascii=False, indent=2))
    return candidate


def label_original(home, label):
    from .native_sources import private_write, xhs_configuration
    endpoint = xhs_configuration(home)
    if not endpoint or not isinstance(label, str) or not label.strip() or len(label) > 80 or any(ord(c) < 32 for c in label):
        raise ValueError('xhs_invalid_original_account')
    values = additional_accounts(home)
    values['default'] = {'label': label, 'endpoint': endpoint}
    private_write(Path(home) / 'xhs-accounts.json', json.dumps(values, ensure_ascii=False, indent=2))


def import_owner(account, dialog=False):
    """Owner-supplied export only; never inspect a browser's cookies or log secrets."""
    import getpass
    import subprocess
    import sys
    from .credentials import CredentialStore, CredentialNotFound
    from .xhs_credentials import import_export
    account_id(account)
    if account == 'default':
        raise ValueError('xhs_use_existing_original_account')
    if dialog:
        prompt = '导入新增小红书账号 ' + account + '：请粘贴本人手工导出的 Cookie-Editor Header String。仅存本机钥匙串，不发送聊天。'
        script = 'text returned of (display dialog ' + json.dumps(prompt, ensure_ascii=False) + ' default answer "" with hidden answer buttons {"取消", "导入"} default button "导入")'
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=600)
        if result.returncode:
            raise ValueError('xhs_owner_import_cancelled')
        raw = result.stdout.strip()
    else:
        if not sys.stdin.isatty():
            raise ValueError('xhs_owner_terminal_required')
        raw = getpass.getpass(f'新增账号 {account} Cookie-Editor Header String（不回显，仅存钥匙串）: ')
    # Parse in memory before touching the real store, then reject a duplicate session.
    class Candidate:
        def get(self):
            raise CredentialNotFound()
        def set(self, value):
            self.value = value
    candidate = Candidate()
    import_export(raw, candidate)
    session = json.loads(candidate.value)
    cookie = next(c['value'] for c in session['cookies'] if c['name'] == 'web_session')
    try:
        original = json.loads(CredentialStore(credential(), SERVICE).get())
    except CredentialNotFound:
        original = {}
    if any(c.get('name') == 'web_session' and c.get('value') == cookie for c in original.get('cookies', [])):
        raise ValueError('xhs_duplicate_original_session_export_other_account')
    return import_export(raw, account=account)


def main():
    import argparse
    from .native_sources import HOME
    parser = argparse.ArgumentParser(description='本机独立小红书账号配置；会话仅进入Keychain')
    parser.add_argument('action', choices=['import', 'install'])
    parser.add_argument('--account', required=True)
    parser.add_argument('--home', type=Path, default=HOME)
    parser.add_argument('--label')
    parser.add_argument('--port', type=int, default=18061)
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--dialog', action='store_true')
    args = parser.parse_args()
    try:
        if args.action == 'import':
            result = import_owner(args.account, args.dialog)
        else:
            if not args.binary or not args.label:
                raise ValueError('xhs_label_and_binary_required')
            from .xhs_service import install
            from .credentials import CredentialStore
            CredentialStore(credential(args.account), SERVICE).get()
            register(args.home, args.account, args.label, args.port)
            result = install(args.home, args.binary, args.account, args.port)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as error:
        # No upstream output, cookie text or exception payload in the console.
        print(json.dumps({'error': str(error) if isinstance(error, ValueError) and str(error).startswith('xhs_') else type(error).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
