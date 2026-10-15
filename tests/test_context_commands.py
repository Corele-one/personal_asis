"""Encrypted owner mutations, conflict checks and no plaintext VPS persistence."""
import json,shutil,tempfile,unittest,uuid
from pathlib import Path
from personal_asis import pa1
from personal_asis.context_commands import validate,apply,snapshot
from personal_asis.coordinator import ProtocolError
from personal_asis.domain_context import DomainContexts
from personal_asis.agent_channel import AgentRelay
from personal_asis.feishu import FeishuBridge
from personal_asis.feishu_cards import Cards,card
from personal_asis.runtime_adapter import PI_DIR
import test_agent_channel as channels
from test_analysis_channel import CRYPTO

class ContextCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.home=pa1.fixture(self.tmp.name)
        self.command={'op':'set','domain':'research','expected_revision':0,'goal':'SYNTHETIC_OWNER_GOAL','constraints':'','source_ids':['synthetic'],'allow_model':False}
    def test_exact_schema_boundaries_credentials_and_conflicts(self):
        validate(self.command)
        for changed in ({'extra':'no'},{'allow_model':1},{'expected_revision':False},{'goal':'password: syntheticsecret'},{'source_ids':[]},{'domain':'shell'}):
            with self.assertRaises(ProtocolError):validate({**self.command,**changed})
        first=apply(self.home,self.command,'first');self.assertEqual(first['revision'],1)
        self.assertNotIn('roots',first);self.assertNotIn(str(self.home),json.dumps(first));self.assertFalse(first['model_called'])
        with self.assertRaisesRegex(ValueError,'revision_conflict'):apply(self.home,self.command,'stale')
        self.assertEqual(apply(self.home,self.command,'first')['revision'],1)
        apply(self.home,{'op':'forget','domain':'research','expected_revision':1},'forget')
        self.assertTrue(snapshot(self.home,'research')['deleted'])
        self.assertIsNone(snapshot(self.home,'research')['goal'])
    def test_metadata_extension_keeps_legacy_plugin_insert_compatible(self):
        bridge=FeishuBridge(self.home);self.addCleanup(bridge.close);cards=Cards(bridge)
        self.assertEqual(len(bridge.db.execute('PRAGMA table_info(card_sessions)').fetchall()),10)
        # The retained old plugin's positional SQL must work on the upgraded database.
        bridge.db.execute('INSERT INTO card_sessions VALUES(?,?,?,?,NULL,0,NULL,?,?,?)',
                          ('legacy','lark','ou_owner','legacy_message','sending',0,1800))
        self.assertEqual(cards.session('legacy')['page'],'work')

    def test_card_manage_show_set_delete_fences_and_keeps_only_metadata(self):
        bridge=FeishuBridge(self.home);self.addCleanup(bridge.close)
        bridge.bind('lark','ou_owner',bridge.pairing('lark')['pairing_code'])
        cards=Cards(bridge);session,_=cards.create('lark','ou_owner','msg');cards.sent(session['id'],'om_card')
        def click(action,form=None,**extra):
            current=cards.session(session['id'])
            return cards.accept('lark','ou_owner','om_card',{'asis_card':session['id'],'revision':str(current['revision']),'action':action,**extra},form)
        state,job,_=click('manage');self.assertIsNone(job);self.assertEqual(state['page'],'context')
        state,job,_=click('context_show',{'domain':'research'})
        self.assertEqual(job['context'],{'op':'show','domain':'research'})
        rendered=card(state,view={'result':snapshot(self.home,'research')})
        self.assertIn('保存新目标',json.dumps(rendered,ensure_ascii=False))
        state,job,_=click('context_set',{'goal':'SYNTHETIC_CARD_GOAL','constraints':'','sources':'study','permission':'local'},domain='research',expected_revision='0')
        self.assertEqual(job['context']['goal'],'SYNTHETIC_CARD_GOAL');self.assertFalse(job['context']['allow_model'])
        self.assertNotIn(b'SYNTHETIC_CARD_GOAL',b''.join(p.read_bytes() for p in self.home.glob('feishu*.sqlite3*')))
        old={'asis_card':session['id'],'revision':str(state['revision']-1),'action':'context_set','domain':'research','expected_revision':'0'}
        _,job,duplicate=cards.accept('lark','ou_owner','om_card',old,{'goal':'changed'})
        self.assertTrue(duplicate);self.assertIsNone(job)
        _,job,_=click('new');self.assertIsNone(job)
        state,job,_=click('run',{'question':'cache','mode':'research','sources':'study','continuity':'history'})
        self.assertTrue(job['use_context']);self.assertTrue(job['role_history'])

@unittest.skipUnless(CRYPTO and shutil.which('node') and (PI_DIR/'node_modules/@earendil-works/pi-agent-core').is_dir(),'crypto and Pi required')
class EncryptedContextTests(unittest.TestCase):
    setUp=channels.AgentChannelTests.setUp
    decrypt=channels.AgentRelayTests.decrypt
    command=channels.AgentRelayTests.command
    drain=channels.AgentChannelTests.drain
    send=channels.AgentChannelTests.send
    def context(self,op='show',**fields):
        return {**self.command('context'),'context':{'op':op,'domain':'research',**fields}}
    def test_show_save_replay_stale_write_and_forget_never_call_model(self):
        initial=self.send(self.context());self.assertEqual(initial['revision'],0)
        request=self.context('set',goal='SYNTHETIC_REMOTE_GOAL',constraints='',source_ids=['synthetic'],allow_model=True,expected_revision=0)
        value=self.send(request);self.assertEqual(value['revision'],1);self.assertNotIn('roots',value)
        self.relay.jobs.clear();self.assertEqual(self.send(request)['revision'],1)
        stale={**request,'request_id':str(uuid.uuid4())};self.assertEqual(self.send(stale)['error'],'domain_context_revision_conflict')
        removed=self.send(self.context('forget',expected_revision=1));self.assertTrue(removed['deleted'])
        self.assertEqual(self.provider.calls,[])
        raw=b''.join(p.read_bytes() for p in self.home.glob('work.sqlite3*'))
        self.assertNotIn(b'SYNTHETIC_REMOTE_GOAL',raw)
    def test_invalid_options_do_not_reach_worker_and_busy_run_can_receive_context(self):
        for changed in ({'mode':'life','use_context':1},{'role_history':True},{'mode':'conversation','use_context':True}):
            with self.assertRaises(ProtocolError):self.relay.request({**self.data,**changed})
        self.relay.request(self.data);self.relay.poll('mac','a'*64)
        request=self.context();self.relay.request(request)
        job=self.relay.poll('mac','a'*64,True)['job'];self.assertEqual(job['action'],'context')
    def test_context_input_never_grants_a_source_or_changes_budget(self):
        before=(self.home/'sources.yaml').read_bytes()
        denied=self.send(self.context('set',goal='SYNTHETIC_GOAL',constraints='',source_ids=['new-source'],allow_model=True,expected_revision=0))
        self.assertEqual(denied['error'],'domain_context_source_not_configured')
        self.assertEqual((self.home/'sources.yaml').read_bytes(),before);self.assertEqual(self.provider.calls,[])
