import hashlib
import tempfile
from pathlib import Path
import unittest
from personal_asis.shared_store import SharedStore,identity
from personal_asis.shared_sources import document_bodies
from personal_asis.shared_query import KnowledgeQuery


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=SharedStore(Path(self.tmp.name).resolve()/'library.sqlite3','mac');self.addCleanup(self.store.close)
        self.query=KnowledgeQuery(self.store)

    def put(self,locator,text='合成复习内容',source='life',**kwargs):
        refs=[]
        for body in document_bodies(source,locator,Path(locator).stem,text,**kwargs):
            key=identity(source,locator,body['part'])
            version=self.store.put('reading' if source in ('wucai','xiaohongshu') else 'notes',key,body)
            refs.append((key,version))
        return refs

    def test_week_enumeration_does_not_depend_on_search_keywords(self):
        for i in range(2,9):self.put(f'Calendar/Journal/Daily/2026-11-{i:02}.md',f'第{i}日的独立主题')
        self.put('Calendar/Journal/Daily/2026-11-09.md')
        self.put('Note/undated.md')
        kwargs=dict(action='list',source='life',start='2026-11-02',end='2026-11-08',limit=3)
        first=self.query.query(**kwargs)
        self.assertEqual(first['coverage']['total_documents'],7)
        self.assertEqual(first['coverage']['undated_parts_excluded'],1)
        self.assertEqual(len(first['coverage']['days']),7)
        ids=[];page=first
        while True:
            ids.extend(r['id'] for r in page['results'])
            self.assertNotIn('text',page['results'][0])
            if not page['next_cursor']:break
            page=self.query.query(**kwargs,cursor=page['next_cursor'])
        self.assertEqual(len(set(ids)),7)
        self.assertTrue(page['coverage']['catalog_complete'])
        self.assertTrue(all(r['date_basis']=='source_document_date' for r in page['results']))

    def test_snapshot_change_and_filter_change_invalidate_cursor(self):
        self.put('2026-11-02.md');self.put('2026-11-03.md')
        page=self.query.query(action='list',source='life',limit=1)
        with self.assertRaisesRegex(ValueError,'snapshot_changed'):
            self.query.query(action='list',source='study',limit=1,cursor=page['next_cursor'])
        self.put('2026-11-04.md')
        with self.assertRaisesRegex(ValueError,'snapshot_changed'):
            self.query.query(action='list',source='life',limit=1,cursor=page['next_cursor'])

    def test_chinese_ranking_short_terms_and_account_filters(self):
        self.put('one.md','复习内容 电路'+(' 其他材料'*30))
        self.put('电路.md','电路')
        self.put('reading','电路资料',source='wucai',account='cn',acquired_at='2026-11-08T20:00:00+00:00')
        for term in ('电路','复习内容'):
            page=self.query.query(query=term)
            self.assertTrue(page['results'])
        page=self.query.query(query='电路',source='life')
        self.assertEqual(page['results'][0]['title'],'电路')
        page=self.query.query(action='list',source='wucai',account='cn',start='2026-11-09',end='2026-11-09')
        self.assertEqual(len(page['results']),1)
        self.assertEqual(page['results'][0]['date_basis'],'acquisition_date_not_reading_date')
        self.assertEqual(self.query.query(action='coverage',source='study')['coverage']['total_parts'],0)

    def test_multisegment_read_needs_all_actual_ranges_and_source_versions(self):
        refs=self.put('2026-11-02.md','甲'*12000+'乙'*100)
        receipts={}
        value=self.query.read('mac','notes',refs[0][0],receipts=receipts)
        self.assertEqual(len(value['body']['text']),6000)
        self.assertFalse(value['read_complete'])
        # Jumping to a later part cannot falsely complete the document.
        last=self.query.read('mac','notes',refs[1][0],receipts=receipts)
        self.assertFalse(last['read_complete'])
        args=last['next_arguments'];args.pop('action');args['key']=args.pop('record_id')
        done=self.query.read(**args,receipts=receipts)
        self.assertTrue(done['read_complete'])
        self.assertIsNone(done['next_arguments'])
        body=self.store.read('mac','notes',refs[0][0])['body']
        self.store.put('notes',refs[0][0],dict(body,text='新版本',hash=hashlib.sha256('新版本'.encode()).hexdigest()))
        with self.assertRaisesRegex(ValueError,'source_changed'):
            self.query.read('mac','notes',refs[0][0],expected_version=refs[0][1])
        with self.assertRaisesRegex(ValueError,'source_changed'):
            self.query.read('mac','notes',refs[1][0],receipts=receipts)

    def test_missing_parts_withdrawals_and_expiry_never_claim_full_read(self):
        refs=self.put('2026-11-02.md','甲'*12001)
        self.store.put('notes',refs[1][0],None)
        value=self.query.read('mac','notes',refs[0][0],offset=6000)
        self.assertFalse(value['read_complete']);self.assertFalse(value['source_parts_complete'])
        expired=self.put('expired.md',expires_at=1)[0]
        self.assertNotIn(expired[0],[r['id'] for r in self.query.query(action='list')['results']])
        with self.assertRaisesRegex(ValueError,'expired'):
            self.query.read('mac','notes',expired[0])

    def test_vps_capture_sources_remain_separate_and_date_uses_reported_day(self):
        from personal_asis.life_store import LifeStore
        from personal_asis.shared_sources import refresh_vps
        home=Path(self.tmp.name).resolve()/'vps';home.mkdir()
        life=LifeStore(home/'life.sqlite3')
        try:
            for kind in ('life_command','conversation','reminder'):
                life.capture('p','owner',kind,'这是合成'+kind,'2026-11-02T20:00:00+08:00',capture_source=kind)
        finally:life.close()
        vps=SharedStore(home/'shared.sqlite3','vps')
        try:
            refresh_vps(vps,home)
            for kind in ('life_command','conversation','reminder'):
                page=KnowledgeQuery(vps).query(action='list',source='astrbot',capture_source=kind,start='2026-11-02',end='2026-11-02')
                self.assertEqual(len(page['results']),1)
                self.assertEqual(page['results'][0]['capture_source'],kind)
                self.assertEqual(page['results'][0]['date_basis'],'reported_day')
        finally:vps.close()

    def test_failed_mixed_version_read_does_not_mark_unreturned_text_as_read(self):
        refs=self.put('2026-11-02.md','甲'*12001)
        other=self.store.read('mac','notes',refs[1][0])['body']
        self.store.put('notes',refs[1][0],dict(other,hash='b'*64))
        receipts={}
        with self.assertRaisesRegex(ValueError,'source_changed'):
            self.query.read('mac','notes',refs[0][0],receipts=receipts)
        self.assertEqual(receipts,{})

    def test_date_and_cursor_validation(self):
        for start,end in (('2026-11-01','2026-12-30'),('2026-02-30','2026-03-01'),('2026-11-03','2026-11-02')):
            with self.assertRaises(ValueError):self.query.query(action='list',start=start,end=end)
        with self.assertRaises(ValueError):self.query.query(query='')
        with self.assertRaises(ValueError):self.query.query(action='list',cursor='invalid')
