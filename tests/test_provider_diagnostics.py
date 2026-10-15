from email.message import Message
import io
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError

from personal_asis import pa1
from personal_asis.agent import execute, provider_status
from personal_asis.model_budget import ModelBudget
from personal_asis.model_provider import MiMo, ProviderUnknown
from personal_asis.provider_diagnostics import http_diagnostic as parse_http_diagnostic
from personal_asis.work import WorkStore
from test_agent import FakeTools


def http_error(body, status=429, retry=None):
    headers=Message()
    if retry is not None:
        headers['Retry-After']=retry
    return HTTPError('https://synthetic.invalid/hidden',status,'hidden',headers,io.BytesIO(body))


def http_diagnostic(error,**kwargs):
    try:
        return parse_http_diagnostic(error,**kwargs)
    finally:
        error.close()


class ProviderDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'budget.sqlite3'
        self.now=1000000
        self.budget=ModelBudget(self.path,'mac',daily=1000,monthly=1000,clock=lambda:self.now)
        self.addCleanup(self.budget.close)

    def test_error_body_only_contributes_allowlisted_signals_never_raw_text(self):
        body=json.dumps({'error':{'message':'SYNTHETIC_SECRET quota exhausted',
                                  'code':'SYNTHETIC_SECRET_CODE'}}).encode()
        result=http_diagnostic(http_error(body,retry='600'))
        self.assertEqual(result,{'http_status':429,'category':'quota_signal','retry_after_seconds':600})
        self.assertNotIn('SECRET',json.dumps(result))
        self.assertEqual(http_diagnostic(http_error(b'<html>private content</html>'))['category'],'http_error')

    def test_oversized_malformed_nested_body_and_retry_headers_fail_closed(self):
        for body in (b'x'*8193,b'{',b'null',b'[]',b'{"error":"hidden"}',b'{"error":{"message":[]}}'):
            with self.subTest(body_size=len(body)):
                result=http_diagnostic(http_error(body,retry='SYNTHETIC_SECRET_HEADER'))
                self.assertEqual(result['category'],'http_error')
                self.assertIsNone(result['retry_after_seconds'])

    def test_http_date_hint_and_negative_or_excessive_hint(self):
        value=http_diagnostic(http_error(b'{}',retry='Thu, 01 Jan 1970 00:10:00 GMT'),clock=lambda:0)
        self.assertEqual(value['retry_after_seconds'],600)
        for header in ('-1','0','9999999999999999999999','NaN'):
            self.assertIsNone(http_diagnostic(http_error(b'{}',retry=header))['retry_after_seconds'])

    def test_mimo_exposes_sanitized_diagnostic_without_error_body_or_retry(self):
        error=http_error(b'{"error":{"message":"concurrency limit SYNTHETIC_SECRET"}}',retry='120')
        class Opener:
            calls=0
            def open(self,*args,**kwargs):
                self.calls+=1
                raise error
        opener=Opener()
        client=MiMo('mac','synthetic-model',opener=opener)
        with self.assertRaises(ProviderUnknown) as caught:
            client.request('/chat/completions',{'synthetic':True},'SYNTHETIC_CREDENTIAL')
        self.assertEqual(caught.exception.diagnostic['category'],'concurrency_signal')
        self.assertNotIn('SECRET',str(caught.exception))
        self.assertEqual(opener.calls,1)

    def test_shared_cooldown_blocks_new_reservations_preserves_unknown_and_expires(self):
        self.budget.reserve('old','fp',400)
        diag={'http_status':429,'category':'rate_signal','retry_after_seconds':30}
        self.budget.finish('old','unknown',diagnostic=diag)
        with ModelBudgetContext(self.path,lambda:self.now) as other:
            with self.assertRaisesRegex(ValueError,'provider_cooldown'):
                other.reserve('new','new-fp',100)
            self.assertEqual(other.status()['daily_tokens'],400)
            self.assertEqual(other.provider_status()['cooldown']['remaining_seconds'],300)
        self.now+=301
        self.budget.reserve('new','new-fp',100)
        with self.assertRaisesRegex(ValueError,'not_retryable_unknown'):
            self.budget.reserve('old','fp',400)
        self.assertEqual(self.budget.provider_status()['last_failure']['category'],'rate_signal')

    def test_concurrent_failures_never_shorten_cooldown_and_cache_costs_nothing(self):
        self.budget.reserve('cached','a',10)
        self.budget.finish('cached','succeeded',5,{'synthetic':True})
        self.budget.reserve('first','b',100)
        self.budget.reserve('second','c',100)
        self.budget.finish('first','unknown',diagnostic={
            'http_status':429,'category':'rate_signal','retry_after_seconds':900})
        self.budget.finish('second','unknown',diagnostic={
            'http_status':503,'category':'overload_signal','retry_after_seconds':30})
        self.assertEqual(self.budget.provider_status()['cooldown']['remaining_seconds'],900)
        self.assertEqual(self.budget.provider_status()['cooldown']['reason'],'http_429')
        self.assertEqual(self.budget.reserve('cached','a',10),{'cached':{'synthetic':True}})
        self.assertEqual(self.budget.status()['daily_tokens'],205)

    def test_provider_status_never_calls_model_or_reads_remote_metadata_without_probe(self):
        home=pa1.fixture(Path(self.tmp.name))
        pa1.configure(home,'synthetic-model',True,synthetic_only=False)
        class Probe(FakeTools):
            probes=0
            def models(self):
                self.probes+=1
                return ['synthetic-model']
        client=Probe()
        self.assertFalse(provider_status(home,provider=client)['probe_made'])
        self.assertEqual(client.probes,0)
        result=provider_status(home,probe=True,provider=client)
        self.assertTrue(result['configured_model_listed'])
        self.assertEqual(client.probes,1)
        self.assertEqual(client.calls,[])

    def test_failed_diagnostic_validation_cannot_settle_or_leak(self):
        self.budget.reserve('held','fp',400)
        with self.assertRaisesRegex(ValueError,'invalid_provider_diagnostic'):
            self.budget.finish('held','unknown',diagnostic={'body':'SYNTHETIC_SECRET'})
        self.assertEqual(self.budget.status()['unresolved_calls'],1)
        self.assertEqual(self.budget.provider_status()['last_failure'],None)


class ModelBudgetContext:
    def __init__(self,path,clock):
        self.budget=ModelBudget(path,'mac',daily=1000,monthly=1000,clock=clock)
    def __enter__(self):return self.budget
    def __exit__(self,*args):self.budget.close()
