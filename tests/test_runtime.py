import json
from pathlib import Path
import shutil
import tempfile
import unittest

from personal_asis.model_budget import ModelBudget
from personal_asis.runtime_adapter import PI_DIR, run_pi
from personal_asis.runtime_validation import SyntheticHost, TOOLS, tool_reply, validate
from personal_asis.work import WorkStore


PI_INSTALLED = bool(shutil.which('node') and (PI_DIR/'node_modules/@earendil-works/pi-agent-core').is_dir())


class RuntimeGatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.work = WorkStore(self.root/'work.sqlite3')
        self.addCleanup(self.work.close)
        self.ledger = ModelBudget(self.root/'budget.sqlite3', 'synthetic-node', daily=1000, monthly=1000)
        self.addCleanup(self.ledger.close)
        self.did = self.work.create('trial', 'synthetic-node', 'Synthetic cache trial', ['synthetic'])
        self.parent = self.work.enqueue(self.did, 'supervisor')
        self.work.enqueue(self.did, 'research', 'research', self.parent)
        self.work.claim('synthetic-node', capacity=2, foreground_reserve=1)
        self.claim = self.work.claim('synthetic-node', capacity=2, foreground_reserve=1)
        self.answer = 'Synthetic evidence [E1]; E2 is summary_only.'
        self.replies = [tool_reply('lookup', 'lookup-1', 'cache'),
                        {'content': [{'type': 'text', 'text': self.answer}], 'stopReason': 'stop'}]

    def host(self, after_model=None):
        return SyntheticHost(self.work, self.claim, self.ledger, self.root, self.replies, after_model)

    def test_unregistered_shell_network_external_write_and_changed_capability_rejected(self):
        host = self.host()
        for name in ('shell', 'network', 'send_mail', 'candidate_tool'):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'not_registered'):
                host.tool({'name': name, 'args': {'value': 'synthetic'}, 'callId': name})
        host.approved['lookup'] = 'unapproved-new-version'
        with self.assertRaisesRegex(ValueError, 'version_changed'):
            host.tool({'name': 'lookup', 'args': {'value': 'cache'}, 'callId': 'lookup'})
        self.assertEqual(self.work.executions(self.claim['id']), [])

    def test_gateway_filters_private_bodies_titles_paths_and_reports_partial_coverage(self):
        result = self.host().tool({'name': 'lookup', 'args': {'value': 'cache'}, 'callId': 'lookup'})
        serialized = json.dumps(result)
        self.assertNotIn('PRIVATE_', serialized)
        self.assertNotIn('UNGRANTED_', serialized)
        self.assertEqual(result['coverage'], 'partial_synthetic_fixture')
        self.assertEqual(result['evidence'][1]['coverage'], 'summary_only')

    def test_fixed_artifact_does_not_follow_existing_symlink_or_accept_raw_path(self):
        host = self.host()
        host.tool({'name': 'lookup', 'args': {'value': 'cache'}, 'callId': 'lookup'})
        with self.assertRaisesRegex(ValueError, 'arguments'):
            host.tool({'name': 'artifact', 'args': {'value': self.answer, 'path': '../escape'}, 'callId': 'bad-path'})
        outside = self.root/'original.txt'
        outside.write_text('SYNTHETIC_SOURCE_UNCHANGED')
        (self.root/'result.txt').symlink_to(outside)
        with self.assertRaises(OSError):
            host.tool({'name': 'artifact', 'args': {'value': self.answer}, 'callId': 'artifact'})
        self.assertEqual(outside.read_text(), 'SYNTHETIC_SOURCE_UNCHANGED')
        self.assertEqual(self.work.executions(self.claim['id'])[-1]['state'], 'unknown')

    def test_policy_revocation_after_model_call_suppresses_reply_and_retains_unknown_budget(self):
        host = self.host(after_model=lambda host: setattr(host, 'revoked', True))
        with self.assertRaisesRegex(ValueError, 'revoked'):
            host('model', {'turn': 1, 'messages': []})
        self.assertEqual(self.ledger.status()['unresolved_calls'], 1)
        self.assertEqual(self.work.executions(self.claim['id'])[0]['state'], 'unknown')
        with self.assertRaisesRegex(ValueError, 'revoked'):
            host('done', {'messages': []})

    def test_pause_while_model_inflight_discards_late_result_and_no_next_step(self):
        host = self.host(after_model=lambda host: self.work.control(self.did, 'pause'))
        with self.assertRaisesRegex(ValueError, 'stale'):
            host('model', {'turn': 1, 'messages': []})
        self.assertEqual(self.work.executions(self.claim['id'])[0]['state'], 'unknown')
        self.assertEqual(self.ledger.status()['unresolved_calls'], 1)
        self.work.control(self.did, 'resume')
        # Supervisor can resume; the unknown child cannot start another model call.
        resumed = self.work.claim('synthetic-node', capacity=2, foreground_reserve=1)
        self.assertEqual(resumed['id'], self.parent)
        self.assertIsNone(self.work.claim('synthetic-node', capacity=2, foreground_reserve=1))

    def test_exhausted_budget_stops_before_provider_is_entered(self):
        self.ledger.reserve('existing-role', 'synthetic', 1000)
        host = self.host()
        with self.assertRaisesRegex(ValueError, 'budget_exhausted'):
            host('model', {'turn': 1, 'messages': []})
        self.assertEqual(host.model_inputs, [])
        self.assertEqual(self.work.executions(self.claim['id'])[0]['state'], 'rejected')

    def test_missing_optional_runtime_reports_clear_error(self):
        with self.assertRaisesRegex(ValueError, 'not_installed'):
            run_pi('Synthetic', [], 'session', self.host(), runtime_dir=self.root/'missing')

    @unittest.skipUnless(PI_INSTALLED, 'optional pinned Pi packages and Node required')
    def test_real_pi_loop_with_fake_provider_and_host_policy(self):
        result = validate()
        self.assertTrue(result['passed'])
        self.assertTrue(all(result['checks'].values()))
        self.assertEqual(result['model_turns'], 3)
        self.assertEqual(result['real_model_calls'], 0)

    @unittest.skipUnless(PI_INSTALLED, 'optional pinned Pi packages and Node required')
    def test_real_pi_passes_tool_failure_to_provider_then_recovers(self):
        host = self.host()
        host.replies = iter([tool_reply('unregistered_tool', 'bad-1', 'synthetic'),
                             tool_reply('lookup', 'lookup-1', 'cache'), self.replies[-1]])
        result = run_pi('Synthetic trial', TOOLS, self.claim['session'], host)
        self.assertEqual(result['model_turns'], 3)
        self.assertEqual(result['tools'], ['lookup'])
        self.assertIn('not found', json.dumps(host.model_inputs).lower())

    @unittest.skipUnless(PI_INSTALLED, 'optional pinned Pi packages and Node required')
    def test_real_pi_revocation_aborts_loop_without_model_retry(self):
        host = self.host(after_model=lambda host: setattr(host, 'revoked', True))
        with self.assertRaisesRegex(ValueError, 'revoked'):
            run_pi('Synthetic trial', TOOLS, self.claim['session'], host)
        self.assertEqual(len(host.model_inputs), 1)
        self.assertEqual(host.tool_calls, [])

    @unittest.skipUnless(PI_INSTALLED, 'optional pinned Pi packages and Node required')
    def test_real_pi_turn_cap_cannot_publish_unfinished_tool_batch_as_final(self):
        host = self.host()
        host.replies = iter([tool_reply('lookup', 'lookup-1', 'cache')])
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            run_pi('Synthetic trial', TOOLS, self.claim['session'], host, max_turns=1)
        self.assertEqual(host.turn, 1)
        self.assertEqual(host.tool_calls, ['lookup'])


if __name__ == '__main__':
    unittest.main()
