"""Local exclusion checks. Never send source text to a model for classification."""

from pathlib import PurePosixPath
import re


VERSION = 'explicit-exclusion-and-credentials-v1'
CREDENTIAL_NAMES = {'id_rsa', 'id_ed25519', 'id_ecdsa', 'id_dsa', 'cookies.json',
                    'auth.json', 'credentials.json', 'credentials.md', 'passwords.md',
                    '账号密码.md', '密码清单.md'}
CREDENTIAL_DIRS = {'.ssh', '.aws', '.gnupg'}
TOKEN = re.compile(r'(?:sk-[A-Za-z0-9_-]{24,}|gh[opusr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})')
PRIVATE_KEY = re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----')
AUTH_HEADER = re.compile(r'(?im)^\s*(?:authorization\s*:\s*(?:Bearer|Basic)|(?:set-)?cookie\s*:)\s+(\S{6,})')
ASSIGNMENT = re.compile(
    r'''(?im)(?<![\w])(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|client[_ -]?secret|password|passwd|密码|口令|API密钥|访问令牌)["']?\s*[:=：]\s*["']?([^\s"'`#;,，；]{6,})''')
PLACEHOLDER = re.compile(r'(?i)^(?:your[_-]|example[_-]|replace[_-]|placeholder|changeme|<|\$|os\.getenv|process\.env|getenv\(|getpass\.)')


def credential_path(relative):
    parts = PurePosixPath(relative.replace('\\', '/')).parts
    if not parts:
        return False
    name = parts[-1].lower()
    return (bool(set(part.lower() for part in parts) & CREDENTIAL_DIRS)
            or name in CREDENTIAL_NAMES or name == '.env' or name.startswith('.env.')
            or name.endswith(('.key', '.p12', '.pfx', '.kdbx')) or bool(TOKEN.search(relative)))


def exclusion_reason(relative, text=None):
    if credential_path(relative):
        return 'credential_path'
    if text is None:
        return None
    lines = text.splitlines()
    if lines and lines[0].strip() == '---':
        end = next((i for i in range(1,len(lines)) if lines[i].strip() in {'---','...'}),len(lines))
        if re.search(r'(?im)^\s*assistant_exclude\s*:\s*(?:true|yes|1)\s*$', '\n'.join(lines[1:end])):
            return 'assistant_excluded'
    if PRIVATE_KEY.search(text) or TOKEN.search(text):
        return 'credential_content'
    for match in AUTH_HEADER.finditer(text):
        if not PLACEHOLDER.search(match.group(1)):
            return 'credential_content'
    for match in ASSIGNMENT.finditer(text):
        value = match.group(1).rstrip(')}]')
        if not PLACEHOLDER.search(value) and '(' not in value:
            return 'credential_content'
    return None
