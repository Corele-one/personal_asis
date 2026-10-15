"""Optional Pi JSONL transport. Model access remains in the host adapter.

The child never receives credentials or raw tool results. The host's handler
must check the work claim, policy and budget on every request and final output.
"""

import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import tempfile
import time


PI_DIR = Path(__file__).resolve().parents[2] / 'runtime' / 'pi'


def run_pi(prompt, tools, session, handler, *, max_turns=6, timeout=20, runtime_dir=PI_DIR):
    runtime_dir = Path(runtime_dir).resolve()
    node = shutil.which('node')
    if node is None or not (runtime_dir/'node_modules/@earendil-works/pi-agent-core').is_dir():
        raise ValueError('optional_pi_not_installed')
    if type(max_turns) is not int or not 1 <= max_turns <= 12:
        raise ValueError('invalid_runtime_turn_limit')
    deadline = time.monotonic() + timeout
    with tempfile.TemporaryDirectory(prefix='asis-pi-') as temporary:
        # Do not inherit model keys, proxy credentials, NODE_OPTIONS or user config.
        env = {'PATH': str(Path(node).parent), 'HOME': temporary, 'TMPDIR': temporary,
               'LANG': 'en_US.UTF-8', 'DO_NOT_TRACK': '1'}
        process = subprocess.Popen([node, str(runtime_dir/'bridge.mjs')], cwd=temporary,
                                   env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, bufsize=0)
        try:
            def send(value):
                process.stdin.write((json.dumps(value, ensure_ascii=False)+'\n').encode())
                process.stdin.flush()
            send({'prompt': prompt, 'tools': tools, 'session': session, 'maxTurns': max_turns})
            buffer = b''
            sequence = 0
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                for _ in range(200):
                    while b'\n' not in buffer:
                        remaining = deadline-time.monotonic()
                        if remaining <= 0 or not selector.select(remaining):
                            raise ValueError('pi_bridge_timeout')
                        chunk = os.read(process.stdout.fileno(), 65536)
                        if not chunk:
                            raise ValueError('pi_bridge_disconnected')
                        buffer += chunk
                        if len(buffer) > 1024*1024:
                            raise ValueError('pi_bridge_output_too_large')
                    line, buffer = buffer.split(b'\n', 1)
                    try:
                        event = json.loads(line)
                    except (ValueError, UnicodeError):
                        raise ValueError('pi_bridge_invalid_protocol') from None
                    if event.get('kind') == 'done':
                        return handler('done', event)
                    if event.get('kind') not in ('model', 'tool') or event.get('id') != sequence+1:
                        raise ValueError('pi_bridge_invalid_protocol')
                    sequence += 1
                    # On any host rejection kill the entire loop, not a follow-up retry.
                    reply = handler(event['kind'], event)
                    send({'id': sequence, 'ok': True, 'value': reply})
                raise ValueError('pi_bridge_event_limit')
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            process.stdin.close()
            process.stdout.close()
