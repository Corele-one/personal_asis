"""Accept only Mac synchronization metadata via authenticated SSH, never note content."""
import json
import os
import sys
from pathlib import Path
from datetime import datetime


def validate(value):
    if set(value) != {'checked_at', 'pending', 'applied', 'sources'}:
        raise ValueError('invalid_mac_status_fields')
    if not isinstance(value['checked_at'], str) or len(value['checked_at']) > 80 or datetime.fromisoformat(value['checked_at']).tzinfo is None:
        raise ValueError('invalid_status_date')
    for k in ('pending','applied'):
        if type(value[k]) is not int or not 0 <= value[k] <= 1000000:
            raise ValueError('invalid_status_count')
    if (not isinstance(value['sources'], dict) or set(value['sources']) != {'study','life','wucai','xiaohongshu'}
        or any(type(v) is not bool for v in value['sources'].values())):
        raise ValueError('invalid_status_sources')
    return value


def main():
    os.umask(0o077)
    value = validate(json.loads(sys.stdin.read(4096)))
    directory = Path.home() / '.local/share/personal-asis-life'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = directory / 'mac-status.json'
    temp = target.with_suffix('.tmp')
    temp.write_text(json.dumps(value))
    temp.replace(target)
    print('{"saved":true}')


if __name__ == '__main__':
    main()
