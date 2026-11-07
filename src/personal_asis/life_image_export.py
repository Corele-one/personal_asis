"""Fixed SSH image read: record identity and hash, never a supplied path."""
import json
from pathlib import Path
import sys
from .life_store import LifeStore
from .life_images import export


def main():
    store = LifeStore(Path.home() / '.local/share/personal-asis-life/life.sqlite3')
    try:
        data = export(store, json.loads(sys.stdin.read(1024)))
        sys.stdout.buffer.write(data)
    finally:
        store.close()


if __name__ == '__main__':
    main()
