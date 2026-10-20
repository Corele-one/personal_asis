from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout

from personal_asis.cli import main
from personal_asis.model_budget import ModelBudget
from personal_asis.pa1 import fixture
from personal_asis.work import WorkStore


class WorkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'work.sqlite3'
        self.now = 1000000
        self.store = WorkStore(self.path, clock=lambda: self.now)
        self.addCleanup(self.store.close)
        self.did = self.store.create('create', 'node', 'Synthetic goal', ['synthetic'])

    def run_claim(self, role='supervisor', parent=None, key='run', priority='foreground'):
        rid = self.store.enqueue(self.did, key, role, parent, priority)
        claim = self.store.claim('node', capacity=4, foreground_reserve=1)
        self.assertEqual(claim['id'], rid)
        return claim

    def test_idempotent_creation_conflicts_and_independent_identities(self):
        self.assertEqual(self.store.create('create', 'node', 'Synthetic goal', ['synthetic']), self.did)
        with self.assertRaisesRegex(ValueError, 'conflict'):
            self.store.create('create', 'node', 'Different goal', ['synthetic'])
        parent = self.run_claim()
        child = self.run_claim('research', parent['id'], 'research')
        self.assertEqual(self.store.enqueue(self.did, 'research', 'research', parent['id']), child['id'])
        self.assertEqual(len({self.did, parent['id'], parent['session'], child['id'], child['session']}), 5)
        with self.assertRaisesRegex(ValueError, 'conflict'):
            self.store.enqueue(self.did, 'research', 'life', parent['id'])

    def test_proactive_policy_requires_scoped_unexpired_confirmation_and_is_reversible(self):
        preview=self.store.prepare_proactive(self.did,request_id='p3-preview',interval_seconds=3600,
            expires=self.now+86400,token_budget=2000,max_runs=5,notify_when='attention')
        value=self.store.proactive(self.did)
        self.assertEqual(value['state'],'pending_confirmation')
        self.assertFalse(preview['scheduler_started'])
        self.assertEqual(value['scope']['sources'],['synthetic'])
        with self.assertRaisesRegex(ValueError,'confirmation_invalid'):
            self.store.control_proactive(self.did,'authorize',confirmation_token='wrong')
        active=self.store.control_proactive(self.did,'authorize',confirmation_token=preview['confirmation_token'])
        self.assertEqual(active['state'],'authorized')
        self.store.control(self.did,'pause')
        self.assertEqual(self.store.proactive(self.did)['state'],'paused')
        self.store.control(self.did,'resume')
        self.assertEqual(self.store.proactive(self.did)['state'],'paused')
        self.store.control_proactive(self.did,'resume')
        self.store.control_proactive(self.did,'cancel')
        self.assertEqual(self.store.proactive(self.did)['state'],'cancelled')

    def test_proactive_policy_rejects_unbounded_or_external_notifications(self):
        with self.assertRaisesRegex(ValueError,'invalid_proactive_policy'):
            self.store.prepare_proactive(self.did,request_id='p3-bad',interval_seconds=10,
                expires=self.now+86400,token_budget=2000,max_runs=5,notify_when='completion')
        with self.assertRaisesRegex(ValueError,'invalid_proactive_policy'):
            self.store.prepare_proactive(self.did,request_id='p3-bad2',interval_seconds=3600,
                expires=self.now+86400,token_budget=2000,max_runs=5,notify_when='completion',notify_channel='feishu')

    def test_proactive_confirmation_and_policy_expiry_are_enforced(self):
        preview=self.store.prepare_proactive(self.did,request_id='p3-expiry',interval_seconds=3600,
            expires=self.now+86400,token_budget=2000,max_runs=5,notify_when='none')
        self.now+=901
        with self.assertRaisesRegex(ValueError,'confirmation_invalid'):
            self.store.control_proactive(self.did,'authorize',confirmation_token=preview['confirmation_token'])
        # Re-create a fresh confirmation, activate, then let the policy expire.
        self.now+=1
        preview=self.store.prepare_proactive(self.did,request_id='p3-expiry-2',interval_seconds=3600,
            expires=self.now+86400,token_budget=2000,max_runs=5,notify_when='none')
        self.store.control_proactive(self.did,'authorize',confirmation_token=preview['confirmation_token'])
        self.now+=86401
        self.assertEqual(self.store.proactive(self.did)['state'],'expired')
        with self.assertRaisesRegex(ValueError,'cannot_resume'):
            self.store.control_proactive(self.did,'resume')

    def test_specialists_cannot_route_directly_or_cross_delegations(self):
        with self.assertRaisesRegex(ValueError, 'supervisor'):
            self.store.enqueue(self.did, 'unrouted', 'life')
        supervisor = self.run_claim()
        child = self.run_claim('research', supervisor['id'], 'research')
        with self.assertRaisesRegex(ValueError, 'supervisor'):
            self.store.enqueue(self.did, 'cross-specialist', 'career', child['id'])
        another = self.store.create('another', 'node', 'Other synthetic goal', ['synthetic'])
        with self.assertRaisesRegex(ValueError, 'supervisor'):
            self.store.enqueue(another, 'cross-delegation', 'life', supervisor['id'])
        with self.assertRaisesRegex(ValueError, 'children'):
            self.store.progress(supervisor['id'], 'node', supervisor['epoch'], {}, completed=True)

    def test_pause_all_children_fences_running_workers_and_resume_is_explicit(self):
        parent = self.run_claim()
        child = self.run_claim('life', parent['id'], 'life')
        self.store.progress(child['id'], 'node', child['epoch'], {'phase': 'evidence'})
        self.store.control(self.did, 'pause')
        self.assertTrue(all(r['state'] == 'paused' for r in self.store.view(self.did)['runs']))
        self.assertIsNone(self.store.claim('node', capacity=4, foreground_reserve=1))
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.store.progress(child['id'], 'node', child['epoch'], {'bad': 'late result'})
        self.store.control(self.did, 'resume')
        restored = self.store.claim('node', capacity=4, foreground_reserve=1)
        self.assertEqual(restored['id'], parent['id'])
        self.assertGreater(restored['epoch'], parent['epoch'])
        self.assertEqual(self.store.view(self.did)['runs'][1]['checkpoint'], {'phase': 'evidence'})

    def test_stop_run_cascades_but_next_run_allowed_cancel_is_terminal(self):
        parent = self.run_claim()
        self.run_claim('research', parent['id'], 'research')
        self.store.stop_run(parent['id'])
        self.assertTrue(all(r['state'] == 'stopped' for r in self.store.view(self.did)['runs']))
        self.store.enqueue(self.did, 'next')
        self.store.control(self.did, 'cancel')
        with self.assertRaisesRegex(ValueError, 'cannot_resume'):
            self.store.control(self.did, 'resume')
        with self.assertRaisesRegex(ValueError, 'not_active'):
            self.store.enqueue(self.did, 'after-cancel')
        # A repeated enqueue acknowledgement does not create another job.
        self.assertEqual(self.store.enqueue(self.did, 'run'), parent['id'])

    def test_reopen_checkpoint_original_node_only_and_fenced_lease(self):
        claim = self.run_claim()
        self.store.progress(claim['id'], 'node', claim['epoch'], {'next_step': 2})
        self.assertEqual(self.store.recover('node'), 0)
        self.now += 61
        with WorkStore(self.path, clock=lambda: self.now) as reopened:
            self.assertIsNone(reopened.claim('other-node', capacity=2, foreground_reserve=1))
            resumed = reopened.claim('node', capacity=2, foreground_reserve=1)
            self.assertEqual(resumed['id'], claim['id'])
            self.assertEqual(json.loads(resumed['checkpoint']), {'next_step': 2})
            with self.assertRaisesRegex(ValueError, 'stale'):
                self.store.heartbeat(claim['id'], 'node', claim['epoch'])
            reopened.progress(resumed['id'], 'node', resumed['epoch'], {'phase': 'done'}, completed=True)

    def test_unknown_execution_blocks_recovery_until_owner_inspects_no_replay(self):
        claim = self.run_claim()
        args = (claim['id'], 'node', claim['epoch'])
        self.store.begin_execution(*args, 'write-1', 'tool', {'synthetic': True}, resource='account-A')
        self.now += 61
        self.store.recover('node')
        self.assertIsNone(self.store.claim('node', capacity=2, foreground_reserve=1))
        self.assertEqual(self.store.executions(claim['id'])[0]['state'], 'unknown')
        self.store.resolve(claim['id'], 'write-1', 'done')
        resumed = self.store.claim('node', capacity=2, foreground_reserve=1)
        with self.assertRaisesRegex(ValueError, 'not_retryable_done'):
            self.store.begin_execution(claim['id'], 'node', resumed['epoch'], 'write-1', 'tool',
                                       {'synthetic': True}, resource='account-A')
        self.store.progress(claim['id'], 'node', resumed['epoch'], {'phase': 'inspected'}, completed=True)

    def test_account_queue_is_shared_and_unknown_lock_survives_cancel(self):
        first = self.run_claim()
        second = self.run_claim(key='second')
        a = (first['id'], 'node', first['epoch'])
        b = (second['id'], 'node', second['epoch'])
        self.store.begin_execution(*a, 'read-1', 'tool', {}, resource='account-A')
        with self.assertRaisesRegex(ValueError, 'resource_busy'):
            self.store.begin_execution(*b, 'read-2', 'tool', {}, resource='account-A')
        self.store.finish_execution(*a, 'read-1', 'done')
        self.store.begin_execution(*b, 'read-2', 'tool', {}, resource='account-A')
        self.store.stop_run(second['id'])
        with self.assertRaisesRegex(ValueError, 'resource_busy'):
            self.store.begin_execution(*a, 'read-3', 'tool', {}, resource='account-A')
        self.store.resolve(second['id'], 'read-2', 'rejected')
        self.store.begin_execution(*a, 'read-3', 'tool', {}, resource='account-A')

    def test_priority_and_reserved_foreground_capacity_across_workers(self):
        background = self.store.enqueue(self.did, 'bg', priority='background')
        foreground = self.store.enqueue(self.did, 'fg')
        self.assertEqual(self.store.claim('node', capacity=2, foreground_reserve=1)['id'], foreground)
        self.assertIsNone(self.store.claim('node', capacity=2, foreground_reserve=1))
        self.store.stop_run(foreground)
        self.assertEqual(self.store.claim('node', capacity=2, foreground_reserve=1)['id'], background)
        urgent = self.store.enqueue(self.did, 'fg2')
        self.assertEqual(self.store.claim('node', capacity=2, foreground_reserve=1)['id'], urgent)
        self.store.enqueue(self.did, 'fg3')
        self.assertIsNone(self.store.claim('node', capacity=2, foreground_reserve=1))

    def test_parallel_claims_and_combined_role_budget_are_transactional(self):
        for n in range(6):
            self.store.enqueue(self.did, f'run-{n}')
        def worker(n):
            with WorkStore(self.path, clock=lambda: self.now) as store:
                return store.claim('node', capacity=2, foreground_reserve=1)
        with ThreadPoolExecutor(max_workers=6) as pool:
            claims = [claim for claim in pool.map(worker, range(6)) if claim]
        self.assertEqual(len(claims), 2)
        self.assertEqual(len({c['id'] for c in claims}), 2)
        budget_path = self.path.with_name('budget.sqlite3')
        def reserve(n):
            ledger = ModelBudget(budget_path, 'node', daily=100, monthly=100)
            try:
                try:
                    ledger.reserve(f'role-{n}', f'fp-{n}', 60)
                    return True
                except ValueError as error:
                    self.assertEqual(str(error), 'model_budget_exhausted')
                    return False
            finally:
                ledger.close()
        # Create schema before concurrent reservation; this tests the transaction.
        ModelBudget(budget_path, 'node', daily=100, monthly=100).close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(reserve, range(2))), 1)

    def test_payload_expiry_and_purge_preserve_no_retry_markers_and_permissions(self):
        claim = self.run_claim()
        args = (claim['id'], 'node', claim['epoch'])
        self.store.begin_execution(*args, 'step', 'tool', {})
        self.store.finish_execution(*args, 'step', 'done')
        self.store.progress(*args, {'body': 'SYNTHETIC_RESULT'}, completed=True)
        self.now += 31*86400
        run = self.store.view(self.did)['runs'][0]
        self.assertIsNone(run['result'])
        self.assertIsNone(run['checkpoint'])
        self.assertEqual(self.store.executions(claim['id'])[0]['state'], 'done')
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        self.store.clean(self.did)
        self.assertEqual(self.store.view(self.did)['runs'][0]['state'], 'completed')

    def test_cli_records_only_no_automatic_work_and_rejects_new_source(self):
        (Path(self.tmp.name)/'fixture').mkdir()
        home = fixture(Path(self.tmp.name)/'fixture')
        output = io.StringIO()
        with redirect_stdout(output):
            rc = main(['--home', str(home), 'work', 'create', '--goal', 'Synthetic work',
                       '--source', 'synthetic', '--request-id', 'cli-create'])
        self.assertEqual(rc, 0)
        result = json.loads(output.getvalue())
        self.assertFalse(result['automatic_execution'])
        with WorkStore(home/'work.sqlite3') as store:
            self.assertEqual(store.view(result['delegation_id'])['runs'], [])
        output = io.StringIO()
        with redirect_stdout(output):
            rc = main(['--home', str(home), 'work', 'create', '--goal', 'Synthetic work',
                       '--source', 'new-source', '--request-id', 'cli-new'])
        self.assertEqual(rc, 1)
        self.assertIn('work_source_not_configured', output.getvalue())


if __name__ == '__main__':
    unittest.main()
