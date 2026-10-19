import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import uuid

from personal_asis import agent,pa1
from personal_asis.pi_terminal import Chats,handle,render,safe_error
from personal_asis.runtime_adapter import PI_DIR
from personal_asis.terminal_history import prepare,validate
from personal_asis.work import WorkStore
from test_agent import FakeTools
from test_agent_roles import RolesProvider

PI_AVAILABLE=bool(shutil.which('node') and (PI_DIR/'node_modules/@earendil-works/pi-agent-core').is_dir())

class TerminalMetadataTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=pa1.fixture(self.tmp.name)
        pa1.configure(self.home,'synthetic-model',True,synthetic_only=False)
    def test_unknown_source_and_privileged_mode_cannot_create_chat(self):
        with self.assertRaises(ValueError):handle(self.home,{'action':'new','sources':['unknown']})
        with self.assertRaises(ValueError):handle(self.home,{'action':'new','sources':['synthetic'],'mode':'shell'})
    def test_manifest_stores_references_only_and_expires_after_30_days(self):
        c=Chats(self.home);cid=c.create(['synthetic'],'auto')
        rid='terminal-'+str(uuid.uuid4());c.add(cid,rid)
        self.assertEqual(c.turns(cid),[rid]);c.add(cid,rid);self.assertEqual(c.turns(cid),[rid])
        self.assertEqual([r[1] for r in c.db.execute('PRAGMA table_info(turns)')],['chat','seq','request'])
        c.db.execute('UPDATE chats SET at=0');c.db.commit();c.close()
        c=Chats(self.home);self.addCleanup(c.close)
        with self.assertRaises(ValueError):c.get(cid)
        self.assertEqual(c.db.execute('SELECT count(*) FROM turns').fetchone()[0],0)
    def test_credential_like_query_rejected_before_work_or_model(self):
        cid=handle(self.home,{'action':'new','sources':['synthetic']})['thread']
        with patch('personal_asis.agent.execute',side_effect=AssertionError('no model')):
            with self.assertRaises(ValueError):handle(self.home,{'action':'run','thread':cid,'query':'api_key=sk-012345678901234567890123456789','request_id':'terminal-'+str(uuid.uuid4())})
    def test_concurrent_chat_append_is_compare_and_swap(self):
        c=Chats(self.home);self.addCleanup(c.close);cid=c.create(['synthetic'],'auto')
        c.add(cid,'terminal-'+str(uuid.uuid4()),expected=[])
        with self.assertRaisesRegex(ValueError,'chat_changed'):
            c.add(cid,'terminal-'+str(uuid.uuid4()),expected=[])
        self.assertEqual(len(c.turns(cid)),1)
    def test_errors_do_not_echo_private_paths_or_provider_bodies(self):
        self.assertEqual(safe_error(ValueError('/private/owner/note.md secret body')),'terminal_request_failed_check_local_status')
        self.assertEqual(safe_error(ValueError('agent_model_result_unknown_no_retry')),'agent_model_result_unknown_no_retry')
    def test_default_auto_greeting_uses_current_message_reply_without_note_tools(self):
        cid=handle(self.home,{'action':'new','sources':['synthetic']})['thread']
        with patch('personal_asis.agent.execute',return_value={'status':'completed'}) as execute:
            handle(self.home,{'action':'run','thread':cid,'query':'你好','request_id':'terminal-'+str(uuid.uuid4())})
        self.assertEqual(execute.call_args.kwargs['mode'],'conversation')

@unittest.skipUnless(PI_AVAILABLE,'optional Pi packages and Node required')
class TerminalExecutionTests(unittest.TestCase):
    setUp=TerminalMetadataTests.setUp
    def first(self):
        return agent.execute(self.home,'cache','history-origin',['synthetic'],provider=FakeTools())
    def test_follow_up_has_bounded_fresh_history_and_old_citations_removed(self):
        self.first();records=prepare(self.home,['history-origin'],['synthetic'])
        self.assertNotIn('[E1]',records[0]['analysis_excerpt'])
        client=FakeTools()
        value=agent.execute(self.home,'explain cache','history-followup',['synthetic'],provider=client,
                            terminal_history=['history-origin'])
        self.assertEqual(value['status'],'completed')
        self.assertIn('不是本人确认',client.calls[0]['messages'][1]['content'])
        self.assertIn('旧引用省略',client.calls[0]['messages'][1]['content'])
        repeat=FakeTools();cached=agent.execute(self.home,None,'history-followup',resume=True,provider=repeat)
        self.assertTrue(cached['cached']);self.assertEqual(repeat.calls,[])
    def test_revoked_origin_invalidates_followup_before_reuse(self):
        self.first()
        agent.execute(self.home,'cache again','history-followup',['synthetic'],provider=FakeTools(),terminal_history=['history-origin'])
        path=self.home/'sources.yaml';d=json.loads(path.read_text());d['sources'][0]['model_providers']=[];path.write_text(json.dumps(d))
        with self.assertRaises(ValueError):agent.inspect(self.home,'history-followup')
        with WorkStore(self.home/'work.sqlite3') as work:
            row=work.db.execute("SELECT result FROM runs r JOIN delegations d ON d.id=r.delegation WHERE d.request_id='agent:history-followup'").fetchone()
            self.assertIsNone(row[0])
    def test_context_cannot_be_reused_on_remote_channel_or_narrower_scope(self):
        self.first()
        with self.assertRaises(ValueError):prepare(self.home,['history-origin'],[])
        with self.assertRaises(ValueError):agent.execute(self.home,'cache','remote',['synthetic'],channel='feishu',terminal_history=['history-origin'])
    def test_simple_conversation_does_not_retrieve_or_attach_old_note_history(self):
        self.first()
        class Conversation(FakeTools):
            def complete(self,payload,secret):
                self.calls.append(payload)
                return {'content':json.dumps({'status':'conversational','answer':'你好。','citations':[],'uncertainty':'仅回应本轮消息。'}),
                    'tool_calls':None,'finish_reason':'stop','usage':{'prompt_tokens':10,'completion_tokens':10,'total_tokens':20}}
        client=Conversation()
        value=agent.execute(self.home,'你好','greeting',['synthetic'],provider=client,mode='conversation',terminal_history=['history-origin'])
        self.assertEqual(value['result']['response_kind'],'conversation')
        self.assertNotIn('Synthetic cache',json.dumps(client.calls))
    def test_terminal_end_to_end_shared_roles_budget_load_and_forget(self):
        cid=handle(self.home,{'action':'new','sources':['synthetic'],'mode':'research'})['thread']
        rid='terminal-'+str(uuid.uuid4());events=[]
        client=RolesProvider()
        with patch('personal_asis.agent.ToolMiMo',return_value=client),patch('personal_asis.pa1.encoder_for',return_value=(None,'disabled')):
            value=handle(self.home,{'action':'run','thread':cid,'query':'cache','request_id':rid},events.append)
            cached=handle(self.home,{'action':'run','thread':cid,'query':'cache','request_id':rid},events.append)
        self.assertEqual(value['status'],'completed');self.assertTrue(cached['cached']);self.assertEqual(len(client.calls),2)
        self.assertTrue(any(e['kind']=='model' for e in events))
        loaded=handle(self.home,{'action':'load','thread':cid});self.assertEqual(len(loaded['messages']),1)
        self.assertIn('SUPERVISOR_SYNTHESIS',loaded['messages'][0]['answer'])
        handle(self.home,{'action':'forget','thread':cid})
        with self.assertRaises(ValueError):handle(self.home,{'action':'load','thread':cid})
        with sqlite3.connect(self.home/'pa1.sqlite3') as db:self.assertEqual(db.execute('SELECT count(*) FROM model_calls').fetchone()[0],2)
    def test_unknown_work_blocks_silent_new_turn_and_cannot_be_retried(self):
        cid=handle(self.home,{'action':'new','sources':['synthetic'],'mode':'research'})['thread']
        rid='terminal-'+str(uuid.uuid4());client=RolesProvider(unknown=True)
        with patch('personal_asis.agent.ToolMiMo',return_value=client),patch('personal_asis.pa1.encoder_for',return_value=(None,'disabled')):
            with self.assertRaises(ValueError):handle(self.home,{'action':'run','thread':cid,'query':'cache','request_id':rid})
            with self.assertRaises(ValueError):handle(self.home,{'action':'run','thread':cid,'query':'cache followup','request_id':'terminal-'+str(uuid.uuid4())})
        self.assertEqual(len(client.calls),1)
