"""Bounded synthetic live checks. No platform transport or real personal content.

The durable task-wide budget is consumed BEFORE each SDK generation, including
failed/unknown requests; running the script again does not reset the 16-call cap.
"""
import asyncio
import json
import logging
from pathlib import Path
import sqlite3
import sys
import time
from types import SimpleNamespace as NS

logging.disable(logging.CRITICAL)

sys.path.insert(0, sys.argv[1])
from astrbot_plugin_smart_router import provider
from astrbot_plugin_smart_router.llm_router import MODELS, BY_NAME, classify_error


async def main():
    from astrbot.core.agent.tool import FunctionTool, ToolSet
    data=Path('/home/mac/astrbot/data')
    config=json.loads((data/'cmd_config.json').read_text(encoding='utf-8-sig'))
    class Manager:
        provider_sources_config=config['provider_sources']
        def get_provider_config_by_id(self,identifier,merged=False):
            item=next((p for p in config['provider'] if p.get('id')==identifier),None)
            if not item:return None
            source=next((p for p in config['provider_sources'] if p.get('id')==item.get('provider_source_id')), {})
            return {**source,**item}
    provider.bind(NS(provider_manager=Manager()))
    runtime=provider.runtime()
    budget=sqlite3.connect(Path.home()/'.local/share/personal-asis-router/live-budget-20261108.sqlite3',isolation_level=None)
    budget.execute('CREATE TABLE IF NOT EXISTS calls(id INTEGER PRIMARY KEY,model TEXT,started REAL,status TEXT)')
    Path(budget.execute('PRAGMA database_list').fetchone()[2]).chmod(0o600)
    reports=[]

    async def call(model_name,messages,tools=None,task='daily'):
        model=BY_NAME[model_name]
        budget.execute('BEGIN IMMEDIATE')
        count=budget.execute('SELECT count(*) FROM calls').fetchone()[0]
        if count>=16:
            budget.execute('ROLLBACK');raise RuntimeError('task_live_budget_exhausted')
        token=budget.execute('INSERT INTO calls(model,started,status) VALUES(?,?,?)',
                              (model_name,time.time(),'sending')).lastrowid
        budget.execute('COMMIT')
        # Validation calls are accounted in production quota history, even when
        # upstream quota was consumed outside this Router before installation.
        from astrbot_plugin_smart_router.llm_router import estimate
        attempt=None
        previous=runtime.state.startup_until
        runtime.state.startup_until=0
        try:
            attempt,blocked=runtime.state.reserve(model,estimate(messages)+1000,task,'live_validation')
            if blocked:
                budget.execute('DELETE FROM calls WHERE id=?',(token,))
                reports.append(dict(model=model_name,status='skipped',reason=blocked))
                return None
            at=time.monotonic()
            result=await asyncio.wait_for(runtime.send(model,messages,tools,task),60)
            usage=getattr(result,'usage',None)
            actual=(usage.input_other+usage.input_cached) if usage else None
            runtime.state.finish(attempt,actual=actual)
            budget.execute('UPDATE calls SET status=? WHERE id=?',('completed',token))
            reports.append(dict(model=model_name,status='completed',seconds=round(time.monotonic()-at,2),
                input_tokens=actual,output_tokens=getattr(usage,'output',None),
                tool_calls=len(result.tools_call_name or [])))
            return result
        except Exception as error:
            failure=classify_error(error)
            if attempt:
                if failure.bucket and not model.paid:runtime.state.merge_bucket(model_name,failure.bucket)
                runtime.state.finish(attempt,error=failure)
            budget.execute('UPDATE calls SET status=? WHERE id=?',('unknown' if failure.terminal else 'failed',token))
            reports.append(dict(model=model_name,status='unknown' if failure.terminal else 'failed',
                error=failure.kind,http=failure.status))
            return None
        finally:
            runtime.state.startup_until=previous

    selected=sys.argv[2:] or [m.name for m in MODELS]
    if selected in (['--router-context'], ['--native-time-route']):
        from astrbot_plugin_smart_router.llm_router import fingerprint,Failure
        async def counted_send(model,messages,tools,task):
            budget.execute('BEGIN IMMEDIATE')
            if budget.execute('SELECT count(*) FROM calls').fetchone()[0]>=16:
                budget.execute('ROLLBACK');raise Failure('live_budget_exhausted',terminal=True)
            token=budget.execute('INSERT INTO calls(model,started,status) VALUES(?,?,?)',
                (model.name,time.time(),'sending')).lastrowid
            budget.execute('COMMIT')
            started=time.monotonic()
            try:
                response=await runtime.send(model,messages,tools,task)
                budget.execute('UPDATE calls SET status=? WHERE id=?',('completed',token))
                usage=getattr(response,'usage',None)
                reports.append(dict(model=model.name,task=task,status='completed',
                    seconds=round(time.monotonic()-started,2),
                    input_tokens=(usage.input_other+usage.input_cached) if usage else None,
                    output_tokens=getattr(usage,'output',None)))
                return response
            except BaseException as error:
                failure=classify_error(error)
                status='unknown' if failure.terminal else 'failed'
                budget.execute('UPDATE calls SET status=? WHERE id=?',(status,token))
                reports.append(dict(model=model.name,task=task,status=status,error=failure.kind,http=failure.status))
                raise
        runtime.router.transport=counted_send
        runtime.state.startup_until=0
        if selected==['--native-time-route']:
            from astrbot.core.agent.message import TextPart
            reminder=TextPart(text='<system_reminder>Current datetime: synthetic</system_reminder>')
            messages=[dict(role='user',content=[dict(type='text',text='用Gemma 你好'),reminder.model_dump()])]
            test_name='native_time_route'
        else:
            messages=[dict(role='system',content='这是合成历史压缩验收，不含真人资料。最终只回复“检查完成”。')]
            for i in range(12):
                messages.extend([dict(role='user',content='合成资料：学习内容需要保留出处、疑问和进展。'*220+str(i)),
                                 dict(role='assistant',content='合成历史回应')])
            messages.append(dict(role='user',content='请只回复“检查完成”。'))
            test_name='router_context'
        before=fingerprint(messages)
        try:
            if test_name=='native_time_route':
                virtual=provider.SmartProvider(dict(id='asis_router/auto',type='asis_smart_router',model='auto'),{})
                response=await virtual.text_chat(contexts=messages,extra_user_content_parts=[reminder],
                    model='auto|synthetic-native-time-route')
                passed=(response.role!='err' and getattr(response,'asis_router_model','')=='gemma-4-26b-a4b-it'
                    and bool(response.completion_text))
            else:
                response=await runtime.router.generate(messages,None,scope='synthetic-live-compaction')
                passed=bool(response.completion_text)
            reports.append(dict(test=test_name,passed=passed,
                original_unchanged=fingerprint(messages)==before))
        except Exception as error:
            reports.append(dict(test=test_name,passed=False,error=classify_error(error).kind,
                original_unchanged=fingerprint(messages)==before))
    elif selected==['--tool']:
        class Probe(FunctionTool):
            async def call(self,context,value):raise AssertionError('model_check_does_not_execute_tools')
        tools=ToolSet([Probe(name='synthetic_probe',description='Synthetic compatibility probe, no external effects.',
            parameters={'type':'object','properties':{'value':{'type':'string'}},'required':['value']})])
        messages=[dict(role='user',content='This is a synthetic tool compatibility test. Call synthetic_probe exactly once with value="ok". Do not answer in prose yet.')]
        for name in ('gemini-3.5-flash-lite','gemini-3.1-flash-lite','mimo-v2.6-flash'):
            response=await call(name,messages,tools)
            if not response:continue
            if response.tools_call_name!=['synthetic_probe']:
                reports[-1]['tool_contract']='failed';break
            tool_id=response.tools_call_ids[0]
            tool_call=dict(id=tool_id,type='function',function=dict(name='synthetic_probe',
                arguments=json.dumps(response.tools_call_args[0])))
            extra=response.tools_call_extra_content.get(tool_id)
            if extra:tool_call['extra_content']=extra
            follow=messages+[dict(role='assistant',content=response.completion_text or '',tool_calls=[tool_call]),
                             dict(role='tool',tool_call_id=tool_id,content='{"ok":true,"synthetic":true}')]
            final=await call(name,follow,tools)
            reports[-1]['tool_roundtrip']=bool(final and final.completion_text and not final.tools_call_name)
            break
    else:
        for name in selected:
            if name not in BY_NAME:raise ValueError('known_model_required')
            task='complex' if BY_NAME[name].pool in ('flash','spare_flash') else 'daily'
            await call(name,[dict(role='user',content='合成兼容性测试：只回复“连接正常”，不要调用工具。')],task=task)
    result=dict(task_limit=16,calls_consumed=budget.execute('SELECT count(*) FROM calls').fetchone()[0],
        results=reports,platform_messages=0,real_note_writes=0,cost='provider_usage_only_no_price_estimate')
    receipt=Path.home()/'.local/share/personal-asis-router'/('live-receipt-'+str(time.time_ns())+'.json')
    receipt.write_text(json.dumps(result,ensure_ascii=False));receipt.chmod(0o600)
    print(json.dumps(result,ensure_ascii=False),flush=True)
    await runtime.close()


asyncio.run(main())
