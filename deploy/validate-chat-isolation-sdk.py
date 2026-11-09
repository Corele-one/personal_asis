"""Run installed Scheduler/background wake paths with synthetic state and no I/O."""
import asyncio
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from unittest.mock import patch

sys.path.insert(0, sys.argv[1])
from astrbot.core.star.context import Context
from astrbot.core.cron.manager import CronJobManager
from astrbot.core.astr_agent_tool_exec import FunctionToolExecutor
from astrbot.core.astr_agent_context import AstrAgentContext, AgentContextWrapper
from astrbot.core.cron.events import CronMessageEvent
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.agent.tool import FunctionTool, ToolSet
from astrbot.core.provider.entities import ProviderRequest
from astrbot_plugin_life_agent.background_isolation import BackgroundIsolation
from astrbot_plugin_life_agent.main import LifeAgent

ORIGIN = 'synthetic:FriendMessage:owner'


class Conversations:
    def __init__(self):
        self.selected = {ORIGIN:'chat'}
        self.rows = {'chat':NS(cid='chat', history=json.dumps([dict(role='user',content='PRIVATE_CHAT_SENTINEL')]))}
        self.origins = {'chat':ORIGIN}
        self.writes = []

    async def get_curr_conversation_id(self, origin):
        return self.selected.get(origin)

    async def new_conversation(self, origin, *args, **kwargs):
        cid = 'execution-'+str(len(self.rows))
        self.rows[cid] = NS(cid=cid,history='[]')
        self.selected[origin] = cid
        self.origins[cid] = origin
        return cid

    async def get_conversation(self, origin, cid):
        assert self.origins[cid] == origin
        return self.rows[cid]

    async def update_conversation(self, origin, cid, history):
        assert self.origins[cid] == origin
        self.rows[cid].history = json.dumps(history)
        self.writes.append((origin,cid))


class SyntheticContext(Context):
    def __init__(self):
        self.conversation_manager = Conversations()
        self.cron_manager = CronJobManager.__new__(CronJobManager)
        self.cron_manager.ctx = self

    def get_config(self, **kwargs):
        return {'provider_settings':{}, 'admins_id':['owner']}

    def get_llm_tool_manager(self):
        return NS(get_builtin_tool=lambda cls:cls())

    async def send_message(self, *args, **kwargs):
        raise AssertionError('platform_transport_forbidden')


async def main():
    context = SyntheticContext()
    binding = dict(owner_platform='synthetic',owner_id='owner')
    isolation = BackgroundIsolation(context,binding)
    original_background = FunctionToolExecutor.__dict__['_wake_main_agent_for_background_result']
    isolation.install()
    built=[]
    async def build(**kwargs):
        event, req = kwargs['event'], kwargs['req']
        assert event.unified_msg_origin == ORIGIN
        assert req.conversation.cid != 'chat'
        assert 'PRIVATE_CHAT_SENTINEL' not in req.system_prompt
        assert not req.contexts
        assert isinstance(kwargs['plugin_context'], Context)
        # Event context also must use the copied SDK Context.
        assert event.context_obj is kwargs['plugin_context']
        built.append(req.conversation.cid)
        class Runner:
            async def step_until_done(self, count):
                assert count == 30
                await asyncio.sleep(0)
                yield None
            def get_final_llm_resp(self):
                return NS(role='assistant',completion_text='synthetic task receipt')
        return NS(agent_runner=Runner())
    try:
        with patch('astrbot.core.astr_main_agent.build_main_agent',side_effect=build):
            event = CronMessageEvent(context=context,session=MessageSession.from_str(ORIGIN),message='synthetic')
            run_context = AgentContextWrapper(context=AstrAgentContext(context=context,event=event))
            async def ordinary_chat():
                await asyncio.sleep(0)
                assert await context.conversation_manager.get_curr_conversation_id(ORIGIN) == 'chat'
                await context.conversation_manager.update_conversation(ORIGIN,'chat',history=[dict(role='user',content='NEW_CHAT_SENTINEL')])
            await asyncio.gather(
                context.cron_manager._woke_main_agent(message='synthetic scheduled task',session_str=ORIGIN,
                    extras={'cron_job':dict(id='synthetic-job',run_started_at='2026-11-09T08:00:00+08:00')},delivery_session_str=ORIGIN),
                FunctionToolExecutor._wake_main_agent_for_background_result(run_context,task_id='synthetic-tool',
                    tool_name='synthetic',result_text='completed tool result',tool_args={},note='done',summary_name='synthetic'),
                ordinary_chat())
        manager = context.conversation_manager
        assert len(set(built)) == 2
        assert manager.selected[ORIGIN] == 'chat'
        assert json.loads(manager.rows['chat'].history) == [dict(role='user',content='NEW_CHAT_SENTINEL')]
        for cid in built:
            assert manager.origins[cid].startswith('asis_background:OtherMessage:')
            report = json.loads(manager.rows[cid].history)
            assert len(report)==2 and report[1]['role']=='assistant'
        assert run_context.context.context is context
        # Actual SDK ToolSet clone: preserving library tools and the shared catalog.
        bot = LifeAgent.__new__(LifeAgent)
        bot.config = dict(capture_enabled=True)
        event = CronMessageEvent(context=context,session=MessageSession.from_str(ORIGIN),message='讨论PWA架构')
        tools = ToolSet([FunctionTool(name=n,description=n,parameters={'type':'object','properties':{}})
                         for n in ('life_organize','life_track','shared_knowledge')])
        req = ProviderRequest(func_tool=tools)
        bot.supply_life_tools(event,req)
        assert [t.name for t in req.func_tool.tools] == ['shared_knowledge']
        assert len(tools.tools)==3
    finally:
        isolation.uninstall()
    assert '_woke_main_agent' not in context.cron_manager.__dict__
    assert FunctionToolExecutor.__dict__['_wake_main_agent_for_background_result'] is original_background
    print(json.dumps(dict(actual_scheduler_and_background_paths=True,isolated_execution_histories=True,
        current_chat_and_concurrent_new_message_preserved=True,delivery_origin_preserved=True,
        installed_sdk_context_type=True,actual_toolset_filtered_without_catalog_mutation=True,
        uninstall_restores_sdk=True,real_model_calls=0,real_messages_sent=0)))


asyncio.run(main())
