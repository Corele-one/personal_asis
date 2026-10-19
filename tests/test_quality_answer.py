import json
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from personal_asis import pa1
from personal_asis.model_provider import ProviderUnknown
from personal_asis.quality_answer import analyze, prepare, validate
from personal_asis.retrieval_eval import fixture


class Scorer:
    cache_key = 'c' * 64
    def score(self, query, passages): return [5.] * len(passages)


class Provider:
    def __init__(self, status='supported'):
        self.calls, self.status = 0, status
    def credential(self): return 'SYNTHETIC_ONLY'
    def complete(self, payload, secret):
        self.calls += 1
        if self.status == 'unknown': raise ProviderUnknown('synthetic_unknown')
        context = json.loads(payload['messages'][1]['content'])
        body = context['evidence'][0]['text']
        quotes = [{'evidence_id':'E1','text':body[:min(60,len(body))]}]
        if self.status == 'insufficient_evidence': quotes = []
        if self.status == 'fabricated': quotes[0]['text'] = 'not present in source'
        content = {'status':'supported' if self.status == 'fabricated' else self.status,'quotes':quotes}
        return {'content':json.dumps(content,ensure_ascii=False),'finish_reason':'stop','tool_calls':None,
                'usage':{'prompt_tokens':20,'completion_tokens':40,'total_tokens':60}}


class QualityAnswerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve()
        fixture(self.home)
        pa1.configure(self.home,model='mimo-v2.6-flash',enabled=True,synthetic_only=False)

    def run_answer(self, client, request='one', query='缓存一致性', **kwargs):
        return analyze(self.home,query,['notes'],request,provider=client,reranker=Scorer(),min_score=0.,**kwargs)

    def test_one_generation_and_cached_reuse_under_same_shared_budget(self):
        client = Provider()
        result = self.run_answer(client)
        cached = self.run_answer(client)
        self.assertEqual(client.calls,1)
        self.assertTrue(cached['cached'])
        self.assertTrue(result['literal_quotes_verified'])
        self.assertFalse(result['answer_entailment_verified'])
        self.assertLessEqual(result['prompt_bytes'],result['baseline_lexical_prompt_bytes'])
        self.assertLessEqual(result['prompt_bytes'],result['prompt_byte_limit'])
        self.assertEqual(result['completion_token_limit'],512)
        with sqlite3.connect(self.home/'pa1.sqlite3') as db:
            self.assertEqual(db.execute('SELECT request_id,tokens FROM model_calls').fetchall(),[('quality-answer-v1:one',60)])

    def test_unknown_result_stays_reserved_and_is_never_retried(self):
        client = Provider('unknown')
        with self.assertRaisesRegex(ValueError,'unknown_no_retry'): self.run_answer(client)
        with self.assertRaisesRegex(ValueError,'not_retryable_unknown'): self.run_answer(client)
        self.assertEqual(client.calls,1)
        with sqlite3.connect(self.home/'pa1.sqlite3') as db:
            state,tokens = db.execute('SELECT state,tokens FROM model_calls').fetchone()
        self.assertEqual(state,'unknown')
        self.assertGreater(tokens,60)

    def test_invalid_quote_is_charged_but_cannot_be_repeated(self):
        client = Provider('fabricated')
        with self.assertRaisesRegex(ValueError,'invalid_quote'): self.run_answer(client)
        with self.assertRaisesRegex(ValueError,'not_retryable_invalid_output'): self.run_answer(client)
        self.assertEqual(client.calls,1)
        with sqlite3.connect(self.home/'pa1.sqlite3') as db:
            self.assertEqual(db.execute('SELECT state,tokens FROM model_calls').fetchone(),('invalid_output',60))

    def test_input_change_cannot_reuse_a_paid_request_id(self):
        client = Provider()
        self.run_answer(client)
        with self.assertRaisesRegex(ValueError,'request_id_conflict'):
            self.run_answer(client,query='流水线')
        self.assertEqual(client.calls,1)

    def test_revocation_before_generation_releases_reservation_without_call(self):
        def revoke():
            path=self.home/'sources.yaml';d=json.loads(path.read_text())
            d['sources'][0]['model_providers']=[];path.write_text(json.dumps(d))
        client=Provider()
        with self.assertRaises(ValueError): self.run_answer(client,before_model=revoke)
        self.assertEqual(client.calls,0)
        with sqlite3.connect(self.home/'pa1.sqlite3') as db:
            self.assertEqual(db.execute('SELECT state,tokens FROM model_calls').fetchone(),('rejected',0))

    def test_insufficient_answer_never_repeats_unverified_model_assertions(self):
        result=self.run_answer(Provider('insufficient_evidence'))
        self.assertFalse(result['quotes'])
        self.assertFalse(result['citations'])
        self.assertEqual(result['answer'],'当前证据缺少回答该问题所需的信息。')

    def test_conflict_is_a_flag_with_two_distinct_literal_quotes_not_a_semantic_proof(self):
        evidence=[{'excerpt':'合成版本甲规定阈值为十。'},{'excerpt':'合成版本乙规定阈值为二十。'}]
        quotes=[{'evidence_id':'E1','text':'规定阈值为十。'},{'evidence_id':'E2','text':'规定阈值为二十。'}]
        response={'finish_reason':'stop','tool_calls':None,'content':json.dumps({'status':'conflicting_evidence','quotes':quotes})}
        result=validate(response,evidence)
        self.assertIn('仍需核对',result['answer'])
        quotes[1]=dict(quotes[0]);response['content']=json.dumps({'status':'conflicting_evidence','quotes':quotes})
        with self.assertRaises(ValueError): validate(response,evidence)

    def test_cleanup_removes_revoked_quality_answer_but_preserves_paid_marker(self):
        self.run_answer(Provider())
        path=self.home/'sources.yaml';d=json.loads(path.read_text())
        d['sources'][0]['model_providers']=[];path.write_text(json.dumps(d))
        from personal_asis.pa1_maintenance import clean
        clean(self.home)
        with sqlite3.connect(self.home/'pa1.sqlite3') as db:
            self.assertEqual(db.execute('SELECT state,tokens,response FROM model_calls').fetchone(),('succeeded',60,None))

    def test_cli_requires_explicit_live_request_before_loading_any_model(self):
        from personal_asis.cli import main
        args=['--home',str(self.home),'quality-answer','analyze','--query','缓存一致性','--source','notes',
              '--reranker-dir',str(self.home/'model'),'--min-score','0']
        with patch('personal_asis.reranking.LocalCrossEncoder') as load, patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(main(args),1)
        load.assert_not_called()

    def test_cli_inspection_only_reports_cost_counts_and_never_calls_provider(self):
        from personal_asis.cli import main
        args=['--home',str(self.home),'quality-answer','inspect','--query','缓存一致性','--source','notes',
              '--reranker-dir',str(self.home/'model'),'--min-score','0']
        with patch('personal_asis.reranking.LocalCrossEncoder',return_value=Scorer()), \
             patch('personal_asis.model_provider.MiMo.complete',side_effect=AssertionError('no paid call')), \
             patch('sys.stdout',new_callable=io.StringIO) as output:
            self.assertEqual(main(args),0)
        value=json.loads(output.getvalue())
        self.assertEqual(value['model_generation_calls'],0)
        self.assertNotIn('缓存一致性',output.getvalue())
        self.assertNotIn(str(self.home),output.getvalue())


if __name__=='__main__': unittest.main()
