import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from personal_asis import native_sources


class NativeSourcesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve() / 'home'
        self.profile = Path(self.tmp.name).resolve() / 'profile'
        self.home.mkdir()
        sources = [{'id': key, 'root': str(self.home / key), 'index': True} for key in (
            'study', 'life', 'reading_wucai', 'reading_folo', 'reading_zhihu')]
        (self.home / 'sources.yaml').write_text(json.dumps({'node_id':'synthetic', 'sources':sources}))
        manifest = self.home / 'reading-cache/xiaohongshu/manifest.sqlite3'
        manifest.parent.mkdir(parents=True)
        with closing(sqlite3.connect(manifest)) as db, db:
            db.execute('CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)')
            db.executemany('INSERT INTO meta VALUES(?,?)', [
                ('enabled','1'), ('xhs_backend','mcp'), ('xhs_endpoint','http://127.0.0.1:18060/mcp')])

    def test_profile_exposes_only_requested_sources_without_bodies_or_credentials(self):
        with patch('personal_asis.credentials.CredentialStore.get', side_effect=AssertionError('no credentials during setup')):
            value = native_sources.prepare(self.home, self.profile)
        self.assertEqual(value['sources'], ['study','life','reading_wucai'])
        context = Path(value['context']).read_text()
        self.assertNotIn('reading_folo', context)
        self.assertNotIn('reading_zhihu', context)
        self.assertIn('reading fetch --source wucai', context)
        self.assertEqual(Path(value['context']).stat().st_mode & 0o777, 0o600)
        mcp = json.loads((self.profile / 'mcp.json').read_text())['mcpServers']['xiaohongshu']
        self.assertEqual(mcp['headers']['Authorization'], 'Bearer ${ASIS_XHS_MCP_TOKEN}')
        self.assertEqual(mcp['exposure'], 'hidden')
        self.assertNotIn('publish', mcp['toolExposure'])
        self.assertFalse((self.profile / 'auth.json').exists())

    def test_existing_native_model_settings_and_unrelated_mcp_are_preserved(self):
        self.profile.mkdir()
        settings = '{"defaultModel":"user-selected-model"}'
        (self.profile / 'settings.json').write_text(settings)
        (self.profile / 'mcp.json').write_text(json.dumps({'mcpServers':{'existing':{'enabled':False}}}))
        native_sources.prepare(self.home, self.profile)
        self.assertEqual((self.profile / 'settings.json').read_text(), settings)
        self.assertIn('existing', json.loads((self.profile / 'mcp.json').read_text())['mcpServers'])

    def test_existing_keychain_values_only_enter_environment(self):
        with patch('personal_asis.credentials.CredentialStore.get', return_value='synthetic-key'), patch.dict(
                native_sources.os.environ, {}, clear=True):
            env = native_sources.credential_environment(self.home)
        self.assertEqual(set(env), {'XIAOMI_API_KEY','ASIS_XHS_MCP_TOKEN'})
        self.assertFalse(self.profile.exists())

    def test_non_loopback_endpoint_is_rejected(self):
        path = self.home / 'reading-cache/xiaohongshu/manifest.sqlite3'
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("UPDATE meta SET value='https://example.com/mcp' WHERE key='xhs_endpoint'")
        with self.assertRaisesRegex(ValueError, 'loopback'):
            native_sources.prepare(self.home, self.profile)

    def test_initialized_library_is_discovered_without_reading_its_content(self):
        path = self.home / 'reading-library/library.sqlite3'
        path.parent.mkdir()
        path.touch()
        value = native_sources.prepare(self.home, self.profile)
        context = Path(value['context']).read_text()
        self.assertIn('asis-library', context)
        self.assertIn('search --query', context)
        self.assertIn('read --source', context)
        self.assertIn('fetch --source', context)
