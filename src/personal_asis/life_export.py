"""Fixed SSH read interface. Nothing from stdin is interpreted as code or a path."""
import json
import sys
from pathlib import Path
from .life_store import LifeStore


def main():
    request = json.loads(sys.stdin.read(1024))
    if set(request) != {'after'}:
        raise ValueError('invalid_export_request')
    store = LifeStore(Path.home() / '.local/share/personal-asis-life/life.sqlite3')
    try:
        print(json.dumps(store.export(request['after']), ensure_ascii=False))
    finally:
        store.close()


if __name__ == '__main__':
    main()
