import base64
import contextlib
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from personal_asis import life_images as images, life_image_sync as transfer, life_sync as sync
from personal_asis.life_store import LifeStore

# Valid 1x1 PNG, not a personal photograph.
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1sAAAAASUVORK5CYII=')


class LifeImageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.store = LifeStore(self.root/'vps/life.sqlite3')
        self.addCleanup(self.store.close)
        self.item = images.descriptor(PNG)
        images.write_bytes(self.store.path.parent/'images'/images.filename(self.item), PNG)
        self.record = self.store.capture('feishu', 'owner', 'image-message', '/life 今天的照片 [image]',
            '2026-11-05T20:00:00+08:00', images=[self.item])[0]
        self.state = dict(cursor=0, records={self.record['id']:self.record}, applied={})
        self.vault = self.root/'vault'
        self.vault.mkdir()
        self.profile = self.root/'profile'
        self.profile.mkdir()
        self.config = dict(enabled=True, host='owner@example.test', daily_directory='Daily', journal_layout_mode='plain')

    def fetch(self, config, state):
        state['records'] = self.state['records']

    def response(self, *args, **kwargs):
        self.assertEqual(args[0][-1], transfer.REMOTE)
        request = json.loads(kwargs['input'])
        return types.SimpleNamespace(returncode=0, stdout=images.export(self.store, request))

    def test_descriptors_are_bounded_and_do_not_contain_paths_or_urls(self):
        for invalid in ([dict(self.item, path='/secret')], [dict(self.item, sha256='../x')],
                        [dict(self.item,size=True)], [dict(self.item,extension='svg')], [self.item]*9):
            with self.assertRaises(ValueError):images.validate(invalid)
        with self.assertRaises(ValueError):images.descriptor(b'<svg></svg>')
        with self.assertRaises(ValueError):images.descriptor(PNG+b'x'*images.MAX_BYTES)
        self.assertEqual(set(self.item), {'sha256','size','extension'})

    def test_export_requires_live_record_and_matching_hash(self):
        self.assertEqual(images.export(self.store, dict(record_id=self.record['id'],sha256=self.item['sha256'])),PNG)
        for request in (dict(record_id=self.record['id'],sha256='f'*64),
                        dict(record_id=self.record['id'],sha256=self.item['sha256'],path='/tmp/a')):
            with self.assertRaises(ValueError):images.export(self.store, request)
        self.store.delete(self.record['id'])
        with self.assertRaises(ValueError):images.export(self.store,dict(record_id=self.record['id'],sha256=self.item['sha256']))
        self.assertFalse((self.store.path.parent/'images'/images.filename(self.item)).exists())
        self.assertNotIn('images',self.store.export()['changes'][0]['record'])

    def test_image_capture_replay_and_shared_blob_deletion(self):
        same, created = self.store.capture('feishu','owner','image-message',self.record['text'],images=[self.item])
        self.assertFalse(created)
        self.assertEqual(same,self.record)
        second = self.store.capture('feishu','owner','second','/life 另一张照片',images=[self.item])[0]
        self.store.delete(self.record['id'])
        self.assertEqual(images.export(self.store,dict(record_id=second['id'],sha256=self.item['sha256'])),PNG)
        with self.assertRaises(ValueError):
            self.store.capture('feishu','owner','ordinary','普通聊天',capture_source='conversation',images=[self.item])

    def test_preview_skip_confirm_replay_and_restore_missing_attachment(self):
        home=self.root/'home';home.mkdir()
        (home/'sources.yaml').write_text(json.dumps({'node_id':'mac','sources':[
            {'id':'life','root':str(self.vault),'policy':'private','index':True}]}))
        (self.profile/'life-sync.json').write_text(json.dumps(self.config))
        target=self.vault/images.vault_path(self.item,self.record,daily='Daily')
        with patch.object(sync,'pull',side_effect=self.fetch), patch.object(sync,'publish_status'), \
                patch.object(transfer.subprocess,'run',side_effect=self.response) as ssh, \
                contextlib.redirect_stdout(io.StringIO()) as shown:
            with patch('builtins.input',return_value='跳过'):
                self.assertEqual(sync.startup(home,self.profile,interactive=True),'skipped')
            self.assertFalse(target.exists())
            self.assertFalse((self.vault/'Daily').exists())
            self.assertIn(str(target),shown.getvalue())
            with patch('builtins.input',return_value='确认写入'):
                self.assertEqual(sync.startup(home,self.profile,interactive=True),'applied')
            self.assertEqual(target.read_bytes(),PNG)
            note=self.vault/'Daily/2026-11-05.md'
            embed=images.embed(self.record,0)
            self.assertEqual(note.read_text().count(embed),1)
            self.assertNotIn('[image]',note.read_text())
            self.assertEqual(target.stat().st_mode & 0o777,0o600)
            with patch('builtins.input') as prompt:
                self.assertEqual(sync.startup(home,self.profile,interactive=True),'up_to_date')
                prompt.assert_not_called()
            # A manually removed image is repaired only after another preview/approval.
            target.unlink()
            with patch('builtins.input',return_value='确认写入'):
                self.assertEqual(sync.startup(home,self.profile,interactive=True),'applied')
            self.assertEqual(target.read_bytes(),PNG)
            self.assertEqual(ssh.call_count,1)  # private cache survives skipped previews

    def test_corruption_exclusions_and_symlinks_stop_before_vault_write(self):
        with patch.object(transfer.subprocess,'run',side_effect=self.response):
            with self.assertRaisesRegex(ValueError,'excluded'):
                transfer.prepare(self.config,self.state,self.profile,self.vault,lambda p:False)
            pending=transfer.prepare(self.config,self.state,self.profile,self.vault,lambda p:True)
        images.write_bytes(pending[0]['cache'],PNG+b'corrupted')
        with self.assertRaisesRegex(ValueError,'cache_changed'):
            transfer.apply(pending,self.vault,lambda p:True)
        self.assertFalse(pending[0]['path'].exists())
        images.write_bytes(pending[0]['cache'],PNG)
        (self.vault/'Daily').symlink_to(self.root)
        with self.assertRaisesRegex(ValueError,'symlink'):
            transfer.apply(pending,self.vault,lambda p:True)

    def test_bad_remote_bytes_do_not_leave_a_cached_image_or_broken_note(self):
        with patch.object(transfer.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stdout=PNG+b'x')):
            with self.assertRaisesRegex(ValueError,'integrity'):
                transfer.prepare(self.config,self.state,self.profile,self.vault,lambda p:True)
        self.assertFalse((self.profile/'life-images'/images.filename(self.item)).exists())
        self.assertEqual(list(self.vault.iterdir()),[])

    def test_multi_image_prose_review_date_move_and_delete(self):
        from personal_asis import life_review
        second=images.descriptor(PNG+b'second')
        r=dict(self.record,images=[self.item,second],text='/life 今天的照片 [image] 第二张 [image]')
        self.state['records'][r['id']]=r
        files,receipts=sync.plan(self.state,self.vault,'Daily')
        body=files[0]['after']
        self.assertLess(body.index(images.embed(r,0)),body.index(images.embed(r,1)))
        _,parts=life_review.prepare(files,self.state)
        self.assertIn(images.embed(r,1),''.join(p['body'] for p in parts.values()))
        sync.apply(files);self.state['applied'].update(receipts)
        self.state['records'][r['id']]=dict(r,day='2026-11-04',occurred_at='2026-11-04T20:00:00+08:00',revision=2)
        files,receipts=sync.plan(self.state,self.vault,'Daily')
        self.assertEqual(len(files),2)
        sync.apply(files);self.state['applied'].update(receipts)
        self.state['records'][r['id']]=dict(r,deleted=True,text='',images=[],revision=3)
        files,_=sync.plan(self.state,self.vault,'Daily')
        self.assertTrue(all('![[' not in f['after'] for f in files))

    def test_picture_only_entry_survives_text_filter(self):
        r=dict(self.record,text='/life [image]')
        self.assertTrue(sync.projected(r))
        self.assertEqual(sync.block(r),images.embed(r,0)+'\n')
        self.assertFalse(sync.projected(dict(r,capture_source='conversation')))

    def test_recovered_image_migrates_removed_transport_marker_but_preserves_handwriting(self):
        old=dict(self.record)
        old.pop('images')
        self.state['records'][old['id']]=old
        files,receipts=sync.plan(self.state,self.vault,'Daily')
        sync.apply(files);self.state['applied'].update(receipts)
        # Legacy layout could put the image on a separate paragraph. Recreate
        # that old receipt, then the user's cleanup of the useless marker.
        note=self.vault/'Daily/2026-11-05.md'
        text=note.read_text().replace('今天的照片 [image]','今天的照片\n\n[image]')
        note.write_text(text)
        from personal_asis.life_journal import location
        body='今天的照片\n\n[image]\n'
        self.state['applied'][old['id']]['locations']=[location('Daily/2026-11-05.md',text,text.index(body),body)]
        note.write_text(text.replace('\n[image]\n','\n')+'\n额外手记\n')
        before=note.read_bytes()
        self.state['records'][old['id']]=dict(self.record,revision=old['revision']+1)
        files,receipts=sync.plan(self.state,self.vault,'Daily')
        self.assertEqual(note.read_bytes(),before)
        self.assertIn('额外手记',files[0]['after'])
        self.assertIn(images.embed(self.record,0),files[0]['after'])
        # Changes to the caption remain conflicts, even with a recovered photo.
        note.write_text(note.read_text().replace('今天的照片','我修改过的照片说明'))
        with self.assertRaisesRegex(ValueError,'journal_text_edited'):
            sync.plan(self.state,self.vault,'Daily')

    def test_assets_follow_existing_date_and_timestamp_convention_with_standalone_images(self):
        r=dict(self.record,text='/life 第一张照片 [image] 这里是第二张的说明 [image]',
               images=[self.item,images.descriptor(PNG+b'2')])
        images.bind_paths({r['id']:r})
        self.assertEqual(images.paths(r)[0],
            'Calendar/Journal/Daily/assets/2026-11-05/file-20261105200000000.png')
        body=sync.block(r)
        self.assertEqual(body,'第一张照片\n\n![[file-20261105200000000.png]]\n\n'
                             '这里是第二张的说明\n\n![[file-20261105200000001.png]]\n')
        self.assertNotIn(self.item['sha256'],body)

    def test_timestamp_collision_is_deterministic_and_different_images_have_different_targets(self):
        a=dict(self.record,id='a'*64)
        b=dict(self.record,id='b'*64,images=[images.descriptor(PNG+b'other')])
        records={b['id']:b,a['id']:a}
        images.bind_paths(records,'Daily')
        self.assertNotEqual(images.paths(a),images.paths(b))
        first={k:images.paths(r)[:] for k,r in records.items()}
        images.bind_paths(records,'Daily')
        self.assertEqual(first,{k:images.paths(r) for k,r in records.items()})

    def test_long_prose_breaks_at_clauses_without_rewriting_words_and_code_stays_whole(self):
        text=('今天复习时遇到了几个问题，我把不清楚的地方都记了下来。[奋斗]'*5
              +'另外我也想调整一下接下来的安排，给散步和休息留一点时间。'*4)
        body=sync.block(dict(self.record,text='/life '+text,images=[]))
        self.assertGreaterEqual(len(body.split('\n\n')),2)
        self.assertLessEqual(max(map(len,body.split('\n\n'))),180)
        self.assertEqual(''.join(body.split()),''.join(text.split()))
        code='```python\nvalue = "'+text+'"\n\nprint(value)\n```'
        self.assertEqual(sync.block(dict(self.record,text='/life '+code,images=[])),code+'\n')

    def test_legacy_hash_embed_is_previewed_for_migration_without_changing_note(self):
        from personal_asis.life_journal import location
        path=self.vault/'Daily/2026-11-05.md';path.parent.mkdir()
        old_body='今天的照片 ![[Attachments/pi-sync/'+images.filename(self.item)+']]\n'
        before='### 📕Freewrite\n\n#### 照片\n\n'+old_body+'\n手写补充\n\n---\n'
        path.write_text(before)
        self.state['applied'][self.record['id']]=dict(revision=self.record['revision'],projection=4,
            path='Daily/2026-11-05.md',present=True,
            locations=[location('Daily/2026-11-05.md',before,before.index(old_body),old_body)])
        files,receipts=sync.plan(self.state,self.vault,'Daily')
        self.assertEqual(path.read_text(),before)
        self.assertIn('手写补充',files[0]['after'])
        self.assertNotIn('Attachments/pi-sync',files[0]['after'])
        self.assertIn('\n\n![[file-',files[0]['after'])
        sync.apply(files);self.state['applied'].update(receipts)
        self.assertEqual(sync.plan(self.state,self.vault,'Daily'),([],[]))

    def test_conversational_transition_can_begin_a_new_paragraph_without_punctuation(self):
        text='今天的课程和实验安排得很满我把几个不太明白的问题记了下来准备找同学一起讨论[奋斗]换个角度想，能发现问题也是收获，接下来想先把基础概念梳理清楚再做练习，不急着把所有事情都堆到一天。'
        body=sync.block(dict(self.record,text='/life '+text,images=[]))
        self.assertIn('[奋斗]\n\n换个角度想',body)
        self.assertEqual(''.join(body.split()),text)


if __name__=='__main__':
    unittest.main()
