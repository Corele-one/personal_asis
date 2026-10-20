import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from personal_asis import native_sources, source_write, xhs_accounts, xhs_credentials, xhs_service
from personal_asis.credentials import CredentialNotFound


class XHSAccountsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve()
        self.original = patch.object(native_sources, 'xhs_configuration', return_value='http://127.0.0.1:18060/mcp')
        self.original.start()
        self.addCleanup(self.original.stop)
        xhs_accounts.label_original(self.home, 'Primary')
        xhs_accounts.register(self.home, 'second', 'Second', 18061)

    def test_two_accounts_preserve_original_and_reject_endpoint_collision(self):
        accounts = native_sources.xhs_configurations(self.home)
        self.assertEqual(accounts['default']['label'], 'Primary')
        self.assertEqual(accounts['second']['endpoint'], 'http://127.0.0.1:18061/mcp')
        before = (self.home / 'xhs-accounts.json').read_bytes()
        for key, port in [('other', 18061), ('second', 18062), ('other', 18060)]:
            with self.assertRaises(ValueError):
                xhs_accounts.register(self.home, key, 'Other', port)
        self.assertEqual((self.home / 'xhs-accounts.json').read_bytes(), before)

    def test_bridge_reads_only_selected_keychain_entry(self):
        with patch.dict(xhs_credentials.os.environ, {'ASIS_XHS_ACCOUNT': 'second'}), patch.object(xhs_credentials, 'CredentialStore') as store:
            store.return_value.get.return_value = '{"version":2,"cookies":[],"seed":234}'
            self.assertEqual(xhs_credentials.bridge({'action': 'read'})['session']['seed'], 234)
        store.assert_called_once_with('xiaohongshu-session:second', xhs_accounts.SERVICE)
        self.assertEqual(xhs_accounts.credential(), 'xiaohongshu-session')

    def test_disabling_original_account_does_not_disable_second_account(self):
        with patch.object(native_sources, 'xhs_configuration', return_value=None):
            self.assertEqual(set(native_sources.xhs_configurations(self.home)), {'second'})

    def test_second_service_has_separate_environment_and_label(self):
        value = xhs_service.plist(self.home, '/tmp/synthetic-mcp', 'second', 18061)
        self.assertEqual(value['Label'], 'local.personal-asis.xiaohongshu.second')
        child = Mock()
        child.wait.return_value = 0
        with patch.object(xhs_service, 'CredentialStore') as store, patch.object(xhs_service.subprocess, 'Popen', return_value=child) as start, patch.object(xhs_service.signal, 'signal'):
            store.return_value.get.return_value = 'synthetic-token'
            xhs_service.run(self.home, '/tmp/synthetic-mcp', 'second', 18061)
        store.assert_called_once_with('xiaohongshu-mcp:second', xhs_accounts.SERVICE)
        self.assertEqual(start.call_args.kwargs['env']['ASIS_XHS_ACCOUNT'], 'second')
        self.assertEqual(start.call_args.args[0][-1], '127.0.0.1:18061')

    def test_native_profile_and_tokens_route_independently(self):
        (self.home / 'sources.yaml').write_text('{"node_id":"test","sources":[]}')
        profile = self.home / 'profile'
        with patch('personal_asis.credentials.CredentialStore.get', side_effect=AssertionError('setup must not read secrets')):
            native_sources.prepare(self.home, profile)
        servers = json.loads((profile / 'mcp.json').read_text())['mcpServers']
        self.assertEqual(servers['xiaohongshu_second']['headers']['Authorization'], 'Bearer ${ASIS_XHS_MCP_TOKEN_SECOND}')
        self.assertIn('Second', servers['xiaohongshu_second']['description'])
        self.assertIn('Primary', servers['xiaohongshu']['description'])
        with patch.dict(native_sources.os.environ, {}, clear=True), patch('personal_asis.credentials.CredentialStore.get', return_value='synthetic'):
            env = native_sources.credential_environment(self.home, model=False)
        self.assertEqual(set(env), {'ASIS_XHS_MCP_TOKEN', 'ASIS_XHS_MCP_TOKEN_SECOND'})

    def test_write_requires_account_and_routes_to_its_endpoint_and_token(self):
        request = {'source': 'xiaohongshu', 'operation': 'like_feed', 'arguments': {'feed_id': 'synthetic', 'xsec_token': 'synthetic', 'unlike': False}}
        with self.assertRaisesRegex(ValueError, 'explicit_account'):
            source_write.prepare(request, self.home, self.home)
        plan = source_write.prepare(dict(request, account='second'), self.home, self.home)
        self.assertIn('账号：Second (second)', plan['preview'])
        with patch('personal_asis.social_reading.XiaoHongShu') as client, patch('personal_asis.credentials.CredentialStore') as store:
            client.return_value._rpc.side_effect = [{'protocolVersion':'2025-03-26'}, {}, {'tools':[{'name':'like_feed'}]}, {'content':[]}]
            source_write.execute(plan['plan'], plan['digest'], self.home, self.home)
        self.assertEqual(client.call_args.args[0], 'http://127.0.0.1:18061/mcp')
        store.assert_called_once_with('xiaohongshu-mcp:second', xhs_accounts.SERVICE)

    def test_owner_duplicate_export_does_not_overwrite_any_session(self):
        exported = 'web_session=synthetic-original'
        original = json.dumps({'version': 2, 'cookies': [{'name': 'web_session', 'value': 'synthetic-original'}]})
        with patch('sys.stdin.isatty', return_value=True), patch('getpass.getpass', return_value=exported), patch('personal_asis.credentials.CredentialStore') as store:
            store.return_value.get.return_value = original
            with self.assertRaisesRegex(ValueError, 'duplicate_original'):
                xhs_accounts.import_owner('second')
        store.return_value.set.assert_not_called()

    def test_owner_new_session_is_saved_only_to_second_account(self):
        with patch('sys.stdin.isatty', return_value=True), patch('getpass.getpass', return_value='web_session=synthetic-new'), patch('personal_asis.credentials.CredentialStore') as original, patch.object(xhs_credentials, 'CredentialStore') as second:
            original.return_value.get.side_effect = CredentialNotFound()
            second.return_value.get.side_effect = CredentialNotFound()
            result = xhs_accounts.import_owner('second')
        second.assert_called_once_with('xiaohongshu-session:second', xhs_accounts.SERVICE)
        original.return_value.set.assert_not_called()
        self.assertTrue(result['session_imported'])
        self.assertNotIn('synthetic-new', str(result))


if __name__ == '__main__':
    unittest.main()
