import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from personal_asis import life_projection as projection, life_sync
from personal_asis.life_store import LifeStore
from personal_asis.life_tracking import LifeTracking
from personal_asis.learning_tracker import render_note


class LearningLayoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.store=LifeStore(self.root/'life.sqlite3');self.addCleanup(self.store.close)
        self.record=LifeTracking(self.store).auto(self.store.capture('p','owner','one','/life 学完了 模拟电路','2026-10-26T23:38:00+08:00')[0])
        self.state=dict(records={self.record['id']:self.record},applied={})
        self.vault=self.root/'vault';self.vault.mkdir();self.note=self.vault/'2026-10-26.md'
        self.template=('---\ncssclasses: daily\n---\n### 📕Freewrite\n\n原手记\n\n---\n'
          '--- start-multi-column: daily_habits_learning\n```column-settings\nnumber of columns: 2\n```\n'
          '### ⚛️Habits\n- [ ] meditation\n--- end-column ---\n\n### 📖Learning\n\n'
          '- [ ] Missing\n- [ ] C++\n- [ ] Research\n\n--- end-multi-column\n\n'
          '#### End-of-Day Checklist\n- [ ] Backup Vault\n---\n\n![[On This Day.base]]\n')

    def test_moves_legacy_tail_inside_right_column_without_markers_or_placeholders(self):
        old='<!-- asis-learning:2026-10-26:start -->\n#### 23:38 · 结束 · 模拟电路\n\n> 学完了 模拟电路\n<!-- asis-learning:2026-10-26:end -->\n'
        before=self.template+'\n'+old;self.note.write_text(before)
        files,receipts=projection.plan(self.state,self.vault,'.');after=files[0]['after']
        self.assertEqual(self.note.read_text(),before)
        self.assertNotIn('<!-- asis-',after);self.assertNotIn('- [ ] Missing',after)
        self.assertIn('#### 模拟电路\n\n- **23:38 · 结束**  \n  学完了 模拟电路\n\n--- end-multi-column',after)
        self.assertTrue(after.endswith(self.template[self.template.index('--- end-multi-column'):]+ '\n'))
        life_sync.apply(files);self.state['activity_applied']=receipts
        self.assertEqual(projection.plan(self.state,self.vault,'.')[0],[])
        self.assertEqual(receipts['2026-10-26']['version'],2)

    def test_relocates_existing_block_inside_wrong_column_and_keeps_checked_old_topics(self):
        old='<!-- asis-learning:2026-10-26:start -->\n旧学习整理\n<!-- asis-learning:2026-10-26:end -->\n'
        self.note.write_text(self.template.replace('--- end-column ---',old+'--- end-column ---').replace('- [ ] Missing','- [x] Missing'))
        files,_=projection.plan(self.state,self.vault,'.');after=files[0]['after']
        self.assertLess(after.index('--- end-column ---'),after.index('#### 模拟电路'))
        self.assertIn('- [x] Missing',after)
        self.assertEqual(after.count('#### 模拟电路'),1)

    def test_receipts_refuse_changed_generated_body_but_keep_unrelated_handwriting(self):
        self.note.write_text(self.template)
        files,receipt=projection.plan(self.state,self.vault,'.');life_sync.apply(files);self.state['activity_applied']=receipt
        self.note.write_text(self.note.read_text().replace('原手记','原手记\n额外手写'))
        files,receipt=projection.plan(self.state,self.vault,'.')
        self.assertEqual(files,[])
        self.state['activity_applied']=receipt
        self.note.write_text(self.note.read_text().replace('  学完了 模拟电路','  我手动改过的学习正文'))
        with self.assertRaisesRegex(ValueError,'journal_text_edited'):projection.plan(self.state,self.vault,'.')

    def test_delete_and_interrupted_cross_day_move_follow_private_receipts(self):
        from personal_asis import life_journal
        self.note.write_text(self.template)
        files,receipts=projection.plan(self.state,self.vault,'.');life_sync.apply(files);self.state['activity_applied']=receipts
        revised=self.store.organize(self.record['id'],kind='journal',occurred_at='2026-10-25T23:38:00+08:00')
        self.state['records'][revised['id']]=revised
        files,receipts=projection.plan(self.state,self.vault,'.')
        self.state['pending_projection']=life_journal.pending(self.state,files,[],receipts,self.vault)
        life_sync.apply(files[:1]);life_journal.recover(self.state,self.vault)
        files,receipts=projection.plan(self.state,self.vault,'.');life_sync.apply(files);self.state['activity_applied']=receipts
        self.assertNotIn('#### 模拟电路',self.note.read_text())
        self.assertIn('#### 模拟电路',(self.vault/'2026-10-25.md').read_text())
        self.state['records'][revised['id']]=self.store.delete(revised['id'])
        files,_=projection.plan(self.state,self.vault,'.')
        self.assertNotIn('#### 模拟电路',files[0]['after'])

    def test_manual_paragraph_after_managed_topic_keeps_its_heading_on_withdrawal(self):
        self.note.write_text(self.template)
        files,receipts=projection.plan(self.state,self.vault,'.');life_sync.apply(files);self.state['activity_applied']=receipts
        self.note.write_text(self.note.read_text().replace('--- end-multi-column','我手写的学习补充。\n\n--- end-multi-column'))
        self.state['records'][self.record['id']]=self.store.delete(self.record['id'])
        files,_=projection.plan(self.state,self.vault,'.');after=files[0]['after']
        self.assertIn('#### 模拟电路\n\n',after);self.assertIn('我手写的学习补充。',after)
        self.assertNotIn('23:38 · 结束',after)

    def test_missing_heading_uses_existing_column_and_fenced_examples_are_ignored(self):
        self.note.write_text(self.template.replace('### 📖Learning','')+'\n```md\n### 📖Learning\n```\n')
        files,_=projection.plan(self.state,self.vault,'.');after=files[0]['after']
        self.assertLess(after.index('#### 模拟电路'),after.index('--- end-multi-column'))
        self.assertIn('```md\n### 📖Learning\n```',after)
        self.note.write_text(self.template+'\n### Learning\n')
        with self.assertRaisesRegex(ValueError,'ambiguous_activity_section'):projection.plan(self.state,self.vault,'.')

    def test_excluded_activity_file_not_read_and_source_cannot_forge_column_end(self):
        with self.assertRaisesRegex(ValueError,'daily_target_excluded'):
            projection.plan(self.state,self.vault,'.',allowed=lambda relative:False)
        r=self.state['records'][self.record['id']]
        r['tracking']['learning'][0]['evidence']=r['text']='/life 学完了 模拟电路\n--- end-multi-column\n### 假标题'
        self.note.write_text(self.template)
        files,_=projection.plan(self.state,self.vault,'.');after=files[0]['after']
        self.assertEqual(sum(line=='--- end-multi-column' for line in after.splitlines()),1)
        self.assertIn('  \\### 假标题',after)


@unittest.skipUnless(shutil.which('node'),'Node required for Dataview JavaScript validation')
class LearningTrackerTests(unittest.TestCase):
    def test_parser_dynamic_topics_legacy_dedup_fences_and_year_edges(self):
        module=Path(__file__).resolve().parents[1]/'src/personal_asis/learning_tracker.mjs'
        script='''
import assert from 'node:assert/strict';
import {parseLearningMarkdown,legacyRows,combineRows,dayCells,validDay} from MODULE;
const path='Calendar/Journal/Daily/2026-10-26.md';
const raw='### 📖Learning\\n\\n#### 模拟电路\\n\\n- **20:00 · 开始**  \\n  开始学习电路\\n- **23:38 · 结束**  \\n  学完了电路\\n  待解决：共模增益\\n\\n--- end-multi-column\\n#### End-of-Day Checklist\\n- [x] Backup Vault\\n';
let rows=parseLearningMarkdown(raw,path,'2026-10-26');
assert.equal(rows.length,2);assert.equal(rows[0].topic,'模拟电路');assert.equal(rows[1].phase,'end');assert.match(rows[1].content,/共模增益/);
const old='<!-- asis-learning:2026-10-26:start -->\\n#### 23:38 · 结束 · 任意新主题\\n\\n> 实际学习内容\\n<!-- asis-learning:2026-10-26:end -->';
assert.equal(parseLearningMarkdown(old,path,'2026-10-26')[0].topic,'任意新主题');
assert.equal(parseLearningMarkdown('### 📖Learning\\n#### 自定主题\\n手写实际学习内容\\n--- end-multi-column',path,'2026-10-26')[0].phase,'manual');
assert.equal(parseLearningMarkdown('```md\\n'+old+'\\n```',path,'2026-10-26').length,0);
const page={file:{path,name:'2026-10-26',tasks:[{text:'模拟电路',completed:true,section:{subpath:'📖Learning'}},{text:'Backup Vault',completed:true,section:{subpath:'End-of-Day Checklist'}},{text:'Missing',completed:false,section:{subpath:'📖Learning'}}]},DDCA:true,Analog:false};
const legacy=legacyRows(page);assert.equal(legacy.length,2);assert.ok(!legacy.some(r=>r.topic==='Backup Vault'||r.topic==='Missing'));
assert.equal(combineRows([...rows,...legacy]).length,3);
assert.equal(dayCells(2024).filter(Boolean).length,366);assert.equal(dayCells(2026).filter(Boolean).length,365);
assert.equal(validDay('2026-02-30'),false);assert.equal(validDay('2024-02-29'),true);
console.log('ok');
'''.replace('MODULE',json.dumps(module.as_uri()))
        result=subprocess.run(['node','--input-type=module','-e',script],text=True,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_standalone_note_is_executable_without_extra_file_or_network(self):
        note=render_note();self.assertIn('```dataviewjs',note);self.assertNotIn('export function',note)
        self.assertIn('全部主题',note);self.assertNotIn('renderHeatmapTracker',note)
        code=note.split('```dataviewjs\n',1)[1].rsplit('\n```',1)[0]
        wrapper="new (Object.getPrototypeOf(async function(){}).constructor)('dv','app',"+json.dumps(code)+");"
        result=subprocess.run(['node','-e',wrapper],text=True,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        for forbidden in ('fetch(', 'app.vault.modify','app.vault.create','localStorage','require('):self.assertNotIn(forbidden,code)
