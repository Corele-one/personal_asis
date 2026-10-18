import json
import unittest

from personal_asis.credentials import CredentialNotFound
from personal_asis.reading_sources import SourceError
from personal_asis.xhs_credentials import bridge, import_export, normalize_cookies


class Store:
    value = None
    def get(self):
        if self.value is None:raise CredentialNotFound()
        return self.value
    def set(self,value):self.value=value


class XHSCredentialsTests(unittest.TestCase):
    def test_explicit_header_import_os_store_only_and_result_has_no_secrets(self):
        store=Store()
        report=import_export('Cookie: a1=synthetic-a1; web_session=synthetic-session; ',store)
        self.assertTrue(report['session_imported'])
        self.assertFalse(report['account_verified'])
        self.assertNotIn('synthetic-session',str(report))
        session=json.loads(store.value)
        self.assertTrue(all(c['domain']=='.xiaohongshu.com' for c in session['cookies']))
        self.assertEqual(session['cookies'][0]['expires'],-1)

    def test_export_domain_filter_and_cookieeditor_session_format(self):
        rows=[{'name':'web_session','value':'synthetic-session','domain':'.xiaohongshu.com','session':True,'expirationDate':0},
              {'name':'unrelated','value':'excluded','domain':'example.com'}]
        result=normalize_cookies(rows)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['expires'],-1)

    def test_missing_platform_session_invalid_export_and_header_injection_rejected(self):
        for raw in ('a1=synthetic','web_session=abc\r\nInjected: 1','[invalid',
                    '[{"name":"web_session","value":"x","domain":"evilxiaohongshu.com"}]'):
            with self.assertRaises(SourceError):import_export(raw,Store())

    def test_private_bridge_roundtrip_preserves_seed_without_disk(self):
        store=Store()
        session={'version':2,'seed':123,'cookies':[{'name':'web_session','value':'synthetic-session','domain':'.xiaohongshu.com'}]}
        self.assertEqual(bridge({'action':'write','session':session},store),{'stored':True})
        response=bridge({'action':'read'},store)
        self.assertEqual(response['session']['seed'],123)
        self.assertEqual(response['session']['cookies'][0]['value'],'synthetic-session')
        import_export('web_session=refreshed-synthetic-session',store)
        self.assertEqual(json.loads(store.value)['seed'],123)

    def test_no_existing_credential_only_returns_empty_session(self):
        self.assertEqual(bridge({'action':'read'},Store()),{'session':{'version':2,'cookies':[]}})

    def test_private_bridge_write_schema_and_unknown_actions_denied(self):
        for req in ({'action':'delete'},{'action':'write','session':{}},{'action':'write','session':{'version':1}}):
            with self.assertRaises(SourceError):bridge(req,Store())


if __name__=='__main__':unittest.main()
