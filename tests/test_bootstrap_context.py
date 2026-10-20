import copy
import json
from pathlib import Path
import tempfile
import unittest
from personal_asis.bootstrap_context import validate,load,render


def fixture():
    return dict(version=1,initialized_on='2026-10-20',window=['2026-09-21','2026-10-20'],scope='life_baseline',facts=[
        dict(id='synthetic',kind='historical_task',topic='daily_affairs',statement='合成的历史候选，时间未知，不创建提醒。',citations=[dict(source_id='life',relative_path='Calendar/Journal/Daily/2026-10-20.md',date='2026-10-20',line_start=19,line_end=19,sha256='a'*64)])],coverage=dict(daily_files=29,missing_days=['2026-09-22'],sleep_times_available=False,reminders_created=0))


class BootstrapTests(unittest.TestCase):
    def test_render_retains_dates_provenance_and_not_current_task(self):
        text=render(fixture())
        self.assertIn('historical_task',text)
        self.assertIn('不是新收到的消息',text)
        self.assertIn('不能计算实际睡眠',text)
        self.assertIn('2026-10-20.md:19',text)

    def test_out_of_scope_sources_dates_and_paths_rejected(self):
        for field,value in [('source_id','study'),('date','2026-08-01'),('relative_path','../../private.md')]:
            data=fixture();data['facts'][0]['citations'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):validate(data)

    def test_evidence_and_strict_bounded_schema_required(self):
        for change in ('no_evidence','unknown_kind','extra_field','reminder','large'):
            data=fixture()
            if change=='no_evidence':data['facts'][0]['citations']=[]
            if change=='unknown_kind':data['facts'][0]['kind']='confirmed_current_task'
            if change=='extra_field':data['raw_notes']='forbidden'
            if change=='reminder':data['coverage']['reminders_created']=1
            if change=='large':data['facts'][0]['statement']='x'*1001
            with self.subTest(change=change),self.assertRaises(ValueError):validate(data)

    def test_loading_baseline_never_creates_life_events_or_reminders(self):
        from personal_asis.life_store import LifeStore
        from personal_asis.dashboard import snapshot
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp).resolve();path=home/'bootstrap.json';path.write_text(json.dumps(fixture()))
            store=LifeStore(home/'life.sqlite3')
            self.assertEqual(load(path),fixture())
            self.assertEqual(store.export()['changes'],[])
            self.assertEqual(store.claim_reminders(),[])
            store.close()
            value=snapshot(home)
            self.assertEqual(len(value['life_baseline']['facts']),1)
            self.assertEqual(value['astrbot']['records'],[])
            other=home/'link.json';other.symlink_to(path)
            with self.assertRaises(ValueError):load(other)

    def test_mac_profile_references_context_without_loading_its_body(self):
        from personal_asis.native_sources import prepare
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();home=root/'home';home.mkdir();profile=root/'profile';profile.mkdir()
            (home/'sources.yaml').write_text(json.dumps({'node_id':'mac','sources':[{'id':'study','root':str(root/'study'),'index':True}]}))
            (profile/'knowledge-context.md').write_text('SYNTHETIC_PRIVATE_CONTEXT_NOT_AUTOINJECTED')
            prepare(home,profile)
            context=(profile/'personal-sources.md').read_text()
            self.assertIn('knowledge-context.md',context)
            self.assertNotIn('SYNTHETIC_PRIVATE_CONTEXT_NOT_AUTOINJECTED',context)
