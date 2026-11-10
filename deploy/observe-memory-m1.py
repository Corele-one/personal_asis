#!/usr/bin/env python3
"""Bounded resource observations only; no model calls or platform messages."""
import argparse
import json
from pathlib import Path
import subprocess
import time
from urllib.request import urlopen

parser=argparse.ArgumentParser();parser.add_argument('--seconds',type=int,default=900);args=parser.parse_args()
home=Path('/home/mac/.local/share/personal-asis-memory-acceptance')
path=home/'resource-samples.jsonl'
if path.exists():raise SystemExit('observation_already_started_no_reset')
units=['personal-asis-memory','alma-work','astrbot','personal-asis-knowledge','personal-asis-dashboard']
started=time.monotonic()
with path.open('x') as output:
    path.chmod(0o600)
    index=0
    while time.monotonic()-started<args.seconds:
        sample=dict(elapsed=round(time.monotonic()-started,2),at=time.time(),units={})
        mem={k:int(v.split()[0]) for k,v in [line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines()]}
        sample.update(available_kib=mem['MemAvailable'],swap_used_kib=mem['SwapTotal']-mem['SwapFree'])
        for unit in units:
            raw=subprocess.check_output(['systemctl','show',unit,'-p','ActiveState','-p','MainPID',
                '-p','MemoryCurrent','-p','MemorySwapCurrent','-p','ControlGroup'],text=True)
            values=dict(line.split('=',1) for line in raw.splitlines())
            events=Path('/sys/fs/cgroup')/values['ControlGroup'].lstrip('/')/'memory.events'
            if events.exists():values['events']=dict(line.split() for line in events.read_text().splitlines())
            sample['units'][unit]=values
        health_start=time.monotonic()
        try:
            with urlopen('http://127.0.0.1:23001/api/health',timeout=5) as response:
                sample['work_health']=json.load(response).get('status')
        except Exception:sample['work_health']='unavailable'
        sample['work_health_ms']=round(1000*(time.monotonic()-health_start),2)
        sample['memory_pressure']=Path('/proc/pressure/memory').read_text().strip()
        output.write(json.dumps(sample)+'\n');output.flush()
        if index%12==0:print(json.dumps(dict(sample=index,elapsed=sample['elapsed'],available_kib=sample['available_kib'],work_health=sample['work_health'])),flush=True)
        index+=1
        time.sleep(5)
print(json.dumps(dict(observation_completed=True,samples=index,seconds=round(time.monotonic()-started,2))),flush=True)
