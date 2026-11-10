#!/usr/bin/env python3
"""Bounded current-runtime observations; no generation, restarts or source reads."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.request import urlopen

p = argparse.ArgumentParser()
p.add_argument('--seconds', type=int, default=600)
p.add_argument('--output', type=Path, required=True)
args = p.parse_args()
if not 10 <= args.seconds <= 3600:
    p.error('seconds must be 10..3600')
os.umask(0o077)
units = ['alma-work', 'astrbot', 'personal-asis-dashboard',
         'personal-asis-knowledge', 'personal-asis-memory']
start = time.monotonic()
with args.output.open('x') as out:
    while time.monotonic() - start < args.seconds:
        sample = dict(elapsed=round(time.monotonic()-start, 2), at=time.time(), units={})
        mem = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
        sample.update(available_kib=int(mem['MemAvailable'].split()[0]),
                      swap_used_kib=int(mem['SwapTotal'].split()[0])-int(mem['SwapFree'].split()[0]))
        for unit in units:
            raw = subprocess.check_output(['systemctl', 'show', unit, '-p', 'ActiveState',
                '-p', 'MainPID', '-p', 'NRestarts', '-p', 'MemoryCurrent',
                '-p', 'MemorySwapCurrent', '-p', 'ControlGroup'], text=True)
            values = dict(line.split('=', 1) for line in raw.splitlines())
            events = Path('/sys/fs/cgroup') / values['ControlGroup'].lstrip('/') / 'memory.events'
            if events.is_file():
                values['events'] = dict(line.split() for line in events.read_text().splitlines())
            sample['units'][unit] = values
        before = time.monotonic()
        try:
            with urlopen('http://127.0.0.1:23001/api/health', timeout=5) as response:
                sample['health'] = json.load(response).get('status')
        except Exception:
            sample['health'] = 'unavailable'
        sample['health_ms'] = round(1000*(time.monotonic()-before), 2)
        sample['pressure'] = Path('/proc/pressure/memory').read_text().strip()
        out.write(json.dumps(sample)+'\n')
        out.flush()
        time.sleep(5)
print(json.dumps(dict(completed=True, seconds=round(time.monotonic()-start, 2))))
