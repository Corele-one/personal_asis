import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from personal_asis import reading, xhs_service


class XHSServiceTests(unittest.TestCase):
    def test_plist_contains_only_runtime_paths_not_credentials(self):
        value=xhs_service.plist(Path('/tmp/synthetic-home'),Path('/tmp/synthetic-mcp'))
        self.assertNotIn('AUTH_TOKEN',json.dumps(value))
        self.assertNotIn('COOKIES',json.dumps(value))
        self.assertEqual(value['StandardOutPath'],'/dev/null')
        self.assertFalse('remote' in value['Label'])

    def test_supervised_child_loopback_and_os_secret_environment_only(self):
        child=Mock()
        child.wait.return_value=0
        with patch.object(xhs_service,'CredentialStore') as store, \
                patch.object(xhs_service.subprocess,'Popen',return_value=child) as start, \
                patch.object(xhs_service.signal,'signal'), patch.object(xhs_service.os,'umask'):
            store.return_value.get.return_value='SYNTHETIC_SERVICE_SECRET'
            self.assertEqual(xhs_service.run(Path('/tmp/synthetic-home'),Path('/tmp/synthetic-mcp')),0)
        argv=start.call_args.args[0]
        env=start.call_args.kwargs['env']
        self.assertEqual(argv[-2:],['-port','127.0.0.1:18060'])
        self.assertNotIn('SYNTHETIC_SERVICE_SECRET',' '.join(argv))
        self.assertEqual(env['AUTH_TOKEN'],'SYNTHETIC_SERVICE_SECRET')
        self.assertEqual(env['ASIS_XHS_KEYCHAIN'],'1')
        self.assertNotIn('COOKIES_PATH',env)

    def test_explicit_backend_switch_preserves_sources_and_stays_deferred(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp).resolve()
            reading.configure(home,'xiaohongshu',xhs_backend='opencli')
            before=(home/'sources.yaml').read_bytes()
            reading.configure(home,'xiaohongshu',xhs_backend='mcp')
            self.assertEqual(before,(home/'sources.yaml').read_bytes())
            with reading.ReadingCache(home,'xiaohongshu') as cache:
                values=dict(cache.db.execute('SELECT key,value FROM meta'))
            self.assertEqual(values['xhs_backend'],'mcp')
            self.assertEqual(values['account_access'],'deferred')


if __name__=='__main__':unittest.main()
