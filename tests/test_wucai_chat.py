import hashlib
import json
from pathlib import Path
import tempfile
import types
import unittest

from personal_asis.wucai_chat import ArticleReads, KEY


URL = 'https://mp.weixin.qq.com/s/CaseSensitive'


class ChatReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name).resolve();self.reader=ArticleReads(self.home,clock=lambda:1000)
        self.extra={}
        self.event=types.SimpleNamespace(message_str=URL+'\n五彩剪藏了，解析这篇文章',unified_msg_origin='synthetic:owner',
            get_extra=lambda k:self.extra.get(k),set_extra=lambda k,v:self.extra.update({k:v}))

    def result(self,text='正文',offset=0,total=None,digest=None,**extra):
        return json.dumps(dict(status='ok',text=text,offset=offset,total_chars=len(text) if total is None else total,
            content_hash=digest or hashlib.sha256(text.encode()).hexdigest(),note_idx='synthetic',original_url=URL,**extra))

    def test_owner_original_url_wins_over_changed_case_and_guessed_id(self):
        self.reader.begin(self.event)
        for args in [{'url':URL.lower()},{'note_idx':'wrong_search_hit'}]:
            bound=json.loads(self.reader.bind(self.event,'get-article-text',json.dumps(args)))
            self.assertEqual(bound,{'url':URL})

    def test_followup_keeps_article_and_does_not_treat_previous_assistant_text_as_evidence(self):
        self.reader.begin(self.event);self.extra.clear()
        self.event.message_str='总结解析这篇文章'
        self.assertEqual(self.reader.begin(self.event),URL)
        self.assertTrue(self.reader.guard(self.event))
        self.assertEqual(self.reader.path.stat().st_mode&0o777,0o600)

    def test_complete_requires_contiguous_entire_body_of_same_version(self):
        self.reader.begin(self.event)
        digest=hashlib.sha256('abcdef'.encode()).hexdigest()
        self.reader.record(self.event,'get-article-text',self.result('def',3,6,digest))
        self.assertTrue(self.reader.guard(self.event))
        r=json.loads(self.reader.record(self.event,'get-article-text',self.result('abc',0,6,digest)))
        self.assertTrue(r['read_complete']);self.assertTrue(r['can_summarize'])
        self.assertEqual(self.reader.guard(self.event),'')
        self.reader.begin(self.event)
        self.assertEqual(self.reader.guard(self.event),'')

    def test_new_version_cannot_complete_previous_version(self):
        self.reader.begin(self.event)
        self.reader.record(self.event,'get-article-text',self.result('abc',0,6,'a'*64))
        r=json.loads(self.reader.record(self.event,'get-article-text',self.result('def',3,6,'b'*64)))
        self.assertFalse(r['read_complete'])

    def test_lookup_failure_or_search_summary_never_permits_full_article_analysis(self):
        self.reader.begin(self.event)
        for value in [{'status':'lookup_incomplete'}, {'error':'wucai_fulltext_exact_article_required'}, {'status':'not_in_sync_export'}]:
            r=json.loads(self.reader.record(self.event,'get-article-text',json.dumps(value)))
            self.assertFalse(r['can_summarize']);self.assertTrue(self.reader.guard(self.event))
        self.reader.record(self.event,'search-articles',self.result('摘要'))
        self.assertTrue(self.reader.guard(self.event))

    def test_wrong_article_body_is_removed_instead_of_sent_to_model(self):
        self.reader.begin(self.event)
        raw=json.loads(self.result());raw['original_url']='https://example.test/other'
        r=json.loads(self.reader.record(self.event,'get-article-text',json.dumps(raw)))
        self.assertEqual(r['status'],'target_mismatch');self.assertNotIn('text',r)
        self.assertTrue(self.reader.guard(self.event))

    def test_confirmed_alias_receipt_still_requires_matching_owner_target(self):
        self.reader.begin(self.event)
        raw=json.loads(self.result());raw.update(original_url='https://example.test/canonical',requested_url=URL,identity_match='owner_confirmed_alias')
        r=json.loads(self.reader.record(self.event,'get-article-text',json.dumps(raw)))
        self.assertTrue(r['read_complete'])

    def test_normal_conversations_are_untouched_and_targets_expire(self):
        self.event.message_str='今天学完了中断';self.reader.begin(self.event)
        self.assertEqual(self.reader.guard(self.event),'')
        self.event.message_str=URL+'\n五彩全文';self.reader.begin(self.event);self.extra.clear()
        self.event.message_str='总结这篇文章'
        old=ArticleReads(self.home,clock=lambda:1000+86401)
        self.assertEqual(old.begin(self.event),'')
        self.assertEqual(old.guard(self.event),'')


if __name__=='__main__':
    unittest.main()
