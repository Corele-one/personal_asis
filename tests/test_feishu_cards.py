import json
from pathlib import Path
import tempfile
import unittest
import uuid

from personal_asis.feishu import FeishuBridge
from personal_asis.feishu_cards import Cards,card


class CardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.bridge=FeishuBridge(Path(self.tmp.name));self.addCleanup(self.bridge.close)
        code=self.bridge.pairing('lark')['pairing_code'];self.bridge.bind('lark','ou_owner',code)
        self.cards=Cards(self.bridge)
        self.session,self.fresh=self.cards.create('lark','ou_owner','message')
        self.cards.sent(self.session['id'],'om_card')
    def value(self,action,session=None):
        session=session or self.cards.session(self.session['id'])
        return {'asis_card':session['id'],'revision':str(session['revision']),'action':action}
    def accept(self,action,form=None,**kw):
        return self.cards.accept('lark','ou_owner','om_card',self.value(action),form,**kw)
    def start(self):
        return self.accept('run',{'question':'SYNTHETIC_PRIVATE_QUESTION','mode':'career','sources':'study,life'})

    def test_menu_is_form_schema_two_no_webhook_and_result_uses_plain_text(self):
        value=card(self.session)
        self.assertEqual(value['schema'],'2.0')
        self.assertFalse(value['config']['enable_forward'])
        forms=[e for e in value['body']['elements'] if e['tag']=='form']
        self.assertEqual(len(forms),2)
        names=[c['name'] for f in forms for c in f['elements'] if 'name' in c]
        self.assertEqual(len(names),len(set(names)))
        self.assertNotIn('https://',json.dumps(value))
        rendered=card(self.session,'<at id=all> secret [link](https://evil.invalid)')
        self.assertTrue(all(e['tag']!='markdown' for e in rendered['body']['elements']))

    def test_duplicate_menu_send_unknown_never_creates_another_delivery(self):
        repeated,fresh=self.cards.create('lark','ou_owner','message')
        self.assertFalse(fresh);self.assertEqual(repeated['id'],self.session['id'])
        self.cards.sent(self.session['id'],None)
        with self.assertRaises(ValueError):self.start()
        self.assertFalse(self.cards.create('lark','ou_owner','message')[1])

    def test_form_acceptance_durable_identity_without_plaintext_and_duplicate_no_new_work(self):
        value=self.value('run')
        session,job,duplicate=self.start()
        self.assertFalse(duplicate);self.assertEqual(job['source_ids'],['study','life'])
        self.assertEqual(job['mode'],'career')
        expected=uuid.uuid5(uuid.NAMESPACE_URL,'asis-agent-work:lark:ou_owner:'+job['command'])
        self.assertEqual(job['target_id'],str(expected))
        repeated=self.cards.accept('lark','ou_owner','om_card',value,{'question':'changed'})
        self.assertTrue(repeated[2]);self.assertIsNone(repeated[1])
        disk=b''.join(p.read_bytes() for p in Path(self.tmp.name).glob('*.sqlite3*'))
        self.assertNotIn(b'SYNTHETIC_PRIVATE_QUESTION',disk)
        self.assertNotIn(b'question',disk)

    def test_foreign_account_forwarded_card_wrong_platform_and_expiry_are_refused(self):
        for platform,owner,message in [('other','ou_owner','om_card'),('lark','ou_other','om_card'),('lark','ou_owner','om_forward')]:
            with self.assertRaises(ValueError):self.cards.accept(platform,owner,message,self.value('new'),{})
        self.bridge.db.execute('UPDATE card_sessions SET expires=0')
        with self.assertRaises(ValueError):self.accept('new')

    def test_form_credential_unknown_scope_role_and_control_fields_are_refused(self):
        valid={'question':'cache','mode':'research','sources':'study'}
        for bad in [{'question':'api_key: sk-'+('x'*30)},{'sources':'outside'},{'mode':'shell'},
                    {'question':''},{'target':str(uuid.uuid4())}]:
            with self.assertRaises(ValueError):self.accept('run',{**valid,**bad})
        self.start()
        with self.assertRaises(ValueError):self.accept('resume',{'sources':'life'})
        with self.assertRaises(ValueError):self.accept('run',valid)

    def test_old_resume_and_double_click_cannot_reopen_new_pause(self):
        self.start();old=self.value('resume')
        self.accept('resume');self.accept('pause')
        current,job,replay=self.cards.accept('lark','ou_owner','om_card',old,{})
        self.assertTrue(replay);self.assertIsNone(job)
        self.assertEqual(current['revision'],3)

    def test_stale_result_cannot_replace_newer_card_and_lookup_uses_same_work(self):
        session,job,_=self.start()
        task=str(uuid.uuid4());self.cards.submitted(job,task)
        self.bridge.db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?)',('delivery',task,'sending',0,0))
        self.assertIsNotNone(self.cards.for_delivery('om_card','delivery'))
        self.accept('pause')
        self.assertIsNone(self.cards.for_delivery('om_card','delivery'))
        session,_,_=self.accept('new')
        self.assertIsNone(session['target_id'])
        self.assertIsNone(self.cards.for_delivery('om_card','delivery'))
        looked,job,_=self.accept('lookup',{'target':job['target_id']})
        self.assertEqual(job['action'],'status')
        self.assertEqual(looked['target_id'],job['target_id'])

    def test_rebinding_removes_old_card_authority(self):
        code=self.bridge.pairing('lark')['pairing_code'];self.bridge.bind('lark','ou_new',code)
        with self.assertRaises(ValueError):self.start()

    def test_structured_card_separates_user_agent_status_and_historical_quotes(self):
        session,_,_=self.start()
        view={'result':{'question':'SYNTHETIC_USER_MESSAGE','state':'completed','committed_actions':3,
            'result':{'answer':'SYNTHETIC_AGENT_ANSWER','uncertainty':'SYNTHETIC_LIMIT',
                'role_plan':{'roles':['life']},'evidence':[{'id':'E1','source_id':'life','title':'A note',
                    'path_hint':'2026-06-03.md','excerpt':'SYNTHETIC_HISTORICAL_QUOTE'}]}}}
        rendered=card(session,view=view)
        content=[e['text']['content'] for e in rendered['body']['elements'] if e['tag']=='div']
        self.assertLess(content.index('【你的问题】'),content.index('SYNTHETIC_USER_MESSAGE'))
        self.assertLess(content.index('【Agent 的回答 · 总管汇总】'),content.index('SYNTHETIC_AGENT_ANSWER'))
        self.assertIn('【参考资料 · 原文摘录不是 Agent 的回答】',content)
        self.assertTrue(any('2026-06-03' in s for s in content))
        self.assertTrue(any('不代表你当前的状态' in s for s in content))
        self.assertTrue(all(e['tag']!='markdown' for e in rendered['body']['elements']))
        disk=b''.join(p.read_bytes() for p in Path(self.tmp.name).glob('*.sqlite3*'))
        self.assertNotIn(b'SYNTHETIC_USER_MESSAGE',disk)
        self.assertNotIn(b'SYNTHETIC_AGENT_ANSWER',disk)

    def test_current_message_reply_marks_no_history_and_pending_receipt_is_not_an_answer(self):
        session,_,_=self.start()
        pending=json.dumps(card(session,question='SYNTHETIC_CURRENT_INPUT'),ensure_ascii=False)
        self.assertIn('尚无 Agent 的回答',pending)
        rendered=json.dumps(card(session,view={'result':{'question':'SYNTHETIC_CURRENT_INPUT',
            'state':'completed','result':{'answer':'SYNTHETIC_CURRENT_REPLY','response_kind':'conversation'}}}),ensure_ascii=False)
        self.assertIn('Agent 的回答',rendered)
        self.assertIn('未检索笔记或日记',rendered)
        self.assertNotIn('参考资料 ·',rendered)
