"""Restore only this release's selection/config/code. Never restore data databases."""
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess

backup=Path(__file__).resolve().parent
state=json.loads((backup/'rollback.json').read_text())
data=Path('/home/mac/astrbot/data')
subprocess.run(['sudo','systemctl','stop','astrbot.service'],check=True,capture_output=True)
for name,present in state['plugins'].items():
    target=data/'plugins'/name
    if target.exists():shutil.rmtree(target)
    if present:shutil.copytree(backup/name,target)
shutil.copyfile(backup/'cmd_config.json',data/'cmd_config.json')
profile=data/'config'/state['profile_file']
if state['profile_existed']:shutil.copyfile(backup/'owner-profile.json',profile)
else:profile.unlink(missing_ok=True)
metadata=Path('/home/mac/.local/share/personal-asis-router/deployment.json')
if 'deployment_metadata_existed' in state:
    if state['deployment_metadata_existed']:
        shutil.copyfile(backup/'deployment-before.json',metadata)
    else:
        metadata.unlink(missing_ok=True)
db=sqlite3.connect(data/'data_v4.db')
with db:
    for row in state['preferences']:
        db.execute('DELETE FROM preferences WHERE scope=? AND scope_id=? AND key=?',
                   (row['scope'],row['scope_id'],row['key']))
        if row['old'] is not None:
            db.execute('INSERT INTO preferences(created_at,updated_at,scope,scope_id,key,value) '
                'VALUES(CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,?,?,?,?)',
                (row['scope'],row['scope_id'],row['key'],row['old']))
db.close()
subprocess.run(['sudo','systemctl','start','astrbot.service'],check=True,capture_output=True)
print('router_selection_restored_original_data_preserved')
