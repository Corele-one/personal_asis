import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from personal_asis.life_store import LifeStore
from personal_asis import life_sync as sync
from personal_asis import source_write


class LifeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()
        self.store=LifeStore(self.root/'life.sqlite3')
        self.addCleanup(self.store.close)

    def record(self, message='one', at='2026-10-19T17:30:00+00:00'):
        return self.store.capture('owner-platform','owner',message,'合成日常记录',at)[0]

    def state(self, records):
        return dict(cursor=0,records={r['id']:r for r in records},applied={})

    def test_capture_idempotency_timezone_and_correction(self):
        a=self.record()
        self.assertEqual(a['day'],'2026-10-20')
        b=self.record()
        self.assertEqual(a,b)
        self.assertEqual(len(self.store.export()['changes']),1)
        b=self.store.organize(a['id'],kind='sleep_bed',summary='补记',occurred_at='2026-10-19T22:30:00+08:00')
        self.assertEqual(b['day'],'2026-10-19')
        self.assertEqual(b['text'],a['text'])
        self.assertEqual(b['revision'],2)
        with self.assertRaises(ValueError):self.record('naive','2026-10-20T12:00:00')

    def test_reminder_claimed_before_send_and_never_resent(self):
        a=self.record()
        self.store.organize(a['id'],kind='task',due_at='2026-10-20T08:00:00+08:00',origin='owner:FriendMessage:owner')
        self.assertEqual(len(self.store.claim_reminders('2026-10-20T09:00:00+08:00')),1)
        self.assertEqual(self.store.claim_reminders('2026-10-20T09:00:00+08:00'),[])
        self.store.reminder_result(a['id'],'unknown')
        self.store.organize(a['id'],kind='task',summary='修改摘要',due_at='2026-10-20T08:00:00+08:00',origin='owner:FriendMessage:owner')
        self.assertEqual(self.store.claim_reminders('2026-10-21T09:00:00+08:00'),[])

    def test_vault_preview_is_readonly_replay_and_date_move(self):
        a=self.record()
        state=self.state([a])
        vault=self.root/'vault';vault.mkdir()
        note=vault/'Daily/2026-10-20.md'
        files,receipts=sync.plan(state,vault,'Daily')
        self.assertFalse(note.exists())
        sync.apply(files)
        for rid,receipt in receipts:state['applied'][rid]=receipt
        raw=note.read_text()
        self.assertEqual(sync.plan(state,vault,'Daily'),([],[]))
        # Crash after file write but before recording the local receipt.
        fresh=self.state([a])
        self.assertEqual(sync.plan(fresh,vault,'Daily')[0],[])
        b=self.store.organize(a['id'],kind='health',occurred_at='2026-10-18T18:00:00+08:00')
        state['records'][a['id']]=b
        files,_=sync.plan(state,vault,'Daily')
        self.assertEqual(len(files),2)
        sync.apply(files)
        self.assertNotIn(a['text'],note.read_text())
        self.assertIn(a['text'],(vault/'Daily/2026-10-18.md').read_text())
        self.assertIn('### 📕Freewrite\n\n#### 聊天随记',raw)

    def test_existing_sections_and_user_changes_require_reconfirmation(self):
        a=self.record()
        vault=self.root/'vault';vault.mkdir()
        note=vault/'2026-10-20.md'
        note.write_text('# 日记\n\n## AstrBot 同步\n\n旧手记\n\n## 下一节\n保留\n')
        state=self.state([a,self.record('two')])
        files,_=sync.plan(state,vault,'.')
        self.assertEqual(files[0]['after'].count('## AstrBot 同步'),1)
        self.assertIn('## 下一节\n保留\n',files[0]['after'])
        self.assertGreater(files[0]['after'].index(a['text']),files[0]['after'].index('#### 聊天随记'))
        note.write_text('用户在预览后修改')
        with self.assertRaisesRegex(ValueError,'reconfirmation'):sync.apply(files)
        self.assertEqual(note.read_text(),'用户在预览后修改')

    def test_delete_scrubs_export_and_proposes_removal(self):
        a=self.record();state=self.state([a]);vault=self.root/'vault';vault.mkdir()
        files,receipts=sync.plan(state,vault,'.');sync.apply(files)
        for rid,receipt in receipts:state['applied'][rid]=receipt
        deleted=self.store.delete(a['id']);state['records'][a['id']]=deleted
        self.assertNotIn('合成日常记录',json.dumps(self.store.export(),ensure_ascii=False))
        files,_=sync.plan(state,vault,'.')
        self.assertNotIn('合成日常记录',files[0]['after'])

    def test_symlink_and_escaping_paths_denied(self):
        vault=self.root/'vault';vault.mkdir()
        (vault/'link').symlink_to(self.root)
        for rel in ('../escape.md','/tmp/escape.md','link/escape.md'):
            with self.assertRaises(ValueError):sync.safe_target(vault,rel)

    def test_noninteractive_startup_never_reads_pipe_or_writes_vault(self):
        profile=self.root/'profile';profile.mkdir()
        (profile/'life-sync.json').write_text('{"enabled":true}')
        with patch.object(sync,'pull') as pull, patch('builtins.input') as question:
            self.assertEqual(sync.startup(self.root,profile,interactive=False),'interactive_sync_required')
        pull.assert_not_called();question.assert_not_called()

    def test_write_plan_bound_to_exact_content_expiry_and_no_unknown_retry(self):
        request=dict(source='wucai',operation='append_diary',arguments={'content':'合成笔记'})
        value=source_write.prepare(request,self.root)
        with self.assertRaises(ValueError):source_write.execute(value['plan'],'wrong',self.root)
        with patch('personal_asis.reading_sources.Wucai.call',side_effect=TimeoutError) as upstream:
            with self.assertRaises(TimeoutError):source_write.execute(value['plan'],value['digest'],self.root)
            with self.assertRaises(Exception):source_write.execute(value['plan'],value['digest'],self.root)
            self.assertEqual(upstream.call_count,1)
        with self.assertRaises(ValueError):source_write.prepare(dict(request,operation='trash_article'),self.root)

    def test_startup_skip_then_confirm_preserves_pending_and_writes_once(self):
        import contextlib,io
        home=self.root/'home';home.mkdir()
        profile=self.root/'profile';profile.mkdir()
        vault=self.root/'vault';vault.mkdir()
        (home/'sources.yaml').write_text(json.dumps({'node_id':'mac','sources':[{'id':'life','root':str(vault),'policy':'private','index':True}]}))
        (profile/'life-sync.json').write_text(json.dumps({'enabled':True,'host':'owner@example.test','daily_directory':'Daily','journal_layout_mode':'plain'}))
        a=self.record()
        def fetch(config,state):state['records'][a['id']]=a;state['cursor']=1
        with patch.object(sync,'pull',side_effect=fetch),patch.object(sync,'publish_status'),contextlib.redirect_stdout(io.StringIO()) as shown:
            with patch('builtins.input',return_value='跳过'):
                self.assertEqual(sync.startup(home,profile,interactive=True),'skipped')
            self.assertFalse((vault/'Daily').exists())
            self.assertIn('合成日常记录',shown.getvalue())
            with patch('builtins.input',return_value='确认写入'):
                self.assertEqual(sync.startup(home,profile,interactive=True),'applied')
            raw=(vault/'Daily/2026-10-20.md').read_text()
            self.assertEqual(raw.count(a['text']),1)
            with patch('builtins.input') as ask:
                self.assertEqual(sync.startup(home,profile,interactive=True),'up_to_date')
                ask.assert_not_called()

    def configure_sync(self):
        home=self.root/'home';home.mkdir()
        profile=self.root/'profile';profile.mkdir()
        vault=self.root/'vault';vault.mkdir()
        (home/'sources.yaml').write_text(json.dumps({'node_id':'mac','sources':[
            {'id':'life','root':str(vault),'policy':'private','index':True}]}))
        (profile/'life-sync.json').write_text(json.dumps(
            {'enabled':True,'host':'owner@example.test','daily_directory':'Daily','journal_layout_mode':'plain'}))
        return home,profile,vault

    def legacy_block(self, r):
        return (f"<!-- astrbot:{r['id']}:start -->\n"
                f"### {r['occurred_at']} · {r['kind']}\n\n> {r['text']}\n"
                f"<!-- astrbot:{r['id']}:end -->\n")

    def test_sleep_filter_is_narrow_and_does_not_create_notes(self):
        vault=self.root/'vault';vault.mkdir()
        for kind,text,filtered in (
            ('sleep_bed','我准备睡觉了',True), ('sleep_wake','起床了',True),
            ('journal','晚安，睡觉了🌙',True), ('journal','我刚醒了！',True),
            ('journal','昨晚睡觉了',False), ('journal','晚安？',False),
            ('journal','今天睡不好，明天想调整学习安排。',False),
            ('health','睡眠问题让我很焦虑。',False), ('task','提醒我睡觉',True)):
            with self.subTest(kind=kind,text=text):
                r=dict(self.record(kind+text),kind=kind,text=text)
                files,changes=sync.plan(self.state([r]),vault,'Daily')
                self.assertEqual(bool(files),not filtered)
                self.assertEqual(bool(changes),not filtered)
        self.assertFalse((vault/'Daily').exists())

    def test_legacy_sleep_cleanup_is_previewed_and_preserves_handwritten_notes(self):
        r=dict(self.record(),kind='sleep_bed',text='晚安')
        state=self.state([r]);vault=self.root/'vault';(vault/'Daily').mkdir(parents=True)
        note=vault/'Daily/2026-10-20.md'
        original='# 今天\n\n## AstrBot 同步\n\n我的手记\n\n'+self.legacy_block(r)+'\n## 学习\n保留\n'
        note.write_text(original)
        state['applied'][r['id']]=dict(revision=r['revision'],path='Daily/2026-10-20.md')
        files,changes=sync.plan(state,vault,'Daily')
        self.assertEqual(note.read_text(),original)
        self.assertEqual(len(files),1)
        self.assertNotIn('晚安',files[0]['after'])
        self.assertIn('我的手记',files[0]['after'])
        self.assertIn('## 学习\n保留',files[0]['after'])
        sync.apply(files);state['applied'].update(changes)
        self.assertEqual(sync.plan(state,vault,'Daily'),([],[]))
        state['records'][r['id']]=dict(r,revision=r['revision']+1,kind='journal',text='完成了实验')
        files,_=sync.plan(state,vault,'Daily')
        self.assertIn('完成了实验',files[0]['after'])

    def test_sleep_reclassification_removes_old_day_without_creating_new_day(self):
        a=self.record();state=self.state([a]);vault=self.root/'vault';vault.mkdir()
        files,receipts=sync.plan(state,vault,'Daily');sync.apply(files);state['applied'].update(receipts)
        state['records'][a['id']]=self.store.organize(a['id'],kind='sleep_wake',occurred_at='2026-10-18T18:00:00+08:00')
        files,changes=sync.plan(state,vault,'Daily')
        self.assertEqual(len(files),1)
        self.assertEqual(files[0]['after'],'### 📕Freewrite\n\n')
        self.assertFalse((vault/'Daily/2026-10-18.md').exists())
        sync.apply(files);state['applied'].update(changes)
        self.assertEqual(sync.plan(state,vault,'Daily'),([],[]))

    def test_existing_journal_migrates_same_revision_to_freewrite_prose(self):
        r=self.record();state=self.state([r]);vault=self.root/'vault';vault.mkdir()
        note=vault/'2026-10-20.md';note.write_text('## AstrBot 同步\n\n'+self.legacy_block(r)+'\n## 手写\n保留\n')
        state['applied'][r['id']]=dict(revision=r['revision'],path=note.name)
        files,changes=sync.plan(state,vault,'.')
        self.assertIn('#### 聊天随记',files[0]['after'])
        self.assertIn(r['text'],files[0]['after'])
        self.assertNotIn('> [!note]',files[0]['after'])
        self.assertNotIn('2026-10-19T17:30',files[0]['after'])
        self.assertIn('## 手写\n保留',files[0]['after'])
        sync.apply(files);state['applied'].update(changes)
        self.assertEqual(sync.plan(state,vault,'.'),([],[]))
        task=dict(r,kind='task',summary='可修正的整理',due_at='2026-10-20T00:00:00+00:00',task_status='done')
        self.assertFalse(sync.projected(task))

    def test_damaged_identity_markers_stop_before_overwriting(self):
        r=self.record();vault=self.root/'vault';vault.mkdir()
        note=vault/'2026-10-20.md'
        for body in (f"<!-- astrbot:{r['id']}:start -->\n手动删除了结尾\n",
                     self.legacy_block(r)*2):
            note.write_text(body)
            with self.assertRaises(ValueError):sync.plan(self.state([r]),vault,'.')
            self.assertEqual(note.read_text(),body)

    def test_sleep_only_startup_and_receipt_recovery_never_ask_empty_approval(self):
        home,profile,vault=self.configure_sync()
        r=dict(self.record(),kind='sleep_bed',text='晚安')
        def fetch(config,state):state['records'][r['id']]=r
        with patch.object(sync,'pull',side_effect=fetch),patch.object(sync,'publish_status'),patch('builtins.input') as ask,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sync.startup(home,profile,interactive=True),'up_to_date')
            ask.assert_not_called()
        self.assertFalse((vault/'Daily').exists())
        r=self.record('journal');state=self.state([r]);files,_=sync.plan(state,vault,'Daily');sync.apply(files)
        (profile/'life-sync-cache.json').write_text(json.dumps(state))
        with patch.object(sync,'pull'),patch.object(sync,'publish_status'),patch('builtins.input') as ask,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sync.startup(home,profile,interactive=True),'up_to_date')
            ask.assert_not_called()
        receipt=json.loads((profile/'life-sync-cache.json').read_text())['applied'][r['id']]
        self.assertTrue(receipt['present'])

    def test_full_readable_preview_and_raw_diff_do_not_write_on_skip(self):
        home,profile,vault=self.configure_sync()
        r=dict(self.record(),text='第一行\n'+('合成长正文'*150)+'\n最后一行')
        def fetch(config,state):state['records'][r['id']]=r
        with patch.object(sync,'pull',side_effect=fetch),patch.object(sync,'publish_status'),patch('builtins.input',side_effect=['d','']),contextlib.redirect_stdout(io.StringIO()) as shown:
            self.assertEqual(sync.startup(home,profile,interactive=True),'skipped')
        readable,raw=shown.getvalue().split('--- 写入前')
        self.assertNotIn('<!-- astrbot:',readable)
        for line in r['text'].splitlines():self.assertIn(line,readable)
        self.assertNotIn(r['id'],raw)
        self.assertFalse((vault/'Daily').exists())

    def test_status_excludes_sleep_but_keeps_pending_legacy_cleanup_and_deletions(self):
        a=self.record();b=dict(self.record('sleep'),kind='sleep_bed',text='晚安')
        state=self.state([a,b])
        for old,expected in (({},1),({b['id']:dict(revision=b['revision'],path='Daily/2026-10-20.md')},2)):
            state['applied']=old
            with patch.object(sync.subprocess,'run') as send:
                sync.publish_status({'host':'owner@example.test'},state,{},home=self.root)
            value=json.loads(send.call_args.kwargs['input'])
            self.assertEqual(value['pending'],expected)
            self.assertEqual(value['applied'],0)
        state['applied']={a['id']:dict(revision=a['revision'],path='Daily/2026-10-20.md')}
        state['records'][a['id']]=self.store.delete(a['id'])
        with patch.object(sync.subprocess,'run') as send:
            sync.publish_status({'host':'owner@example.test'},state,{},home=self.root)
        self.assertEqual(json.loads(send.call_args.kwargs['input'])['pending'],1)

    def test_freewrite_selection_drops_conversation_controls_and_keeps_short_reflection(self):
        base=self.record()
        for text in ('life','/life','你好','life 你好','life list','/life sleep off','谢谢你！',
                     '10月26','10月26日','明天下午','14:00','明天下午提醒我核对合成结果',
                     '10月26日早上八点提醒我提交合成材料','开启睡觉提醒'):
            with self.subTest(text=text):self.assertFalse(sync.projected(dict(base,text=text)))
        for text in ('很迷茫','今天心情不错。','老师提醒我放慢节奏，我想了很多。','我想过得更开心，但不想敷衍自己。'):
            with self.subTest(text=text):self.assertTrue(sync.projected(dict(base,text=text)))
        self.assertFalse(sync.projected(dict(base,kind='task')))

    def test_freewrite_uses_existing_template_h4_and_preserves_footer_bytes(self):
        a=dict(self.record('one'),text='life 今天散步后重新想清楚了项目的取舍。',summary='合成模型摘要')
        b=dict(self.record('two'),text='life 也想给自己留一点休息的空间。')
        vault=self.root/'vault';vault.mkdir();note=vault/'2026-10-20.md'
        prefix='### 🧾Task\n- [ ] 原任务\n\n### 📕Freewrite\n\n手写的一段\n\n'
        suffix='### ⚛️Habits\n- [x] reading\n### 📖Learning\n原学习笔记\n\n![[On This Day.base]]'
        original=prefix+suffix;note.write_text(original)
        files,receipts=sync.plan(self.state([a,b]),vault,'.');after=files[0]['after']
        self.assertTrue(after.startswith(prefix));self.assertTrue(after.endswith(suffix))
        self.assertEqual(after.count('#### 聊天随记'),1)
        self.assertLess(after.index(a['text'][5:]),after.index('### ⚛️Habits'))
        for unwanted in ('> [!note]','合成模型摘要','life 今天','## 随手记'):
            self.assertNotIn(unwanted,after)
        self.assertEqual(note.read_text(),original)
        sync.apply(files)
        recovered=self.state([a,b])
        self.assertEqual(sync.plan(recovered,vault,'.')[0],[])
        recovered['applied'].update(receipts)
        self.assertEqual(sync.plan(recovered,vault,'.'),([],[]))

    def test_version_two_migration_filters_noise_and_moves_prose_into_freewrite(self):
        a=dict(self.record('kept'),text='life 想认真梳理一下最近的感受。')
        b=dict(self.record('greeting'),text='你好')
        state=self.state([a,b]);vault=self.root/'vault';vault.mkdir();note=vault/'2026-10-20.md'
        old=lambda r:self.legacy_block(r).replace('### '+r['occurred_at']+' · journal','> [!note] 01:30 · 随手记')
        template='### 📕Freewrite\n\n已有手记\n\n### ⚛️Habits\n保留习惯\n\n![[On This Day.base]]\n\n'
        original=template+'## 随手记\n\n'+old(a)+'\n'+old(b)
        note.write_text(original)
        for r in (a,b):state['applied'][r['id']]=dict(path=note.name,revision=r['revision'],projection=2,present=True)
        files,receipts=sync.plan(state,vault,'.');after=files[0]['after']
        self.assertNotIn('你好',after);self.assertNotIn('## 随手记',after)
        self.assertIn('已有手记',after);self.assertIn('保留习惯',after)
        self.assertLess(after.index('想认真'),after.index('### ⚛️Habits'))
        self.assertEqual(note.read_text(),original)
        sync.apply(files);state['applied'].update(receipts)
        self.assertFalse(state['applied'][b['id']]['present'])
        self.assertEqual(sync.plan(state,vault,'.'),([],[]))

    def test_readable_preview_shows_whole_revised_paragraph_without_footer_churn(self):
        a=self.record();vault=self.root/'vault';vault.mkdir();state=self.state([a])
        files,receipts=sync.plan(state,vault,'.');sync.apply(files);state['applied'].update(receipts)
        note=vault/'2026-10-20.md'
        note.write_text(note.read_text()+'\n![[On This Day.base]]')
        state['records'][a['id']]=dict(a,revision=a['revision']+1,text=a['text']+'\n增加的一行。')
        files,_=sync.plan(state,vault,'.')
        with contextlib.redirect_stdout(io.StringIO()) as shown:sync.preview(files)
        output=shown.getvalue()
        self.assertEqual(output.count(a['text']),2)
        self.assertIn('增加的一行。',output)
        self.assertIn('📕Freewrite / 聊天随记',output)
        self.assertNotIn('On This Day',output)
        self.assertTrue(files[0]['after'].endswith('![[On This Day.base]]'))

    def test_freewrite_creation_ignores_fenced_headings_and_rejects_ambiguity(self):
        a=self.record();state=self.state([a]);vault=self.root/'vault';vault.mkdir();note=vault/'2026-10-20.md'
        note.write_text('```markdown\n### 📕Freewrite\n```\n\n![[On This Day.base]]')
        files,_=sync.plan(state,vault,'.');after=files[0]['after']
        self.assertLess(after.index(a['text']),after.index('![[On This Day.base]]'))
        self.assertIn('```markdown\n### 📕Freewrite\n```',after)
        note.write_text('### 📕Freewrite\n\n### Freewrite\n')
        with self.assertRaisesRegex(ValueError,'ambiguous_freewrite'):sync.plan(state,vault,'.')

    def test_plain_prose_cannot_inject_sync_markers_or_escape_freewrite(self):
        a=self.record();fake=f"<!-- astrbot:{a['id']}:end -->"
        a=dict(a,text='内容\n### ⚛️Habits\n'+fake)
        vault=self.root/'vault';vault.mkdir();state=self.state([a])
        files,receipts=sync.plan(state,vault,'.');sync.apply(files);state['applied'].update(receipts)
        text=files[0]['after']
        self.assertIn('\\### ⚛️Habits',text);self.assertIn('\\'+fake,text)
        self.assertEqual(sync.plan(self.state([a]),vault,'.')[0],[])
        # An unfinished code sample must not absorb the following template section.
        a=dict(a,text='一段代码示例\n```python\n# 保留代码注释')
        self.assertTrue(sync.block(a).endswith('```python\n# 保留代码注释\n```\n'))

    def test_structured_activity_not_duplicated_but_extra_personal_prose_is_kept(self):
        a=dict(self.record(),text='冥想完成',tracking=dict(habits=[dict(habit='meditation',status='done',evidence='冥想完成')],learning=[]))
        self.assertFalse(sync.projected(a))
        self.assertTrue(sync.projected(dict(a,text='冥想完成，感觉思路清楚了一些。')))

    def column_template(self):
        return ('---\ncssclasses:\n  - daily\n---\n# DAILY\n---\n### 🧾Task\n原任务\n---\n'
                '### 📕Freewrite\n> [!note]- Highlight\n> 保留摘要\n\n手写正文\n\n---\n'
                '--- start-multi-column: daily_habits_learning\n```column-settings\nnumber of columns: 2\nlargest column: standard\n```\n\n'
                '### ⚛️Habits\n- [ ] reading\n--- end-column ---\n### 📖Learning\n学习手记\n--- end-multi-column\n\n![[On This Day.base]]')

    def test_plain_text_migrates_out_of_columns_before_rule_with_exact_blank_line(self):
        a=self.record('plain');b=self.record('second');vault=self.root/'vault';vault.mkdir()
        note=vault/'2026-10-20.md';original=self.column_template()
        original=original.replace('### ⚛️Habits','#### 聊天随记\n\n'+self.legacy_block(a)+'\n'+self.legacy_block(b)+'\n### ⚛️Habits')
        note.write_text(original);state=self.state([a,b])
        for r in (a,b):state['applied'][r['id']]=dict(path=note.name,revision=r['revision'],projection=3,present=True)
        files,receipts=sync.plan(state,vault,'.');after=files[0]['after']
        self.assertEqual(note.read_text(),original)
        self.assertNotIn('astrbot:',after)
        self.assertEqual(after.count('#### 聊天随记'),1)
        self.assertIn(b['text']+'\n\n---\n--- start-multi-column:',after)
        self.assertLess(after.index(a['text']),after.index('--- start-multi-column:'))
        for kept in ('手写正文','> [!note]- Highlight','```column-settings\nnumber of columns: 2\nlargest column: standard\n```',
                     '### ⚛️Habits\n- [ ] reading\n--- end-column ---\n### 📖Learning\n学习手记\n--- end-multi-column'):
            self.assertIn(kept,after)
        sync.apply(files);state['applied'].update(receipts)
        self.assertEqual(sync.plan(state,vault,'.'),([],[]))

    def test_markerless_receipts_preserve_unrelated_edits_and_refuse_changed_synced_text(self):
        a=self.record();vault=self.root/'vault';vault.mkdir();state=self.state([a])
        files,receipts=sync.plan(state,vault,'.');sync.apply(files);state['applied'].update(receipts)
        note=vault/'2026-10-20.md';note.write_text('额外手记\n\n'+note.read_text())
        state['records'][a['id']]=dict(a,revision=a['revision']+1,text='修订后的合成自述')
        files,receipts=sync.plan(state,vault,'.')
        self.assertTrue(files[0]['after'].startswith('额外手记\n\n'))
        sync.apply(files);state['applied'].update(receipts)
        note.write_text(note.read_text().replace('修订后的合成自述','本人手动改过的内容'))
        state['records'][a['id']]=dict(a,revision=a['revision']+2,text='新的上游内容')
        with self.assertRaisesRegex(ValueError,'journal_text_edited'):sync.plan(state,vault,'.')
        self.assertIn('本人手动改过',note.read_text())

    def test_markerless_identical_messages_share_one_paragraph_until_last_deleted(self):
        a=self.record('one');b=self.record('two');state=self.state([a,b]);vault=self.root/'vault';vault.mkdir()
        files,receipts=sync.plan(state,vault,'.');sync.apply(files);state['applied'].update(receipts)
        note=vault/'2026-10-20.md';self.assertEqual(note.read_text().count(a['text']),1)
        state['records'][a['id']]=self.store.delete(a['id'])
        files,receipts=sync.plan(state,vault,'.');sync.apply(files);state['applied'].update(receipts)
        self.assertEqual(note.read_text().count(b['text']),1)
        state['records'][b['id']]=self.store.delete(b['id'])
        files,_=sync.plan(state,vault,'.')
        self.assertNotIn(a['text'],files[0]['after'])

    def test_pending_receipt_recovers_partial_date_move_and_does_not_duplicate(self):
        from personal_asis import life_journal
        a=self.record();state=self.state([a]);vault=self.root/'vault';vault.mkdir()
        files,receipts=sync.plan(state,vault,'.');sync.apply(files);state['applied'].update(receipts)
        state['records'][a['id']]=self.store.organize(a['id'],kind='journal',occurred_at='2026-10-18T18:00:00+08:00')
        files,receipts=sync.plan(state,vault,'.')
        state['pending_projection']=life_journal.pending(state,files,receipts,{},vault)
        # Only the first file reached disk before the process was interrupted.
        sync.apply(files[:1])
        self.assertTrue(life_journal.recover(state,vault))
        files,receipts=sync.plan(state,vault,'.');sync.apply(files);state['applied'].update(receipts)
        self.assertEqual((vault/'2026-10-18.md').read_text().count(a['text']),1)
        self.assertNotIn(a['text'],(vault/'2026-10-20.md').read_text())
        self.assertEqual(sync.plan(state,vault,'.'),([],[]))
        # The reverse interruption: old file removed, new file not written yet.
        state['records'][a['id']]=self.store.organize(a['id'],kind='journal',occurred_at='2026-10-17T18:00:00+08:00')
        files,receipts=sync.plan(state,vault,'.')
        state['pending_projection']=life_journal.pending(state,files,receipts,{},vault)
        sync.apply(files[-1:]);life_journal.recover(state,vault)
        files,receipts=sync.plan(state,vault,'.');sync.apply(files);state['applied'].update(receipts)
        self.assertEqual((vault/'2026-10-17.md').read_text().count(a['text']),1)
        self.assertNotIn(a['text'],(vault/'2026-10-18.md').read_text())

    def test_pending_receipt_recovers_all_written_files_without_new_confirmation(self):
        from personal_asis import life_journal
        a=self.record();state=self.state([a]);vault=self.root/'vault';vault.mkdir()
        files,receipts=sync.plan(state,vault,'.')
        state['pending_projection']=life_journal.pending(state,files,receipts,{},vault)
        sync.apply(files);life_journal.recover(state,vault)
        self.assertEqual(sync.plan(state,vault,'.'),([],[]))

    def test_clean_does_not_remove_example_headings_inside_code(self):
        from personal_asis import life_freewrite
        snippet='```markdown\n#### 聊天随记\n\n### 示例下一节\n```\n'
        text=snippet+'\n#### 聊天随记\n\n### ⚛️Habits\n'
        cleaned=life_freewrite.clean(text)
        self.assertTrue(cleaned.startswith(snippet))
        self.assertEqual(cleaned.count('#### 聊天随记'),1)

    def test_paragraph_that_is_prefix_of_another_record_keeps_independent_receipts(self):
        a=dict(self.record('one'),text='合成自述\n还有第二行')
        b=dict(self.record('two'),text='合成自述')
        state=self.state([a,b]);vault=self.root/'vault';vault.mkdir()
        files,receipts=sync.plan(state,vault,'.');sync.apply(files);state['applied'].update(receipts)
        self.assertEqual(sync.plan(self.state([a,b]),vault,'.')[0],[])
        state['records'][b['id']]=dict(b,revision=b['revision']+1,text='单独修订短段落')
        files,_=sync.plan(state,vault,'.')
        self.assertIn(a['text'],files[0]['after']);self.assertIn('单独修订短段落',files[0]['after'])

    def test_untracked_filtered_messages_do_not_rebuild_already_current_prose(self):
        a=self.record();state=self.state([a]);vault=self.root/'vault';vault.mkdir()
        files,receipts=sync.plan(state,vault,'.');sync.apply(files);state['applied'].update(receipts)
        noise=dict(self.record('noise'),text='你好')
        state['records'][noise['id']]=noise
        self.assertEqual(sync.plan(state,vault,'.'),([],[]))

    def test_dashboard_publication_is_exact_bounded_and_private(self):
        from personal_asis.mac_content import save,validate
        data=dict(request_id='a'*32,title='选定摘要',content='本人确认的合成正文')
        self.assertFalse(save(data,self.root)['duplicate'])
        self.assertTrue(save(data,self.root)['duplicate'])
        request=dict(source='dashboard',operation='publish_summary',arguments={k:data[k] for k in ('title','content')})
        self.assertEqual(source_write.validate(request),request)
        with self.assertRaises(ValueError):validate(dict(data,extra='unauthorized'))
        self.assertEqual((self.root/'mac-content.json').stat().st_mode&0o777,0o600)
