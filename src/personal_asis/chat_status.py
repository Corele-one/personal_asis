"""Private plugin heartbeat for observations, never a platform message."""
from contextlib import suppress
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile


def publish(home, *, ready=True):
    temporary = None
    try:
        home = Path(home)
        fd, temporary = tempfile.mkstemp(prefix='.chat-status-', dir=home)
        with os.fdopen(fd, 'w') as handle:
            json.dump(dict(version='2.13.0',ready=bool(ready),observed_at=datetime.now(timezone.utc).isoformat()),handle)
        os.replace(temporary,home/'chat-status.json')
        return True
    except OSError:
        return False
    finally:
        if temporary:
            with suppress(OSError):
                Path(temporary).unlink(missing_ok=True)
