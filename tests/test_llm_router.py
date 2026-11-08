import asyncio
from datetime import datetime
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest

from personal_asis.llm_router import (BY_NAME, MODELS, State, Router, Failure,
    classify_error, day_bounds, estimate, fingerprint, ordered_models, task_for)


def answer(text='合成回答', **kw):
    return NS(completion_text=text, role='assistant', tools_call_name=[], usage=None, **kw)


class QuotaTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.now=[datetime.fromisoformat('2026-11-08T10:00:00+08:00').timestamp()]
        self.path=Path(self.tmp.name)/'router.sqlite3'
        self.state=State(self.path,clock=lambda:self.now[0],startup_cooldown=0)
        self.addCleanup(self.state.db.close)
        self.lite=BY_NAME['gemini-3.5-flash-lite']

    def test_atomic_minute_reservation_and_actual_usage(self):
        a,_=self.state.reserve(self.lite,190000,'daily')
        self.assertIsNotNone(a)
        self.assertEqual(self.state.reserve(self.lite,20000,'daily')[1],'local_tpm')
        self.state.finish(a,actual=50000)
        self.assertIsNotNone(self.state.reserve(self.lite,20000,'daily')[0])
        self.now[0]+=61
        self.assertIsNotNone(self.state.reserve(self.lite,190000,'daily')[0])
        self.assertEqual(self.path.stat().st_mode & 0o777,0o600)

    def test_two_connections_cannot_oversubscribe(self):
        other=State(self.path,clock=lambda:self.now[0],startup_cooldown=0)
        self.addCleanup(other.db.close)
        self.state.reserve(self.lite,150000,'daily')
        self.assertEqual(other.reserve(self.lite,60000,'daily')[1],'local_tpm')

    def test_flash_reserve_for_complex(self):
        flash=BY_NAME['gemini-3.8-flash']
        for _ in range(16):
            self.assertIsNotNone(self.state.reserve(flash,100,'complex')[0]);self.now[0]+=61
        self.assertEqual(self.state.reserve(flash,100,'daily')[1],'local_daily_quota')
        self.assertIsNotNone(self.state.reserve(flash,100,'complex')[0])

    def test_daily_cooldown_persists_and_resets(self):
        a,_=self.state.reserve(self.lite,100,'daily')
        self.state.finish(a,error=Failure('daily_quota',429))
        other=State(self.path,clock=lambda:self.now[0],startup_cooldown=0)
        self.addCleanup(other.db.close)
        self.assertEqual(other.reserve(self.lite,100,'daily')[1],'daily_quota')
        self.now[0]=day_bounds(self.now[0])[1]+1
        self.assertIsNotNone(other.reserve(self.lite,100,'daily')[0])

    def test_dst_23_and_25_hour_days(self):
        for timestamp,hours in [('2026-03-08T12:00:00-07:00',23),('2026-11-01T12:00:00-08:00',25)]:
            start,end=day_bounds(datetime.fromisoformat(timestamp).timestamp())
            self.assertEqual(end-start,hours*3600)

    def test_unknown_429_is_only_minute_cooldown(self):
        a,_=self.state.reserve(self.lite,100,'daily')
        self.state.finish(a,error=Failure('rate_limit',429))
        self.now[0]+=61
        self.assertIsNotNone(self.state.reserve(self.lite,100,'daily')[0])

    def test_unavailable_backoff_and_shared_bucket(self):
        self.state.merge_bucket(self.lite.name,'shared-lite')
        other=BY_NAME['gemini-3.1-flash-lite']
        self.state.merge_bucket(other.name,'shared-lite')
        a,_=self.state.reserve(self.lite,100,'daily')
        self.state.finish(a,error=Failure('unavailable',503))
        self.assertEqual(self.state.reserve(other,100,'daily')[1],'unavailable')
        self.now[0]+=61
        a,_=self.state.reserve(other,100,'daily')
        self.state.finish(a,error=Failure('unavailable',503))
        row=self.state.db.execute('SELECT until FROM health').fetchone()
        self.assertEqual(row[0]-self.now[0],120)

    def test_auth_isolates_source_and_startup_is_not_false_daily_exhaustion(self):
        a,_=self.state.reserve(self.lite,100,'daily');self.state.finish(a,error=Failure('auth',401))
        self.assertEqual(self.state.reserve(BY_NAME['gemini-3.1-flash-lite'],100,'daily')[1],'auth')
        cold=State(Path(self.tmp.name)/'cold.sqlite3',clock=lambda:self.now[0])
        self.addCleanup(cold.db.close)
        self.assertEqual(cold.reserve(self.lite,100,'daily')[1],'startup_cooldown')
        self.assertEqual(cold.status()['models'],[])

    def test_error_parser_preserves_only_allowed_facts(self):
        err=NS(code=429,response_json={'error':{'message':'secret-key', 'details':[
            {'retryDelay':'24s'}, {'violations':[{'quotaId':'GenerateRequestsPerDayPerProjectPerModel-FreeTier',
                'quotaDimensions':{'model':'shared-lite'}}]}]}})
        result=classify_error(err)
        self.assertEqual((result.kind,result.wait,result.bucket),('daily_quota',24,'shared-lite'))
        self.assertNotIn('secret-key',str(result))
        self.assertTrue(classify_error(TimeoutError()).terminal)
        self.assertTrue(classify_error(ConnectionError()).terminal)
        self.assertTrue(classify_error(NS(status_code=504)).terminal)
        self.assertEqual(classify_error(NS(status_code=504)).kind,'timeout')

    def test_configuration_repair_clears_only_configuration_quarantine(self):
        self.state.config_version('old')
        a,_=self.state.reserve(self.lite,100,'daily');self.state.finish(a,error=Failure('auth',401))
        self.state.config_version('new')
        a,_=self.state.reserve(self.lite,100,'daily');self.assertIsNotNone(a)
        self.state.finish(a,error=Failure('daily_quota',429))
        self.state.config_version('newer')
        self.assertEqual(self.state.reserve(self.lite,100,'daily')[1],'daily_quota')


class RoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.state=State(Path(self.tmp.name)/'s.sqlite3',startup_cooldown=0)
        self.addCleanup(self.state.db.close)
        self.calls=[]

    async def send(self, model, messages, tools, task):
        self.calls.append((model.name,messages,tools,task))
        return answer()

    def messages(self,text='帮我查询最近记录'):
        return [dict(role='system',content='合成规则'),dict(role='user',content=text)]

    async def test_short_message_is_not_sufficient_for_gemma(self):
        self.assertEqual(task_for(self.messages('提醒我')),'daily')
        self.assertEqual(task_for(self.messages('你好')),'simple')
        self.assertEqual(task_for(self.messages('你好'),'daily'),'daily')
        self.assertEqual(task_for(self.messages('深入分析这篇文章')),'complex')
        chain=self.messages('看看系统')+[dict(role='assistant',tool_calls=[
            {'function':{'name':'astrbot_execute_shell'}}]),dict(role='tool',content='合成结果')]
        self.assertEqual(task_for(chain),'complex')

    async def test_empty_enabled_model_set_sends_nothing(self):
        with self.assertRaises(Failure):
            await Router(self.state,self.send,available=[]).generate(self.messages(),None)
        self.assertEqual(self.calls,[])

    async def test_gemma_simple_and_tools_not_discarded_for_regular_request(self):
        router=Router(self.state,self.send)
        tools=NS(empty=lambda:False,get_func_desc_openai_style=lambda:[{'name':'life_organize'}])
        await router.generate(self.messages('你好'),tools)
        self.assertEqual(self.calls[0][0],'gemma-4-26b-a4b-it');self.assertIsNone(self.calls[0][2])
        self.calls.clear()
        await router.generate(self.messages('/life 今天冥想完成'),tools)
        self.assertEqual(self.calls[0][0],'gemini-3.5-flash-lite');self.assertIs(self.calls[0][2],tools)

    async def test_flash_exhaustion_falls_to_lite_before_paid(self):
        for m in MODELS:
            if m.pool in ('flash','spare_flash'):
                a,_=self.state.reserve(m,1,'complex');self.state.finish(a,error=Failure('daily_quota',429))
        await Router(self.state,self.send).generate(self.messages('综合分析'),'dummy' if False else None)
        self.assertEqual(self.calls[0][0],'gemini-3.5-flash-lite')

    async def test_two_free_attempts_then_mimo_then_deepseek(self):
        async def failed(model,messages,tools,task):
            self.calls.append(model.name)
            if model.name=='deepseek-v4-flash':return answer()
            raise Failure('unavailable',503)
        result=await Router(self.state,failed).generate(self.messages(),None)
        self.assertEqual(self.calls,['gemini-3.5-flash-lite','gemini-3.1-flash-lite','mimo-v2.6-flash','deepseek-v4-flash'])
        self.assertEqual(result.asis_router_model,'deepseek-v4-flash')
        self.assertEqual(result.completion_text,'合成回答')

    async def test_unknown_timeout_does_not_fallback(self):
        async def failed(model,*args):
            self.calls.append(model.name);raise TimeoutError()
        with self.assertRaises(Failure):await Router(self.state,failed).generate(self.messages(),None)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.state.status()['recent'][0]['status'],'unknown')

    async def test_tool_only_response_has_no_text_and_is_not_retried(self):
        async def send(*args):
            self.calls.append(args)
            return NS(completion_text=None,role='tool',tools_call_name=['life_organize'],usage=None)
        result=await Router(self.state,send).generate(self.messages(),None)
        self.assertEqual(result.tools_call_name,['life_organize'])
        self.assertEqual(len(self.calls),1)

    async def test_cancel_before_send_and_during_send(self):
        event=asyncio.Event();event.set()
        with self.assertRaises(asyncio.CancelledError):
            await Router(self.state,self.send).generate(self.messages(),None,abort=event)
        self.assertEqual(self.calls,[])
        async def cancelled(*args):raise asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await Router(self.state,cancelled).generate(self.messages(),None)
        self.assertEqual(self.state.status()['recent'][0]['error'],'cancelled')

    async def test_tool_results_are_preserved_across_fallback_without_execution(self):
        messages=self.messages()+[dict(role='assistant',tool_calls=[{'id':'a','function':{'name':'calendar_propose'}}]),
                                  dict(role='tool',tool_call_id='a',content='already-proposed')]
        original=json.loads(json.dumps(messages))
        async def send(model,msg,*args):
            self.calls.append(json.loads(json.dumps(msg)))
            if len(self.calls)==1:raise Failure('rate_limit',429)
            return answer()
        await Router(self.state,send).generate(messages,None)
        self.assertEqual(self.calls,[original,original]);self.assertEqual(messages,original)

    async def test_modality_filter_and_large_gemma_exclusion(self):
        msg=self.messages('你好');msg[0]['content']='规则'*4000
        await Router(self.state,self.send).generate(msg,None)
        self.assertEqual(self.calls[0][0],'gemini-3.5-flash-lite')
        msg=self.messages()+[dict(role='user',content=[dict(type='image_url',image_url={'url':'https://example.test/image'})])]
        router=Router(self.state,self.send,available=['deepseek-v4-flash'])
        with self.assertRaises(Failure):await router.generate(msg,None)

    async def test_outbound_summary_cache_coverage_and_raw_history_unchanged(self):
        messages=[dict(role='system',content='必须保留的规则')]
        for i in range(12):
            messages.extend([dict(role='user',content=('历史资料。'*650)+str(i)),dict(role='assistant',content='历史回应')])
        messages.append(dict(role='user',content='现在的问题'))
        before=fingerprint(messages)
        router=Router(self.state,self.send)
        await router.generate(messages,None,scope='synthetic')
        self.assertEqual(fingerprint(messages),before)
        self.assertTrue(any(c[3]=='summary' for c in self.calls))
        final=self.calls[-1][1]
        self.assertIn('覆盖旧消息',json.dumps(final,ensure_ascii=False))
        self.assertIn('现在的问题',json.dumps(final,ensure_ascii=False))
        self.assertLessEqual(estimate(final),32768)
        count=sum(c[3]=='summary' for c in self.calls)
        await router.generate(messages,None,scope='synthetic')
        self.assertEqual(sum(c[3]=='summary' for c in self.calls),count)
        self.state.invalidate('synthetic')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM summaries').fetchone()[0],0)

    async def test_mandatory_current_turn_allows_64k_then_rejects(self):
        router=Router(self.state,self.send)
        await router.generate(self.messages('字'*25000),None)
        self.assertEqual(self.calls[-1][3],'complex')
        self.calls.clear()
        with self.assertRaisesRegex(Failure,'context_too_large'):
            await router.generate(self.messages('字'*60000),None)
        self.assertEqual(self.calls,[])

    async def test_summary_failure_stops_dependent_generation(self):
        async def send(*args):self.calls.append(args);raise Failure('unknown')
        messages=[]
        for _ in range(15):messages.extend([dict(role='user',content='资料。'*1000),dict(role='assistant',content='回应')])
        messages.append(dict(role='user',content='当前问题'))
        with self.assertRaises(Failure):await Router(self.state,send).generate(messages,None)
        self.assertEqual(len(self.calls),1)

    async def test_incremental_summary_reuses_matching_prefix(self):
        messages=[dict(role='system',content='合成规则')]
        for i in range(12):
            messages.extend([dict(role='user',content='历史内容。'*650+str(i)),dict(role='assistant',content='历史回应')])
        messages.append(dict(role='user',content='现在的问题'))
        router=Router(self.state,self.send)
        await router.generate(messages,None,scope='incremental')
        self.calls.clear()
        messages.extend([dict(role='assistant',content='本次回应'),dict(role='user',content='新增资料。'*700)])
        await router.generate(messages,None,scope='incremental')
        summary_call=next(c for c in self.calls if c[3]=='summary')
        self.assertIn('已有摘要',summary_call[1][-1]['content'])
        self.assertLess(estimate(summary_call[1]),20000)

    async def test_large_history_token_estimation_scales_linearly(self):
        from unittest.mock import patch
        from personal_asis import llm_router
        messages=[dict(role='system',content='规则')]
        for i in range(200):
            messages.extend([dict(role='user',content='合成历史。'*250+str(i)),dict(role='assistant',content='回应')])
        messages.append(dict(role='user',content='当前问题'))
        calls=[]
        real_estimate=llm_router.estimate
        def counted(value):
            if isinstance(value,str):calls.append(len(value))
            return real_estimate(value)
        with patch.object(llm_router,'estimate',counted):
            await Router(self.state,self.send).generate(messages,None)
        # A suffix-per-turn implementation visits dozens of times more text.
        self.assertLess(sum(calls),12*len(json.dumps(messages,ensure_ascii=False)))


if __name__=='__main__':unittest.main()
