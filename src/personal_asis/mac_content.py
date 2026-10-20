"""Publish one explicitly confirmed Mac summary to the private Dashboard via SSH."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile


def validate(value):
    if set(value)!={'request_id','title','content'} or not re.fullmatch('[a-f0-9]{32}',value.get('request_id','')):
        raise ValueError('invalid_mac_publication')
    for key,limit in (('title',300),('content',16000)):
        text=value[key]
        if not isinstance(text,str) or not text.strip() or len(text.encode())>limit or any(ord(c)<32 and c not in '\n\r\t' for c in text):
            raise ValueError('invalid_mac_publication_text')
    return value


def save(value,home):
    value=validate(value)
    home=Path(home);home.mkdir(mode=0o700,parents=True,exist_ok=True)
    target=home/'mac-content.json'
    if target.exists() and json.loads(target.read_text()).get('request_id')==value['request_id']:
        return {'saved':True,'duplicate':True}
    value=dict(value,updated_at=datetime.now(timezone.utc).isoformat())
    fd,name=tempfile.mkstemp(prefix='.mac-content-',dir=home)
    try:
        with os.fdopen(fd,'w') as handle:handle.write(json.dumps(value,ensure_ascii=False))
        Path(name).replace(target);target.chmod(0o600)
    finally:
        Path(name).unlink(missing_ok=True)
    return {'saved':True,'duplicate':False}


def main():
    os.umask(0o077)
    print(json.dumps(save(json.loads(sys.stdin.read(128000)),Path.home()/'.local/share/personal-asis-life')))


if __name__=='__main__':main()
