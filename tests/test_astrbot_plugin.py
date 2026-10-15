"""Run in the installed AstrBot interpreter; never send platform messages."""

import asyncio
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import Mock

from personal_asis.feishu import FeishuBridge


class Event:
    def __init__(self, text, platform="lark-fixture", sender="ou_owner", private=True):
        self.message_str, self.platform, self.sender, self.private = text, platform, sender, private
        self.stopped, self.call_llm = False, True
        self.message_obj = SimpleNamespace(message_id="message-1", raw_message=SimpleNamespace(message_type="text", parent_id=None))

    def get_platform_id(self): return self.platform
    def get_sender_id(self): return self.sender
    def is_private_chat(self): return self.private
    def should_call_llm(self, value): self.call_llm = value
    def stop_event(self): self.stopped = True


@unittest.skipUnless(importlib.util.find_spec("astrbot"), "run with the VPS AstrBot interpreter")
class AstrBotPluginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "integrations/astrbot_plugin_personal_asis/main.py"
        spec = importlib.util.spec_from_file_location("asis_plugin_smoke", path)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.plugin = self.module.PersonalAsis.__new__(self.module.PersonalAsis)
        self.plugin.bridge = FeishuBridge(Path(self.tmp.name))
        self.addCleanup(self.plugin.bridge.close)
        self.plugin.lock = asyncio.Lock()
        self.plugin.home = Path(self.tmp.name)
        self.plugin.worker = None
        self.adapter = SimpleNamespace(meta=lambda: SimpleNamespace(name="lark"), connection_mode="socket")
        self.plugin.context = SimpleNamespace(get_platform_inst=lambda platform: self.adapter if platform == "lark-fixture" else None)
        self.sent = []
        async def send(*args):
            self.sent.append(args)
            return True
        self.plugin.send = send

    def bind(self):
        code = self.plugin.bridge.pairing("lark-fixture")["pairing_code"]
        self.plugin.bridge.bind("lark-fixture", "ou_owner", code)

    def test_unauthorized_other_platform_group_and_webhook_never_fall_through(self):
        for event in (Event("/asis search 芯片"), Event("/asis search 芯片", platform="qq"),
                      Event("/asis search 芯片", private=False)):
            asyncio.run(self.plugin.on_message(event))
            self.assertTrue(event.stopped)
            self.assertFalse(event.call_llm)
        self.bind()
        self.adapter.connection_mode = "webhook"
        event = Event("/asis search 芯片")
        asyncio.run(self.plugin.on_message(event))
        self.assertTrue(event.stopped)
        self.assertEqual(self.sent, [])

    def test_normal_message_is_unchanged_and_registered_regex_is_available(self):
        from astrbot.api.event import filter
        self.assertTrue(callable(filter.regex))
        event = Event("普通聊天")
        asyncio.run(self.plugin.on_message(event))
        self.assertFalse(event.stopped)
        self.assertTrue(event.call_llm)
        self.assertEqual(self.sent, [])

    def test_authorized_search_is_persisted_without_model_or_duplicate_send(self):
        self.bind()
        event = Event("/asis search 芯片")
        asyncio.run(self.plugin.on_message(event))
        self.assertTrue(event.stopped)
        self.assertFalse(event.call_llm)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("部分结果", self.sent[0][2])
        asyncio.run(self.plugin.on_message(event))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.plugin.bridge.db.execute("SELECT count(*) FROM routes").fetchone()[0], 1)

    def test_analysis_and_research_use_bound_owner_adapter_without_astrbot_model(self):
        self.bind()
        self.plugin.bridge.submit_analysis=Mock(return_value='synthetic-id')
        for command in ('/asis analyze 个人问题','/asis research 个人问题 | public chip query | https://example.com/article'):
            event=Event(command)
            asyncio.run(self.plugin.on_message(event))
            self.assertFalse(event.call_llm)
            self.assertTrue(event.stopped)
        args=self.plugin.bridge.submit_analysis.call_args.args
        self.assertEqual(args[3],'个人问题')
        self.assertEqual(args[4],{'public_query':'public chip query','urls':['https://example.com/article']})

    def test_analysis_status_keeps_delivered_state_after_relay_expires(self):
        self.bind()
        with self.plugin.bridge.db:
            self.plugin.bridge.db.execute('INSERT INTO analysis_routes VALUES(?,?,?,?,?)',('synthetic-id','lark-fixture','ou_owner','m',0))
            self.plugin.bridge.db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?)',('delivery','synthetic-id','sent',0,0))
        asyncio.run(self.plugin.on_message(Event('/asis status synthetic-id')))
        self.assertIn('结果已回复此私聊',self.sent[0][2])

    def test_agent_scope_controls_and_duplicate_ack_never_use_default_model(self):
        self.bind()
        request=str(uuid.uuid4());target=str(uuid.uuid4())
        self.plugin.bridge.agent.submit=Mock(return_value={'request_id':request,'target_id':target,'submitted':True})
        event=Event('/asis agent study | 核对证据')
        asyncio.run(self.plugin.on_message(event))
        asyncio.run(self.plugin.on_message(event))
        self.assertFalse(event.call_llm)
        self.assertEqual(len(self.sent),1)
        self.assertEqual(self.plugin.bridge.agent.submit.call_args.kwargs['source_ids'],['study'])
        self.assertEqual(self.plugin.bridge.agent.submit.call_args.kwargs['query'],'核对证据')
        for i,action in enumerate(('agent-status','pause','resume','cancel')):
            self.plugin.bridge.agent.submit.return_value={'request_id':str(uuid.uuid4()),'target_id':target,'submitted':True}
            event=Event('/asis '+action+' '+target)
            event.message_obj.message_id='control-'+str(i)
            asyncio.run(self.plugin.on_message(event))
            self.assertTrue(event.stopped)
            self.assertFalse(event.call_llm)
            self.assertEqual(self.plugin.bridge.agent.submit.call_args.kwargs['target_id'],target)

    def test_specialist_command_selects_role_sources_and_refuses_unknown_mode(self):
        self.bind()
        self.plugin.bridge.agent.submit=Mock(return_value={
            'request_id':str(uuid.uuid4()),'target_id':str(uuid.uuid4()),'submitted':True})
        event=Event('/asis agent study,life team | 比较方向与作息约束')
        asyncio.run(self.plugin.on_message(event))
        call=self.plugin.bridge.agent.submit.call_args.kwargs
        self.assertEqual(call['mode'],'team')
        self.assertEqual(call['source_ids'],['study','life'])
        self.plugin.bridge.agent.submit.reset_mock()
        event=Event('/asis agent study shell | query')
        asyncio.run(self.plugin.on_message(event))
        self.plugin.bridge.agent.submit.assert_not_called()
        self.assertFalse(event.call_llm)

    def card_adapter(self):
        import lark_oapi as lark
        self.adapter.appid='cli_fixture'
        self.adapter.event_handler=lark.EventDispatcherHandler.builder('','').build()
        self.card_requests=[]
        async def reply(request):
            self.card_requests.append(request)
            return SimpleNamespace(success=lambda:True,data=SimpleNamespace(message_id='om_card'))
        async def patch(request):
            self.card_requests.append(request)
            return SimpleNamespace(success=lambda:True)
        self.adapter.lark_api=SimpleNamespace(im=SimpleNamespace(v1=SimpleNamespace(
            message=SimpleNamespace(areply=reply,apatch=patch))))

    def card_callback(self,action,form=None,**changes):
        import json
        session=self.plugin.card_store().db.execute('SELECT * FROM card_sessions').fetchone()
        value={'asis_card':session['id'],'revision':str(session['revision']),'action':action}
        value.update(changes.pop('value',{}))
        payload={'schema':'2.0','header':{'event_type':'card.action.trigger','app_id':changes.get('app','cli_fixture')},
            'event':{'operator':{'open_id':changes.get('owner','ou_owner')},'host':'im_message',
                'context':{'open_message_id':changes.get('message','om_card')},
                'action':{'value':value,'tag':'button','form_value':form or {}}}}
        return self.adapter.event_handler._do_without_validation(json.dumps(payload).encode())

    def test_bare_asis_sends_owner_card_once_and_sdk_callback_is_nonblocking(self):
        import json
        import time
        self.bind();self.card_adapter();jobs=[]
        async def process(job):jobs.append(job)
        self.plugin.process_card=process
        async def scenario():
            event=Event('/asis')
            await self.plugin.on_message(event);await self.plugin.on_message(event)
            self.assertFalse(event.call_llm)
            self.assertEqual(len(self.card_requests),1)
            request=self.card_requests[0]
            self.assertEqual(request.request_body.msg_type,'interactive')
            self.assertEqual(json.loads(request.request_body.content)['schema'],'2.0')
            started=time.monotonic()
            response=self.card_callback('run',{'question':'cache','sources':'study','mode':'research'})
            self.assertLess(time.monotonic()-started,.3)
            self.assertEqual(response.card.type,'raw')
            self.assertEqual(jobs,[])
            await asyncio.sleep(.15)
            self.assertEqual(len(jobs),1)
            self.assertEqual(jobs[0]['source_ids'],['study'])
            self.assertEqual(jobs[0]['mode'],'research')
        asyncio.run(scenario())

    def test_card_sdk_wrong_owner_application_and_forwarded_message_never_schedule(self):
        self.bind();self.card_adapter();jobs=[]
        async def process(job):jobs.append(job)
        self.plugin.process_card=process
        async def scenario():
            await self.plugin.on_message(Event('/asis'))
            form={'question':'cache','sources':'study','mode':'research'}
            for changed in ({'owner':'ou_other'},{'app':'cli_other'},{'message':'om_forward'}):
                response=self.card_callback('run',form,**changed)
                self.assertEqual(response.toast.type,'error')
            await asyncio.sleep(.15)
            self.assertEqual(jobs,[])
        asyncio.run(scenario())

    def test_card_callback_relay_completion_updates_original_card_without_private_disk_payload(self):
        import json
        from personal_asis.agent_channel import AgentRelay,aad
        from personal_asis.evidence import control_server,encrypt
        self.bind();self.card_adapter()
        relay=AgentRelay();server,path=control_server(self.plugin.home,relay,'agent.sock')
        self.addCleanup(path.unlink,missing_ok=True);self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        async def scenario():
            await self.plugin.on_message(Event('/asis'))
            self.card_callback('run',{'question':'SYNTHETIC_CARD_QUESTION','sources':'study','mode':'research'})
            for _ in range(100):
                await asyncio.sleep(.02)
                row=self.plugin.bridge.db.execute('SELECT submitted FROM agent_routes').fetchone()
                if row and row[0]:break
            self.assertIsNotNone(row);self.assertTrue(row[0])
            job=relay.poll('mac','a'*64)['job']
            self.assertEqual(job['mode'],'research')
            view={'target_id':job['target_id'],'state':'completed','delegation_state':'active',
                'committed_actions':3,'unresolved_executions':0,'usage':None,
                'result':{'answer':'SYNTHETIC_CARD_RESULT [E1]','uncertainty':'partial','citations':['E1'],
                    'evidence':[{'id':'E1','title':'Synthetic','source_id':'study','path_hint':'cache.md',
                        'line_start':2,'excerpt':'SYNTHETIC_CARD_EXCERPT'}]}}
            relay.complete('mac',{'request_id':job['request_id'],'lease':job['lease'],'status':'ready',
                'envelope':encrypt(view,job,aad(job))})
            route,value,digest=self.plugin.bridge.agent.pending()[0]
            state=await self.plugin.bridge.deliver(route,value,digest,
                lambda *a:self.module.PersonalAsis.send(self.plugin,*a))
            self.assertEqual(state,'sent')
            patched=self.card_requests[-1]
            self.assertEqual(patched.message_id,'om_card')
            self.assertIn('SYNTHETIC_CARD_RESULT',patched.request_body.content)
            self.assertEqual(json.loads(patched.request_body.content)['schema'],'2.0')
            self.assertEqual(self.plugin.bridge.agent.pending(),[])
            disk=b''.join(p.read_bytes() for p in self.plugin.home.glob('*.sqlite3*'))
            self.assertNotIn(b'SYNTHETIC_CARD_QUESTION',disk)
            self.assertNotIn(b'SYNTHETIC_CARD_RESULT',disk)
        asyncio.run(scenario())

    def test_card_sdk_preserves_other_callback_and_old_resume_cannot_run_twice(self):
        import lark_oapi as lark
        from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTriggerResponse
        self.bind();self.card_adapter();jobs=[]
        async def process(job):jobs.append(job)
        self.plugin.process_card=process
        async def scenario():
            previous=lark.EventDispatcherHandler.builder('','').register_p2_card_action_trigger(
                lambda data:P2CardActionTriggerResponse({'toast':{'type':'info','content':'other'}})).build()
            self.adapter.event_handler._callback_processor_map.update(previous._callback_processor_map)
            await self.plugin.on_message(Event('/asis'))
            self.card_callback('run',{'question':'cache','sources':'study','mode':'team'})
            self.card_callback('resume');self.card_callback('pause')
            old=self.card_callback('resume',value={'revision':'1'})
            self.assertIn('旧操作',old.toast.content)
            await asyncio.sleep(.15)
            self.assertEqual([j['action'] for j in jobs],['run','resume','pause'])
        asyncio.run(scenario())

    def test_agent_foreign_owner_or_group_cannot_enqueue_work(self):
        self.bind()
        self.plugin.bridge.agent.submit=Mock()
        for event in (Event('/asis agent life | question',sender='ou_other'),
                      Event('/asis agent life | question',private=False),
                      Event('/asis pause '+str(uuid.uuid4()),platform='qq')):
            asyncio.run(self.plugin.on_message(event))
            self.assertTrue(event.stopped)
            self.assertFalse(event.call_llm)
        self.plugin.bridge.agent.submit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
