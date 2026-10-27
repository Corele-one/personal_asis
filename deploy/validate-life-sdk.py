"""Use the installed AstrBot SDK with temporary synthetic state; transport forbidden."""
import asyncio
import importlib
import json
from pathlib import Path
import sys
import tempfile
import types
from unittest.mock import patch

sys.path.insert(0, sys.argv[1])
module = importlib.import_module('astrbot_plugin_life_agent.main')
tools = ('organize', 'life_context', 'recent', 'workspace_tool', 'track', 'progress', 'focus','shared_knowledge')
assert all(callable(getattr(module.LifeAgent, name)) for name in tools)


async def fixture():
    async def forbidden(*args, **kwargs):
        raise AssertionError('real_transport_forbidden_in_sdk_fixture')
    with tempfile.TemporaryDirectory(prefix='asis-sdk-synthetic-') as tmp:
        with patch.object(Path, 'home', return_value=Path(tmp).resolve()):
            bot = module.LifeAgent(types.SimpleNamespace(send_message=forbidden),
                                   dict(owner_platform='synthetic', owner_id='owner'))
        try:
            extras = {}
            event = types.SimpleNamespace(message_str='/life 冥想完成，开始学习模拟滤波器',
                message_obj=types.SimpleNamespace(message_id='synthetic-learning'),
                unified_msg_origin='synthetic:FriendMessage:owner',
                is_private_chat=lambda: True, get_platform_id=lambda: 'synthetic',
                get_sender_id=lambda: 'owner', set_extra=lambda k,v: extras.update({k:v}),
                get_extra=lambda k: extras.get(k), plain_result=lambda s: s)
            replies = [reply async for reply in bot.collect(event)]
            assert replies == []
            bot.capture(event)
            r = bot.store.recent()[0]
            assert r['tracking']['habits'][0]['status'] == 'done'
            assert r['tracking']['learning'][0]['topic'] == '模拟滤波器'
            result = await bot.track(event, learning_json='[]')
            assert json.loads(result)['saved_on'] == 'VPS'
            request = types.SimpleNamespace(system_prompt='')
            await bot.instructions(event, request)
            assert 'life_track' in request.system_prompt
            assert '08:00' in request.system_prompt
            event.message_str = '帮我持续跟进实验进展'
            event.message_obj.message_id = 'synthetic-focus'
            goal = json.loads(await bot.focus(event, '合成实验', next_step='核对测量条件'))
            assert goal['title'] == '合成实验'
            goal_request = types.SimpleNamespace(system_prompt='')
            await bot.instructions(event, goal_request)
            assert goal['id'] in goal_request.system_prompt
            current = json.loads(await bot.progress(event))
            assert len(current['goals']) == 1
            shared = importlib.import_module('astrbot_plugin_life_agent.shared_store')
            sources = importlib.import_module('astrbot_plugin_life_agent.shared_sources')
            key = shared.identity('synthetic-sdk-note')
            body = sources.document_bodies('study','Note/synthetic.md','合成共享笔记','合成共享电路资料')[0]
            with shared.SharedStore(bot.home/'shared.sqlite3','vps') as library:
                library.receive(dict(changes=[dict(origin='mac',collection='notes',id=key,version=1,body=body)],cursor=1,more=False),'mac')
            found = json.loads(await bot.shared_knowledge(event,'search',query='共享电路'))
            assert found['results'][0]['id'] == key
            read = json.loads(await bot.shared_knowledge(event,'read',record_id=key))
            assert read['body']['text'] == '合成共享电路资料'
            note = json.loads(await bot.shared_knowledge(event,'annotate',record_id=key,text='合成的本人补充'))
            same = json.loads(await bot.shared_knowledge(event,'annotate',record_id=key,text='合成的本人补充'))
            assert note == same
            # PWA uses the installed native tool executor with a synthetic model
            # boundary; no provider generation or platform dispatch occurs.
            from astrbot.core.astr_agent_context import AgentContextWrapper, AstrAgentContext
            from astrbot.core.astr_agent_tool_exec import FunctionToolExecutor
            from astrbot_plugin_life_agent.life_feedback import LifeFeedback
            from astrbot_plugin_life_agent.feedback_agent import respond
            feedback=LifeFeedback(bot.store)
            bot.attention.configure(bot.bedtime_owner(),event.unified_msg_origin,False)
            target=bot.store.get(r['id'])
            feedback.submit(dict(id='a'*32,thread='b'*32,text='这条冥想是误判，请去掉。',record_id=r['id'],revision=target['revision']))
            job=feedback.claim()
            class SyntheticContext(module.Context):
                def __init__(self):
                    pass
                async def get_current_chat_provider_id(self,umo):
                    assert umo == event.unified_msg_origin
                    return 'synthetic-no-generation'
                async def tool_loop_agent(self,**kwargs):
                    assert kwargs['max_steps']==4
                    tool=kwargs['tools'].get_tool('correct_record')
                    assert tool is not None
                    context=AgentContextWrapper(context=AstrAgentContext(context=self,event=kwargs['event']),tool_call_timeout=10)
                    outputs=[v async for v in FunctionToolExecutor.execute(tool,context,action='clear_habit',habit='meditation')]
                    assert outputs
                    return types.SimpleNamespace(completion_text='已去掉误判。')
            original_context=bot.context
            bot.context=SyntheticContext()
            reply=await respond(bot,feedback,job)
            feedback.finish(job,reply=reply)
            assert feedback.thread('b'*32)[0]['effect']['action']=='clear_habit'
            assert bot.store.get(r['id'])['text']==target['text']
            bot.context=original_context
            event.message_str='实践作业要求阅读完成后写报告'
            event.message_obj.message_id='synthetic-memory'
            awaitable=[reply async for reply in bot.collect(event)]
            assert awaitable==[]
            assert await bot.track(event)=='explicit_life_entry_required'
            assert bot.store.get(bot.rid(event))['capture_source']=='conversation'
            event.get_sender_id = lambda: 'stranger'
            assert await bot.track(event) == 'owner_or_capture_required'
            assert await bot.shared_knowledge(event,'search',query='共享电路') == 'owner_required'
        finally:
            bot.store.close()


asyncio.run(fixture())
print(json.dumps(dict(actual_sdk_import=True, registered_tool_methods=len(tools),
    synthetic_owner_tracking=True, synthetic_goal=True, synthetic_prompt=True,
    synthetic_shared_search_read_annotation=True, synthetic_pwa_feedback_executor=True, conversation_memory_isolated=True,
    stranger_rejected=True, real_model_calls=0, real_messages_sent=0)))
