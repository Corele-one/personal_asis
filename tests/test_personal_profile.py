import copy
import json
from pathlib import Path
import tempfile
import unittest

from personal_asis.personal_profile import load, render, validate


def fixture(status='approved'):
    return dict(version=1, scope='personal_profile', status=status, prepared_on='2026-10-21',
                approved_on='2026-10-21' if status == 'approved' else None,
                facts=[dict(id='synthetic-study-plan', kind='document_plan', topic='learning',
                            statement='合成学习计划，不表示已执行。', brief=True,
                            citations=[dict(source_id='study', relative_path='Plan/synthetic.md', date=None,
                                            line_start=1, line_end=5, sha256='a'*64)])])


class PersonalProfileTests(unittest.TestCase):
    def test_draft_is_previewable_but_never_loads_as_agent_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'profile.json';p.write_text(json.dumps(fixture('draft')))
            self.assertIn('draft', render(fixture('draft')))
            with self.assertRaisesRegex(ValueError, 'approval_required'): load(p)
            p.write_text(json.dumps(fixture()))
            self.assertEqual(load(p), fixture())

    def test_source_boundaries_and_malformed_dates_are_rejected(self):
        for field,value in [('relative_path','/Users/synthetic/private.md'),('relative_path','Plan/../private.md'),
                            ('relative_path','Plan\\private.md'),('relative_path','Research/Health/private.md'),
                            ('relative_path','Other/private.md'),('source_id','unapproved'),('date',12)]:
            v=fixture();v['facts'][0]['citations'][0][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError): validate(v)
        v=fixture();v['approved_on']=None
        with self.assertRaises(ValueError): validate(v)

    def test_life_evidence_requires_exact_dated_journal_path(self):
        v=fixture();cite=v['facts'][0]['citations'][0]
        cite.update(source_id='life',date='2026-10-20',relative_path='Calendar/Journal/Daily/2026-10-20.md')
        self.assertEqual(validate(v),v)
        cite['relative_path']='Calendar/Journal/Daily/2026-10-19.md'
        with self.assertRaises(ValueError): validate(v)

    def test_brief_is_small_but_keeps_provenance_and_does_not_load_details(self):
        v=fixture();detail=copy.deepcopy(v['facts'][0]);detail.update(id='detail',statement='SYNTHETIC_DETAIL_NOT_PRELOADED',brief=False)
        v['facts'].append(detail)
        brief=render(v,brief=True)
        self.assertNotIn(detail['statement'],brief)
        self.assertIn('study/Plan/synthetic.md:1-5',brief)
        self.assertIn(detail['statement'],render(v))
        self.assertIn('不据此创建提醒',brief)

    def test_unbounded_or_unsourced_profile_cannot_become_memory(self):
        for change in ('no-evidence','duplicate','large-brief','unknown-field','more-brief-facts'):
            v=fixture()
            if change=='no-evidence':v['facts'][0]['citations']=[]
            elif change=='duplicate':v['facts'].append(copy.deepcopy(v['facts'][0]))
            elif change=='large-brief':
                v['facts'][0]['statement']='x'*500
                other=copy.deepcopy(v['facts'][0]);other['id']='second';v['facts'].append(other)
            elif change=='unknown-field':v['raw_notes']='forbidden'
            else:
                for i in range(1,5):
                    other=copy.deepcopy(v['facts'][0]);other['id']='item'+str(i);v['facts'].append(other)
            with self.subTest(change=change),self.assertRaises(ValueError): validate(v)

    def test_symlink_denied_and_loading_has_no_record_side_effects(self):
        from personal_asis.life_store import LifeStore
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);p=home/'profile.json';p.write_text(json.dumps(fixture()))
            link=home/'link.json';link.symlink_to(p)
            with self.assertRaises(ValueError):load(link)
            store=LifeStore(home/'life.sqlite3')
            try:
                load(p)
                self.assertEqual(store.export()['changes'],[])
                self.assertEqual(store.claim_reminders(),[])
            finally:store.close()
