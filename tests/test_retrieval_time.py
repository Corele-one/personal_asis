from datetime import date
import json,os,tempfile,unittest
from personal_asis import pa1
from personal_asis.config import load_config
from personal_asis.index import Index
from personal_asis.retrieval import retrieve,ContextBundle
from personal_asis.retrieval_time import note_date,question_window


class DateTests(unittest.TestCase):
    def test_note_date_uses_explicit_metadata_not_touch_time_and_rejects_conflicts(self):
        self.assertEqual(note_date('2026-06-03.md','body'),('2026-06-03','filename'))
        self.assertEqual(note_date('note.md','---\ndate: 2026-10-14\n---\nbody'),('2026-10-14','frontmatter:date'))
        self.assertIsNone(note_date('note.md','happened on 2026-10-15')[0])
        self.assertIsNone(note_date('2026-06-03.md','---\ndate: 2026-10-14\n---\nbody')[0])
    def test_explicit_recency_and_visible_recent_default(self):
        today=date(2026,10,15)
        self.assertEqual(question_window('过去七天的日记',today)['start'],'2026-10-09')
        self.assertEqual(question_window('昨天的记录',today)['end'],'2026-10-14')
        self.assertEqual(question_window('本月的记录',today)['start'],'2026-10-01')
        self.assertEqual(question_window('上个月的记录',today)['end'],'2026-09-30')
        self.assertEqual(question_window('最近日记',today)['basis'],'recent_defaults_to_30_days')
        self.assertIsNone(question_window('解释 cache',today))


class RetrievalTimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=pa1.fixture(self.tmp.name)
        (self.home/'source/cache.md').write_text('---\ndate: 2026-06-03\n---\n# Old\n\ncache old statement\n')
        (self.home/'source/coherence.md').write_text('---\ndate: 2026-10-14\n---\n# New\n\ncache recent statement\n')
        with Index(self.home/'index.sqlite3',load_config(self.home/'sources.yaml')) as index:index.reconcile()
    def lookup(self,window=None):
        with Index(self.home/'index.sqlite3',load_config(self.home/'sources.yaml')) as index:
            return retrieve(index,'cache',provider='mimo',time_window=window)
    def test_explicit_time_scope_excludes_older_high_overlap_evidence(self):
        window=question_window('最近七天',date(2026,10,15))
        result=self.lookup(window)
        self.assertEqual([e['record_date'] for e in result['evidence']],['2026-10-14'])
        self.assertEqual(result['time_window'],window)
        self.assertEqual(len(self.lookup()['evidence']),2)
    def test_no_recent_evidence_does_not_fall_back_to_old_notes_or_file_mtime(self):
        os.utime(self.home/'source/cache.md',None)
        self.assertEqual(self.lookup(question_window('今天',date(2026,10,15)))['evidence'],[])
    def test_claimed_note_date_is_revalidated_before_reuse(self):
        evidence=self.lookup()['evidence'];evidence[0]['record_date']='2026-10-15'
        with self.assertRaisesRegex(ValueError,'note_date_mismatch'):
            ContextBundle('cache','mimo',evidence,'lexical').revalidate(self.home)
