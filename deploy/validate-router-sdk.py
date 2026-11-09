"""Actual installed AstrBot SDK; synthetic providers/tools; network forbidden."""
import asyncio
import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from unittest.mock import patch

sys.path.insert(0, sys.argv[1])
adapter=importlib.import_module('astrbot_plugin_smart_router.provider')
core=importlib.import_module('astrbot_plugin_smart_router.llm_router')


async def main():
    from astrbot.core.agent.tool import FunctionTool, ToolSet
    from astrbot.api.star import Context
    from astrbot.api.event import AstrMessageEvent
    from astrbot.core.platform.astrbot_message import AstrBotMessage
    from astrbot.core.platform.platform_metadata import PlatformMetadata
    from astrbot.core.provider.entities import LLMResponse, TokenUsage
    from astrbot.core.agent.message import TextPart
    from google.genai import types

    registered=importlib.import_module('astrbot.core.provider.register').provider_cls_map
    assert registered['asis_smart_router'].cls_type is adapter.SmartProvider
    for profile in ('auto','complex','summary'):
        p=adapter.SmartProvider(dict(type='asis_smart_router',id='asis_router/'+profile,model=profile),{})
        assert p.get_model()==profile and await p.get_models()==['auto','complex','summary']
        assert p.provider_config['max_context_tokens']==core.NATIVE_HISTORY_CAP

    # Real SDK repeats extra_user_content_parts on follow-up tool steps. They
    # are already in contexts and must never become a new metadata-only turn.
    captured=[]
    async def capture(messages, *args, **kwargs):
        captured.append(messages)
        return LLMResponse(role='assistant',completion_text='synthetic')
    reminder=TextPart(text='<system_reminder>Current datetime: synthetic</system_reminder>')
    greeting=[dict(role='user',content=[dict(type='text',text='你好'),reminder.model_dump()])]
    chain=[dict(role='user',content='深入分析材料'),
           dict(role='assistant',content='',tool_calls=[dict(id='test',type='function',
                function=dict(name='astrbot_execute_python',arguments='{}'))]),
           dict(role='tool',tool_call_id='test',content='synthetic result')]
    virtual=adapter.SmartProvider(dict(id='asis_router/auto',type='asis_smart_router',model='auto'),{})
    with patch.object(adapter,'runtime',return_value=NS(refresh=lambda:None,router=NS(generate=capture))):
        await virtual.text_chat(contexts=greeting,extra_user_content_parts=[reminder])
        await virtual.text_chat(contexts=chain,extra_user_content_parts=[reminder])
        await virtual.text_chat(prompt='你好',extra_user_content_parts=[reminder])
    assert captured[:2]==[greeting,chain]
    assert core.task_for(captured[0])=='simple' and core.task_for(captured[1])=='complex'
    assert len(captured[2])==1 and len(captured[2][0]['content'])==2

    # Native context management must leave full stored history alone. These
    # same settings are applied to the owner profile by activation.
    from astrbot.core.agent.context.config import ContextConfig
    from astrbot.core.agent.context.manager import ContextManager
    from astrbot.core.agent.message import Message
    from astrbot.core.astr_main_agent import MainAgentBuildConfig
    native=MainAgentBuildConfig(tool_call_timeout=10,**core.NATIVE_CONTEXT_SETTINGS)
    assert native.fallback_max_context_tokens==128000  # unknown config fields are not a reliable off switch
    manager=ContextManager(ContextConfig(max_context_tokens=p.provider_config['max_context_tokens'],
        enforce_max_turns=native.max_context_length))
    original_history=[Message(role='user',content='synthetic history '*50000),
                      Message(role='assistant',content='synthetic result')]
    native_compressor=manager.compressor
    class GuardProbe:
        calls=0
        def should_compress(self,*args):return native_compressor.should_compress(*args)
        async def __call__(self,messages):
            self.calls+=1
            raise AssertionError('native_compression_must_be_disabled')
    manager.compressor=GuardProbe()
    assert await manager.process(original_history) is original_history
    assert manager.compressor.calls==0

    # Owner hooks and status are exercised without reading the real binding.
    with tempfile.TemporaryDirectory(prefix='asis-router-owner-sdk-') as temp:
        root=Path(temp)
        binding=root/'astrbot/data/config/astrbot_plugin_life_agent_config.json'
        binding.parent.mkdir(parents=True)
        binding.write_text(json.dumps(dict(owner_id='owner',owner_platform='synthetic')))
        async def current(**kwargs):return 'asis_router/auto'
        ctx=NS(provider_manager=NS(provider_sources_config=[],providers_config=[],get_provider_config_by_id=lambda *a,**kw:None),
               get_current_chat_provider_id=current)
        with patch.object(Path,'home',return_value=root):
            plugin_module=importlib.import_module('astrbot_plugin_smart_router.main')
            plugin=plugin_module.SmartRouterPlugin(ctx)
            await plugin.initialize()
            assert not adapter.runtime().router.available
            ctx.provider_manager.provider_sources_config.append(dict(id='google_gemini',enable=True))
            adapter.runtime().refresh()
            assert 'gemini-3.5-flash-lite' in adapter.runtime().router.available
            ctx.provider_manager.provider_sources_config[0]['enable']=False
            adapter.runtime().refresh()
            assert not adapter.runtime().router.available
            event=NS(is_private_chat=lambda:True,get_platform_id=lambda:'synthetic',
                get_sender_id=lambda:'owner',get_extra=lambda key:'saved',
                unified_msg_origin='synthetic:FriendMessage:owner',plain_result=lambda text:text)
            req=NS(conversation=NS(cid='synthetic-conversation'),model=None,system_prompt='')
            await plugin.hint(event,req)
            assert req.model.startswith('daily|')
            assert '工作上下文目标32K' in req.system_prompt
            assert await plugin.conversation_memory(event,action='recent') == '{"error": "conversation_memory_unavailable"}'
            from astrbot.core.message.message_event_result import MessageChain, MessageEventResult, ResultContentType
            from astrbot.core.message.components import Plain
            extras={}
            event.set_extra=lambda key,value:extras.update({key:value})
            event.get_extra=lambda key:extras.get(key)
            response=LLMResponse(role='assistant',result_chain=MessageChain().message('## 合成回复'))
            response.asis_router_model='deepseek-v4-flash'
            await plugin.attribute(event,response)
            original_chain=response.result_chain
            result=MessageEventResult(chain=list(original_chain.chain),result_content_type=ResultContentType.LLM_RESULT)
            event.get_result=lambda:result
            await plugin.label_reply(event)
            await plugin.label_reply(event)
            assert result.chain[0].text=='🐳\n\n## 合成回复'
            assert response.completion_text=='## 合成回复'
            assert original_chain.chain[0].text=='## 合成回复'
            for model,emoji in [('mimo-v2.6-flash','🍚'),('gemini-3.6-flash','💫'),
                                ('gemini-3.5-flash-lite','✨'),('gemma-4-31b-it','🧊')]:
                response.asis_router_model=model
                await plugin.attribute(event,response)
                result.chain=[Plain('合成回复')]
                await plugin.label_reply(event)
                assert result.chain[0].text==emoji+'\n\n合成回复'
            response.role='err'
            await plugin.attribute(event,response)
            result.chain=[Plain('本地错误说明')]
            await plugin.label_reply(event)
            assert result.chain[0].text=='本地错误说明'
            status=[v async for v in plugin.status(event)]
            assert len(status)==1 and '本地估算' in status[0]
            event.get_sender_id=lambda:'stranger'
            assert await plugin.conversation_memory(event)=='owner_required'
            stopped=[];event.stop_event=lambda:stopped.append(True)
            try:await plugin.hint(event,req)
            except ValueError:pass
            else:raise AssertionError('non_owner_router_request_must_be_rejected')
            assert stopped==[True]
            assert [v async for v in plugin.status(event)]==[]
            await plugin.terminate()

    # Single-shot Google request retains tools and returns native signature/usage.
    google=adapter.SingleGoogle(dict(type='googlegenai_chat_completion',id='synthetic-google',
        model='gemini-3.5-flash-lite',key=['synthetic-key-not-real'],timeout=5,
        gm_thinking_config={'level':'LOW'},gm_resp_image_modal=False),{})
    original=google.client
    try:
        response=types.GenerateContentResponse(response_id='synthetic',candidates=[types.Candidate(
            content=types.Content(role='model',parts=[types.Part(
                function_call=types.FunctionCall(name='life_organize',args={'value':'synthetic'},id='one'),
                thought_signature=b'synthetic-signature')]))],
            usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=100,
                cached_content_token_count=20,candidates_token_count=5))
        generate=AsyncMock(return_value=response)
        google.client=NS(aio=NS(models=NS(generate_content=generate)))
        class SyntheticTool(FunctionTool):
            async def call(self,context,value):return 'synthetic'
        tool=SyntheticTool(name='life_organize',description='Synthetic only',parameters={
            'type':'object','properties':{'value':{'type':'string'}},'required':['value']})
        answer=await google.text_chat(prompt='Synthetic test',func_tool=ToolSet([tool]),request_max_retries=1)
        assert generate.await_count==1 and answer.tools_call_name==['life_organize']
        assert answer.tools_call_extra_content['one']['google']['thought_signature']
        assert answer.usage.input_other==80 and answer.usage.input_cached==20
        config=generate.await_args.kwargs['config']
        assert config.thinking_config.thinking_level==types.ThinkingLevel.LOW
        assert config.automatic_function_calling.disable is True and config.tools
        generate.side_effect=TimeoutError()
        try:await google.text_chat(prompt='Synthetic timeout',request_max_retries=1)
        except core.Failure as error:assert error.terminal
        else:raise AssertionError('unknown_must_stop')
        assert generate.await_count==2
    finally:
        await original.aio.aclose()

    # Run two real native tool loops. A generated tool is executed once, then
    # the next model request encounters a quota error and changes model.
    loops=[]
    for tool_name in ('life_organize','google_calendar_propose_write','astrbot_execute_python'):
        with tempfile.TemporaryDirectory(prefix='asis-router-sdk-') as temp:
            state=core.State(Path(temp)/'quota.sqlite3',startup_cooldown=0)
            calls=[];executed=[]
            async def send(model,messages,tools,task):
                calls.append((model.name,messages))
                if len(calls)==1:
                    return LLMResponse(role='tool',tools_call_name=[tool_name],
                        tools_call_args=[{'value':'synthetic'}],tools_call_ids=['once'],
                        usage=TokenUsage(input_other=100,output=10))
                if len(calls)==2:
                    raise core.Failure('rate_limit',429)
                assert any(m.get('role')=='tool' for m in messages)
                assert messages[-1]['role']=='tool', 'extra metadata must not follow the current tool result'
                return LLMResponse(role='assistant',completion_text='合成完成',usage=TokenUsage(input_other=100,output=10))
            router=core.Router(state,send)
            adapter._runtime=NS(router=router,state=state,refresh=lambda:None)
            virtual=adapter.SmartProvider(dict(id='asis_router/auto',type='asis_smart_router',model='auto'),{})
            async def get_provider(provider_id):return virtual
            class TestContext(Context):
                def __init__(self):self.provider_manager=NS(get_provider_by_id=get_provider)
            class Once(FunctionTool):
                async def call(self,context,value):
                    executed.append(value)
                    return 'synthetic_tool_already_completed'
            message=AstrBotMessage();message.type='FriendMessage';message.message_id='synthetic'
            message.message=[];message.sender=NS(user_id='synthetic',nickname='Synthetic')
            event=AstrMessageEvent('整理合成记录',message,
                PlatformMetadata(name='synthetic',description='Synthetic',id='synthetic',support_proactive_message=False),'synthetic')
            from astrbot.core.agent.runners.tool_loop_agent_runner import ToolLoopAgentRunner
            reset=ToolLoopAgentRunner.reset
            async def with_time(self,*args,**kwargs):
                kwargs['request'].extra_user_content_parts=[reminder]
                return await reset(self,*args,**kwargs)
            with patch.object(ToolLoopAgentRunner,'reset',with_time):
                result=await TestContext().tool_loop_agent(event=event,chat_provider_id='asis_router/auto',
                    prompt='整理合成记录',tools=ToolSet([Once(name=tool_name,description='No real effects',
                        parameters={'type':'object','properties':{'value':{'type':'string'}},'required':['value']})]),
                    max_steps=4,request_max_retries=1,fallback_providers=[])
            assert executed==['synthetic'] and len(calls)==3, dict(executed=executed,
                models=[c[0] for c in calls],role=result.role,text=result.completion_text)
            assert result.completion_text=='合成完成'
            assert result.asis_router_model==calls[-1][0]
            if tool_name=='astrbot_execute_python':
                assert [c[0] for c in calls]==['gemini-3.5-flash-lite','gemini-3.8-flash','gemini-3.6-flash']
            else:
                assert calls[0][0]==calls[1][0] and calls[1][0]!=calls[2][0]
            loops.append(tool_name)
            state.db.close()
    adapter._runtime=None
    print(json.dumps(dict(sdk='passed',virtual_providers=3,single_shot_transport=True,
        signature_and_usage=True,owner_hooks=True,source_disable_refresh=True,extra_parts_replay=False,
        native_loops=loops,native_history_untouched=True,real_generations=0,platform_messages=0)))


asyncio.run(main())
