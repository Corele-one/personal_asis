"""Fixed SSH interface for the approved owner profile; no arbitrary file paths."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from .personal_profile import validate


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode()


def revision(value):
    return hashlib.sha256(encoded(value)).hexdigest() if value is not None else None


def handle(request, home):
    if not isinstance(request, dict) or request.get('operation') not in ('read', 'replace'):
        raise ValueError('invalid_profile_request')
    writing = request['operation'] == 'replace'
    if set(request) != ({'operation', 'expected', 'profile'} if writing else {'operation'}):
        raise ValueError('invalid_profile_request')
    if writing:
        value = validate(request['profile'])
        if value['status'] != 'approved':
            raise ValueError('profile_approval_required')
        expected = request['expected']
        if expected is not None and (not isinstance(expected, str) or len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected)):
            raise ValueError('invalid_profile_revision')
    home = Path(home)
    target = home / 'personal-profile.json'
    lock_path = home / 'personal-profile.lock'
    if any(p.is_symlink() for p in (target, lock_path, home, *home.parents)):
        raise ValueError('profile_symlink_denied')
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    with lock_path.open('a') as lock:
        lock_path.chmod(0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        if target.exists():
            if target.stat().st_size > 16000:
                raise ValueError('profile_too_large')
            current = validate(json.loads(target.read_text()))
            if current['status'] != 'approved':
                raise ValueError('profile_approval_required')
        else:
            current = None
        current_hash = revision(current)
        if not writing:
            return dict(version=1, hash=current_hash, profile=current)
        if current_hash != expected:
            raise ValueError('profile_changed_reconfirmation_required')
        fd, name = tempfile.mkstemp(prefix='.profile-', dir=home)
        try:
            with os.fdopen(fd, 'wb') as out:
                out.write(encoded(value));out.flush();os.fsync(out.fileno())
            os.replace(name, target)
            target.chmod(0o600)
        finally:
            Path(name).unlink(missing_ok=True)
        return dict(version=1, hash=revision(value), updated=True)


def main():
    os.umask(0o077)
    try:
        raw = sys.stdin.read(32001)
        if len(raw.encode()) > 32000:
            raise ValueError('profile_request_too_large')
        result = handle(json.loads(raw), Path.home() / '.local/share/personal-asis-life')
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, KeyError, TypeError, OSError):
        # No request body, source text or remote paths in error output.
        print('{"error":"profile_transfer_rejected"}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
