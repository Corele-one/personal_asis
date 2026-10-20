#!/usr/bin/env python3
"""Restore an exact prior plugin/unit/release selection without deleting life data."""
import json
from pathlib import Path
import shutil
import subprocess

backup=Path(__file__).resolve().parent
state=json.loads((backup/'rollback.json').read_text())
run=lambda *args:subprocess.run(args,check=True,capture_output=True)
run('sudo','systemctl','stop','astrbot.service')
run('sudo','systemctl','disable','--now','personal-asis-dashboard.service')
plugins=Path('/home/mac/astrbot/data/plugins');configs=plugins.parent/'config'
for name,present in state['previous_plugins'].items():
    current=plugins/name
    if current.exists():shutil.rmtree(current)
    if present:shutil.copytree(backup/name,current)
    config=configs/(name+'_config.json')
    if (backup/config.name).exists():shutil.copyfile(backup/config.name,config)
    else:config.unlink(missing_ok=True)
for name,present in state['previous_units'].items():
    target='/etc/systemd/system/'+name
    if present:run('sudo','cp',str(backup/name),target)
    else:run('sudo','rm','-f',target)
link=Path('/home/mac/personal-asis-v2');link.unlink(missing_ok=True)
if state['previous_link']:link.symlink_to(state['previous_link'],target_is_directory=True)
run('sudo','systemctl','daemon-reload')
for name,present in state['previous_units'].items():
    if present:run('sudo','systemctl','enable','--now',name)
run('sudo','systemctl','start','astrbot.service')
print('prior_release_restored_life_data_preserved')
