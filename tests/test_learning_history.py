import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from personal_asis.config import parse_config
from personal_asis.dashboard import snapshot
from personal_asis.learning_history import ALIASES, UNFINISHED, parse_document, scan, from_shared
from personal_asis.learning_tracker import render_note
from personal_asis.life_store import LifeStore
from personal_asis.shared_sources import document_bodies
from personal_asis.shared_store import SharedStore, identity


DAILY = 'Calendar/Journal/Daily/2026-05-07.md'
JOURNAL = 'Research/Journal/2026-07-14.md'
LIFE = '''---
date: 2026-05-07
---
### 🧾Task
- [x] DDCA把乱序执行学完
- [x] 模电复习 依旧没有完成
- [x] 明天马原画重点
- [x] 查看奖学金申请
- [ ] 模集第三章
### ⚛️Habits
- [x] reading
#### 📖Learning
- [Analog::1]：学习了共源放大电路
- [Signal::0]
- [x] 我新加的科目
- [ ] C++
#### End-of-Day Checklist
- [x] Backup Vault
```md
### Learning
- [x] 伪造科目
```
'''
STUDY = "# ToDo\n- [ ] 未来计划\n# Today‘s Work\n学习了GEMM和Attention的数据流\n- [ ] 尚未验证的猜想\n# Tomorrow Plan\n继续实验\n# Prompt\n复制的模型回答\n"


class LearningHistoryTests(unittest.TestCase):
    def test_dated_owner_sections_numeric_flags_and_checked_tasks_only(self):
        rows = parse_document(LIFE, 'life', DAILY)
        self.assertEqual([(r['topic'],r['phase']) for r in rows],
                         [('DDCA','task'),('模拟电路','legacy'),('我新加的科目','legacy')])
        self.assertIn('共源',rows[1]['content'])
        self.assertTrue(all(r['day']=='2026-05-07' and r['line']>0 for r in rows))
        self.assertEqual(rows,parse_document(LIFE,'life',DAILY))

    def test_study_excludes_todo_tomorrow_prompt_templates_and_unchecked_only_day(self):
        rows=parse_document(STUDY,'study',JOURNAL)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['phase'],'work')
        self.assertEqual(rows[0]['content'],'学习了GEMM和Attention的数据流')
        for source,path in [('study','Template/2026-07-14.md'),('study','Research/Journal/summary.md'),('life','Calendar/Journal/Daily/2026-02-30.md')]:
            self.assertEqual(parse_document(STUDY,source,path),[])
        self.assertEqual(parse_document('# Today’s Work\n- [ ] 计划\n# Tomorrow Plan\n','study',JOURNAL),[])

    def test_scan_respects_exclusions_symlinks_and_never_modifies_originals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();p=root/DAILY;p.parent.mkdir(parents=True);p.write_text(LIFE)
            other=p.with_name('2026-05-08.md');other.symlink_to(p)
            config=parse_config({'node_id':'fixture','sources':[{'id':'life','root':str(root),'policy':'private','index':True,'remote_metadata':False,'exclude':[]}]})
            before=p.read_bytes();result=scan(config)
            self.assertEqual(len(result['files']),1);self.assertEqual(p.read_bytes(),before)
            self.assertEqual(result['files'][0]['hash'],hashlib.sha256(before).hexdigest())
            config=parse_config({'node_id':'fixture','sources':[{'id':'life','root':str(root),'policy':'private','index':True,'remote_metadata':False,'exclude':['Calendar/*']}]})
            self.assertEqual(scan(config)['rows'],[])

    def test_shared_copy_withdrawal_hash_and_incomplete_parts(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp).resolve();mac=SharedStore(home/'mac.sqlite3','mac');self.addCleanup(mac.close)
            remote=SharedStore(home/'shared.sqlite3','vps');self.addCleanup(remote.close)
            bodies=document_bodies('study',JOURNAL,'日志',STUDY)
            mac.put('notes',identity('journal'),bodies[0]);remote.receive(mac.export(),'mac')
            before=remote.db.total_changes;result=from_shared(home)
            self.assertEqual(len(result['rows']),1);self.assertEqual(remote.db.total_changes,before)
            mac.put('notes',identity('journal'),None);remote.receive(mac.export(),'mac')
            self.assertEqual(from_shared(home)['rows'],[])
            body=dict(bodies[0],parts=2);mac.put('notes',identity('bad'),body);remote.receive(mac.export(),'mac')
            self.assertEqual(from_shared(home)['incomplete'],1)

    def test_history_dashboard_keeps_astrbot_messages_and_habits_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp).resolve()
            with SharedStore(home/'shared.sqlite3','vps') as remote:
                with SharedStore(home/'mac.sqlite3','mac') as mac:
                    mac.put('notes',identity('daily'),document_bodies('life',DAILY,'日记',LIFE)[0]);remote.receive(mac.export(),'mac')
            life=LifeStore(home/'life.sqlite3')
            try:
                life.capture('synthetic','owner','one','/life 今天天气不错','2026-05-07T10:00:00+08:00')
            finally:
                life.close()
            result=snapshot(home,'2026-05-07')
            self.assertEqual(len(result['learning_history']['rows']),3)
            self.assertEqual(len(result['astrbot']['records']),1)
            self.assertEqual(result['tracking']['learning'],[])
            self.assertNotIn(str(home),json.dumps(result))

    @unittest.skipUnless(shutil.which('node'),'Node required for view parser parity')
    def test_live_view_matches_import_parser_and_compiles_with_study_text(self):
        module=Path(__file__).resolve().parents[1]/'src/personal_asis/learning_tracker.mjs'
        rules=dict(aliases=ALIASES,unfinished=UNFINISHED.pattern)
        script='import {historicalLifeRows} from '+json.dumps(module.as_uri())+';console.log(JSON.stringify(historicalLifeRows('+','.join(map(lambda v:json.dumps(v,ensure_ascii=False),(LIFE,DAILY,'2026-05-07',rules)))+')));'
        result=subprocess.run(['node','--input-type=module','-e',script],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        expected=[{k:v for k,v in r.items() if k!='id'} for r in parse_document(LIFE,'life',DAILY)]
        self.assertEqual(json.loads(result.stdout),expected)
        note=render_note(parse_document(STUDY,'study',JOURNAL),imported_at='2026-10-27')
        self.assertIn('学习了GEMM和Attention',note)
        code=note.split('```dataviewjs\n',1)[1].rsplit('\n```',1)[0]
        result=subprocess.run(['node','-e',"new (Object.getPrototypeOf(async function(){}).constructor)('dv','app','container',"+json.dumps(code)+");"],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        with self.assertRaises(ValueError):render_note(parse_document(LIFE,'life',DAILY))
