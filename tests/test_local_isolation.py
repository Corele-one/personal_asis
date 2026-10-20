"""Exercise public local entry points with all legacy remote imports blocked."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class LocalIsolationTests(unittest.TestCase):
    def test_host_disclosure_rechecks_grants_and_removes_source_uris(self):
        from personal_asis import pa1
        from personal_asis.disclosure import validate_result
        from personal_asis.retrieval import build_bundle
        with tempfile.TemporaryDirectory() as directory:
            home = pa1.fixture(directory)
            bundle = build_bundle(home, 'cache')
            result = {'provider': bundle.provider, 'evidence': bundle.evidence,
                      'retrieval_mode': bundle.retrieval_mode}
            self.assertTrue(bundle.evidence)
            with self.assertRaisesRegex(ValueError, 'context_channel_permission_denied'):
                validate_result(home, result, 'feishu')
            path = home / 'sources.yaml'
            config = json.loads(path.read_text())
            config['sources'][0].update(remote_metadata=True, remote_evidence=True)
            path.write_text(json.dumps(config))
            clean = validate_result(home, result, 'feishu')
            self.assertTrue(all('original_uri' not in e for e in clean['evidence']))
            self.assertTrue(any('original_uri' in e for e in result['evidence']))
            config['sources'][0]['remote_evidence'] = False
            path.write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError, 'context_channel_permission_denied'):
                validate_result(home, result, 'feishu')

    def test_local_entrypoints_import_and_doctor_without_remote_adapters(self):
        # Fresh process also catches eager imports hidden by the full test suite.
        code = '''
import sys
from local_agent_suite import NoRemoteAdapters, REMOTE_MODULES
guard = NoRemoteAdapters()
sys.meta_path.insert(0, guard)
from personal_asis import cli, pi_terminal, conversation_terminal, conversation_api, conversation_web
from personal_asis import conversation_tools, agent, pa1, work_history, disclosure
assert cli.main(['doctor']) == 0
assert not guard.attempts, guard.attempts
assert not REMOTE_MODULES.intersection(sys.modules)
'''
        root = Path(__file__).resolve().parents[1]
        env = {**os.environ, 'PYTHONPATH': os.pathsep.join((str(root / 'src'), str(root / 'tests')))}
        result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['fts5_trigram'])

    def test_local_commands_ignore_existing_remote_connection_configuration(self):
        from personal_asis import cli, pa1
        with tempfile.TemporaryDirectory() as directory:
            home = pa1.fixture(directory)
            # An old remote configuration must not be read by local commands.
            connection = Path(home) / 'coordinator.json'
            connection.write_text('invalid legacy remote configuration')
            for command in (['status'], ['search', 'cache'], ['chat', '--list']):
                with self.subTest(command=command), redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(['--home', str(home), *command]), 0)
            self.assertEqual(connection.read_text(), 'invalid legacy remote configuration')
            self.assertFalse((Path(home) / 'coordinator.sqlite3').exists())
            self.assertFalse((Path(home) / 'node-tasks.sqlite3').exists())
