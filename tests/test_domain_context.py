"""Synthetic-only tests of explicit goals, revocation, and paid-session replay."""

import contextlib
import io
import json
import shutil
import tempfile
import unittest

from personal_asis import pa1
from personal_asis.agent import execute
from personal_asis.cli import main
from personal_asis.domain_context import DomainContexts, REVIEW_SECONDS
from personal_asis.runtime_adapter import PI_DIR
from personal_asis.work import WorkStore
from test_agent import FakeTools


class DomainFixture(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home=pa1.fixture(self.tmp.name)
        pa1.configure(self.home,'synthetic-model',True,synthetic_only=False)


class DomainContextTests(DomainFixture):
    def test_local_default_is_not_model_authority_and_list_omits_body(self):
        before=(self.home/'sources.yaml').read_bytes()
        with DomainContexts(self.home) as store:
            record=store.set('research','SYNTHETIC_RESEARCH_GOAL','SYNTHETIC_CONSTRAINT',
                             ['synthetic'],'set-one')
            self.assertFalse(record['model_allowed'])
            self.assertEqual(store.show('research')['revision'],1)
            self.assertNotIn('SYNTHETIC',json.dumps(store.list()))
            with self.assertRaisesRegex(ValueError,'not_approved'):
                store.for_model('research',['synthetic'])
        self.assertEqual((self.home/'sources.yaml').read_bytes(),before)
        self.assertEqual((self.home/'work.sqlite3').stat().st_mode & 0o777,0o600)

    def test_replayed_updates_cannot_revert_newer_goal_or_delete_replacement(self):
        with DomainContexts(self.home) as store:
            store.set('research','OLD','',['synthetic'],'first',allow_model=True)
            store.set('research','NEW','',['synthetic'],'second',allow_model=True)
            replay=store.set('research','OLD','',['synthetic'],'first',allow_model=True)
            self.assertEqual(replay['goal'],'NEW')
            self.assertTrue(replay['replayed_update'])
            with self.assertRaisesRegex(ValueError,'request_conflict'):
                store.set('research','CHANGED','',['synthetic'],'first',allow_model=True)
            store.forget('research','delete')
            store.set('research','REPLACEMENT','',['synthetic'],'third',allow_model=True)
            self.assertEqual(store.forget('research','delete')['goal'],'REPLACEMENT')
            self.assertEqual(store.show('research')['revision'],4)

    def test_scope_and_explicit_credential_exclusions(self):
        with DomainContexts(self.home) as store:
            for goal in ('password: syntheticsecret','-----BEGIN PRIVATE KEY-----'):
                with self.assertRaisesRegex(ValueError,'credential_input'):
                    store.set('research',goal,'',['synthetic'],'invalid')
            with self.assertRaisesRegex(ValueError,'explicit_sources'):
                store.set('research','goal','',[],'invalid')
            with self.assertRaisesRegex(ValueError,'not_configured'):
                store.set('research','goal','',['other'],'invalid')
            store.set('research','goal','',['synthetic'],'valid',allow_model=True)
            with self.assertRaisesRegex(ValueError,'scope_denied'):
                store.for_model('research',['synthetic','other'])
            with self.assertRaisesRegex(ValueError,'unknown_domain'):
                store.show('other')

    def test_review_due_requires_owner_reconfirmation(self):
        now=[1000.0]
        with DomainContexts(self.home,lambda:now[0]) as store:
            store.set('life','SYNTHETIC_LIFE','',['synthetic'],'one',allow_model=True)
            now[0]+=REVIEW_SECONDS
            self.assertTrue(store.show('life')['needs_review'])
            with self.assertRaisesRegex(ValueError,'needs_review'):
                store.for_model('life',['synthetic'])
            # A replay is not a fresh confirmation.
            store.set('life','SYNTHETIC_LIFE','',['synthetic'],'one',allow_model=True)
            self.assertTrue(store.show('life')['needs_review'])
            store.set('life','SYNTHETIC_LIFE','',['synthetic'],'two',allow_model=True)
            self.assertFalse(store.show('life')['needs_review'])

    def test_root_change_and_provider_revocation_prevent_model_use(self):
        pa1.authorize_current_files(self.home,['synthetic'])
        with DomainContexts(self.home) as store:
            store.set('research','goal','',['synthetic'],'one',allow_model=True)
            original=(self.home/'sources.yaml').read_bytes()
            config=json.loads(original)
            config['sources'][0]['root']=str(self.home/'replacement')
            (self.home/'replacement').mkdir()
            (self.home/'sources.yaml').write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError,'permission_changed'):
                store.for_model('research',['synthetic'])
            (self.home/'sources.yaml').write_bytes(original)
            pa1.revoke_sources(self.home,['synthetic'])
            with self.assertRaisesRegex(ValueError,'permission_changed'):
                store.for_model('research',['synthetic'])

    def test_forget_removes_current_body_and_retains_only_update_fingerprints(self):
        with DomainContexts(self.home) as store:
            store.set('career','SYNTHETIC_FORGET_ME','SYNTHETIC_CONSTRAINT',
                      ['synthetic'],'one',allow_model=True)
            result=store.forget('career','forget')
            self.assertIsNone(result['goal'])
            self.assertEqual(result['roots'],{})
            self.assertTrue(result['deleted'])
            rows=[dict(row) for row in store.db.execute('SELECT * FROM domain_context_updates')]
            self.assertNotIn('SYNTHETIC_FORGET_ME',json.dumps(rows))
            with self.assertRaisesRegex(ValueError,'not_approved'):
                store.for_model('career',['synthetic'])

    def test_cli_can_set_show_list_forget_without_model_calls(self):
        def call(*args):
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                code=main(['--home',str(self.home),'domain',*args])
            self.assertEqual(code,0,output.getvalue())
            return json.loads(output.getvalue())
        result=call('set','--domain','research','--goal','SYNTHETIC_CLI_GOAL',
                    '--source','synthetic','--request-id','cli-set')
        self.assertFalse(result['model_allowed'])
        self.assertEqual(call('show','--domain','research')['goal'],'SYNTHETIC_CLI_GOAL')
        self.assertFalse(call('list')['automatic_execution'])
        self.assertTrue(call('forget','--domain','research','--request-id','cli-forget')['deleted'])


@unittest.skipUnless(shutil.which('node') and (PI_DIR/'node_modules/@earendil-works/pi-agent-core').is_dir(),
                     'optional Pi packages and Node required')
class DomainAgentTests(DomainFixture):
    def approve(self,domain='research',goal='SYNTHETIC_RESEARCH_GOAL',key='approved'):
        with DomainContexts(self.home) as store:
            return store.set(domain,goal,'SYNTHETIC_LIMIT',['synthetic'],key,allow_model=True)

    def test_only_explicit_selected_domain_enters_model_and_resume_is_stable(self):
        self.approve()
        self.approve('life','SYNTHETIC_OTHER_DOMAIN_SECRET','life')
        first=FakeTools()
        partial=execute(self.home,'cache','domain-run',['synthetic'],domain='research',
                        provider=first,step_limit=1)
        self.assertEqual(partial['status'],'checkpointed')
        wire=json.dumps(first.calls)
        self.assertIn('SYNTHETIC_RESEARCH_GOAL',wire)
        self.assertNotIn('SYNTHETIC_OTHER_DOMAIN_SECRET',wire)
        self.assertNotIn(str(self.home),wire)
        second=FakeTools()
        final=execute(self.home,None,'domain-run',resume=True,provider=second)
        self.assertEqual(final['status'],'completed')
        self.assertEqual(final['result']['usage']['total_tokens'],180)
        self.assertEqual(len(second.calls),1)
        self.assertIn('SYNTHETIC_RESEARCH_GOAL',json.dumps(second.calls))
        with self.assertRaisesRegex(ValueError,'saved_domain_context'):
            execute(self.home,None,'domain-run',resume=True,provider=FakeTools(),domain='life')
        with self.assertRaisesRegex(ValueError,'domain_conflict'):
            execute(self.home,'cache','domain-run',['synthetic'],provider=FakeTools(),domain='life')

    def test_local_only_record_prevents_any_model_call(self):
        with DomainContexts(self.home) as store:
            store.set('research','LOCAL_ONLY','',['synthetic'],'local')
        provider=FakeTools()
        with self.assertRaisesRegex(ValueError,'not_approved'):
            execute(self.home,'cache','local',['synthetic'],domain='research',provider=provider)
        self.assertEqual(provider.calls,[])

    def test_update_and_forget_purge_matching_sessions_preserve_other_work_and_billing(self):
        self.approve()
        self.approve('life','SYNTHETIC_OTHER_DOMAIN_SECRET','life')
        selected=execute(self.home,'cache','selected',['synthetic'],domain='research',provider=FakeTools())
        other=execute(self.home,'cache','other',['synthetic'],domain='life',provider=FakeTools())
        plain=execute(self.home,'cache','plain',['synthetic'],provider=FakeTools())
        result=self.approve(goal='REPLACEMENT',key='update')
        self.assertEqual(result['sessions_cleared'],1)
        with WorkStore(self.home/'work.sqlite3') as work:
            self.assertIsNone(work._run(selected['run_id'])['result'])
            self.assertEqual(len(work.executions(selected['run_id'])),3)
            self.assertIsNotNone(work._run(other['run_id'])['result'])
            self.assertIsNotNone(work._run(plain['run_id'])['result'])
        provider=FakeTools()
        with self.assertRaisesRegex(ValueError,'expired_or_cleared'):
            execute(self.home,None,'selected',resume=True,provider=provider)
        self.assertEqual(provider.calls,[])
        with DomainContexts(self.home) as store:
            self.assertEqual(store.forget('life','forget')['sessions_cleared'],1)
        with contextlib.closing(pa1.budget(self.home,'mac',pa1.settings(self.home))) as ledger:
            self.assertEqual(ledger.status()['daily_tokens'],540)

    def test_revocation_during_call_settles_actual_usage_and_does_not_restore_body(self):
        self.approve()
        def revoke():
            with DomainContexts(self.home) as store:
                store.forget('research','revoke-in-flight')
        provider=FakeTools(hook=revoke)
        with self.assertRaisesRegex(ValueError,'not_approved'):
            execute(self.home,'cache','inflight',['synthetic'],domain='research',provider=provider)
        self.assertEqual(len(provider.calls),1)
        with contextlib.closing(pa1.budget(self.home,'mac',pa1.settings(self.home))) as ledger:
            self.assertEqual(ledger.status()['daily_tokens'],60)
            self.assertEqual(ledger.status()['unresolved_calls'],0)
        with WorkStore(self.home/'work.sqlite3') as work:
            self.assertIsNone(work.db.execute('SELECT payload FROM agent_sessions').fetchone()[0])
        with self.assertRaisesRegex(ValueError,'expired_or_cleared'):
            execute(self.home,None,'inflight',resume=True,provider=FakeTools())
