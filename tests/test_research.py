from datetime import datetime,timezone
import json
import unittest
from unittest.mock import patch

from personal_asis.research import collect,public_url,augment
from personal_asis.retrieval import ContextBundle
from personal_asis.model_provider import validate_answer


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.dns=patch('personal_asis.web_search.resolve',return_value=['8.8.8.8'])
        self.dns.start();self.addCleanup(self.dns.stop)
        self.request={'public_query':'AI accelerator inference','urls':['https://www.nvidia.com/research']}
        self.text='Title: Synthetic technical material\nPublished Time: 2026-10-01\nMarkdown Content:\n\n'+('AI accelerator inference memory bandwidth. '*10)

    def test_private_network_credentials_and_nonpublic_urls_rejected(self):
        for url in ('http://example.com','https://user:secret@example.com','https://example.com/?token=secret','https://example.com/#private'):
            with self.assertRaises(ValueError):public_url(url)
        with patch('personal_asis.web_search.resolve',return_value=['127.0.0.1']):
            with self.assertRaisesRegex(ValueError,'dns_nonpublic'):public_url('https://example.com')

    def test_search_gets_only_explicit_public_query_and_url_fallback_is_dated(self):
        def fail(query):
            self.assertEqual(query,self.request['public_query'])
            raise ValueError('limited')
        result=collect(self.request,fail,lambda _:self.text)
        e=result['evidence'][0]
        self.assertEqual(e['published_at'],'2026-10-01')
        self.assertEqual(e['source_class'],'primary')
        self.assertTrue(e['retrieved_at']);self.assertTrue(result['strategy']['gaps'])

    def test_signal_and_unknown_publication_date_are_explicit(self):
        result=collect({'public_query':'chip','urls':[]},lambda _:['https://example.com/news'],lambda _:self.text.replace('Published Time: 2026-10-01\n',''))
        self.assertEqual(result['evidence'][0]['source_class'],'signal')
        self.assertIsNone(result['evidence'][0]['published_at'])

    def test_no_external_evidence_or_credential_query_fails_closed(self):
        with self.assertRaises(ValueError):collect({'public_query':'api_key: sk-'+('x'*30),'urls':[]},lambda _:[],lambda _:self.text)
        with self.assertRaisesRegex(ValueError,'no_public_evidence'):collect(self.request,lambda _:[],lambda _: '')

    def answer_and_bundle(self):
        collected=collect(self.request,lambda _:[],lambda _:self.text)
        local={'document_id':'synthetic','content_hash':'hash','excerpt':'synthetic','title':'local','sensitivity':'normal'}
        bundle=augment(ContextBundle('private question','mimo',[local],'hybrid'),collected)
        direction={'hypothesis':'A possible direction','connection':'related [E1]','gap':'needs testing','opportunity':'possible','risk':'uncertain','next_step':'benchmark'}
        answer={'answer':'Evidence [E1][E2]','citations':['E1','E2'],'uncertainty':'limited',
            'report':{'existing_knowledge':'local [E1]','external_findings':'vendor [E2]','knowledge_gaps':'missing','disagreements':'vendor not independent','directions':[direction.copy(),direction.copy()]}}
        return answer,bundle

    def validate(self,answer,bundle):
        return validate_answer({'finish_reason':'stop','tool_calls':None,'content':json.dumps(answer)},bundle)

    def test_exploration_requires_local_primary_and_two_or_three_linked_directions(self):
        answer,bundle=self.answer_and_bundle()
        self.assertEqual(len(self.validate(answer,bundle)['report']['directions']),2)
        answer['report']['directions']=answer['report']['directions'][:1]
        with self.assertRaises(ValueError):self.validate(answer,bundle)

    def test_signal_alone_unknown_references_or_unlinked_direction_rejected(self):
        for issue in ('signal','reference','connection'):
            answer,bundle=self.answer_and_bundle()
            if issue=='signal':bundle.evidence[1]['source_class']='signal'
            if issue=='reference':answer['report']['external_findings']='unknown [E99]'
            if issue=='connection':answer['report']['directions'][0]['connection']='unlinked'
            with self.assertRaises(ValueError):self.validate(answer,bundle)

    def test_report_reference_index_can_add_known_inline_ids_but_never_unknown_ones(self):
        answer,bundle=self.answer_and_bundle()
        answer['citations']=['E1']
        result=self.validate(answer,bundle)
        self.assertEqual(result['citations'],['E1','E2'])
        self.assertTrue(result['citation_index_normalized'])
        answer['report']['disagreements']='invented [E99]'
        with self.assertRaises(ValueError):self.validate(answer,bundle)

    def test_research_stale_external_context_rejected(self):
        _,bundle=self.answer_and_bundle();bundle.local_count=0
        bundle.evidence=bundle.evidence[1:]
        bundle.evidence[0]['retrieved_at']='2000-01-01T00:00:00+00:00'
        with patch('personal_asis.retrieval.ContextBundle.revalidate'):
            with self.assertRaisesRegex(ValueError,'expired'):bundle.revalidate('/tmp')

    def test_uncertainty_references_count_but_answer_still_needs_evidence(self):
        from personal_asis.model_provider import validate_answer
        bundle=ContextBundle('q','mimo',[{},{}],'lexical')
        response={'finish_reason':'stop','tool_calls':None,'content':json.dumps({
            'answer':'supported [E1]','citations':['E1','E2'],'uncertainty':'limited coverage [E2]'})}
        self.assertEqual(validate_answer(response,bundle)['citations'],['E1','E2'])
        response['content']=json.dumps({'answer':'unsupported personal claim','citations':['E1'],
                                      'uncertainty':'coverage [E1]'})
        with self.assertRaises(ValueError):validate_answer(response,bundle)
