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
        self.assertIn('## AstrBot 同步',raw)

    def test_existing_sections_and_user_changes_require_reconfirmation(self):
        a=self.record()
        vault=self.root/'vault';vault.mkdir()
        note=vault/'2026-10-20.md'
        note.write_text('# 日记\n\n## AstrBot 同步\n\n旧手记\n\n## 下一节\n保留\n')
        state=self.state([a,self.record('two')])
        files,_=sync.plan(state,vault,'.')
        self.assertEqual(files[0]['after'].count('## AstrBot 同步'),1)
        self.assertLess(files[0]['after'].index(a['text']),files[0]['after'].index('## 下一节'))
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
        (profile/'life-sync.json').write_text(json.dumps({'enabled':True,'host':'owner@example.test','daily_directory':'Daily'}))
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

    def test_dashboard_publication_is_exact_bounded_and_private(self):
        from personal_asis.mac_content import save,validate
        data=dict(request_id='a'*32,title='选定摘要',content='本人确认的合成正文')
        self.assertFalse(save(data,self.root)['duplicate'])
        self.assertTrue(save(data,self.root)['duplicate'])
        request=dict(source='dashboard',operation='publish_summary',arguments={k:data[k] for k in ('title','content')})
        self.assertEqual(source_write.validate(request),request)
        with self.assertRaises(ValueError):validate(dict(data,extra='unauthorized'))
        self.assertEqual((self.root/'mac-content.json').stat().st_mode&0o777,0o600)
