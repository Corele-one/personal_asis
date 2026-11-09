#!/usr/bin/env python3
"""Run the unmodified official binary; journal only fixed diagnostic labels."""
import os
import signal
import subprocess
import sys


def diagnostic_labels(chunks):
    labels = {
        b"heap out of memory": "v8_heap_exhausted",
        b"NODE_MODULE_VERSION": "native_module_abi_mismatch",
        b"EADDRINUSE": "listener_port_in_use",
    }
    reported = set()
    buffer = b""
    for chunk in chunks:
        buffer = (buffer + chunk)[-8192:]
        for pattern, label in labels.items():
            if pattern in buffer and label not in reported:
                yield label
                reported.add(label)


def main():
    child = subprocess.Popen(["/opt/alma-work/current/bin/alma-server"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True
        if child.poll() is None:
            child.send_signal(signum)

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, stop)
    chunks = iter(lambda: os.read(child.stderr.fileno(), 4096), b"")
    for label in diagnostic_labels(chunks):
        print("alma-work diagnostic=" + label, file=sys.stderr, flush=True)
    code = child.wait()
    if code and not stopping:
        print("alma-work child_exit=" + str(code), file=sys.stderr, flush=True)
    return 0 if stopping else code if code >= 0 else 128 - code


if __name__ == "__main__":
    sys.exit(main())
