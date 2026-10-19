import copy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from personal_asis import conversation as core, pa1
from personal_asis.conversation_tools import (submit, permission_reply, initialize, validate_context, PROTOCOL,
                                             ToolConversationHost, LIMITS)
from personal_asis.tool_registry import registry_v1, Tool, ToolRegistry, obj, text
from test_conversation import Provider, PI_AVAILABLE


def action(name, **args):
    return {'tool':name, 'arguments':args}


def supported():
    return {'status':'supported','answer':'原文支持这个结论 [E1]','citations':['E1'],'uncertainty':'部分正文，发布日期仅为来源报告。'}


class Web:
    def __init__(self, fail=False):
        self.calls=[];self.fail=fail
    def search_web(self, query, maximum=2, recency=None):
        self.calls.append(('search',query,maximum,recency))
        if self.fail:
            raise TimeoutError('PRIVATE_BACKEND_BODY')
        return {'status':'ok','results':[{'url':'https://example.com/research','title':'Synthetic primary source',
                'excerpt':'Discovery summary, not body evidence.','published_at':'2026-10-01',
                'publication_date_status':'provider_reported_unverified'}]}
    def fetch_web(self, url, maximum=600):
        self.calls.append(('fetch',url,maximum))
        return {'url':url,'requested_url':url,'title':'Synthetic source','excerpt':('Synthetic source explains cache coherence and its limitations. '*6)[:maximum],
                'source_type':'public_web','content_kind':'web_body','content_completeness':'partial',
                'published_at':'2026-10-01','publication_date_status':'provider_reported_unverified',
                'fetched_at':datetime.now(timezone.utc).isoformat(),'reader':'synthetic_local_validated'}


class RegistryTests(unittest.TestCase):
    def test_frozen_versioned_registry_and_strict_arguments(self):
        registry=registry_v1()
        self.assertEqual(len(registry.definitions()),5)
        with self.assertRaisesRegex(ValueError,'frozen'):
            registry.register(Tool('evil',1,'bad',obj({},[]),'evil'))
        with self.assertRaisesRegex(ValueError,'changed_no_retry'):
            registry.verify({'version':'old','fingerprint':'changed'})
        for name,args in [('search_web',{'query':'cache','max_results':True}),
                          ('search_notes',{'query':'cache','paths':['/private']}),
                          ('consult_specialist',{'role':'team','question':'all'}),
                          ('search_reading',{'connector':'zhihu','query':'x'}),
                          ('bash',{'query':'x'})]:
            with self.subTest(name=name,args=args),self.assertRaises(ValueError):
                registry.get(name,args)
        # Mutating an exported definition cannot mutate the frozen authority.
        definitions=registry.definitions();definitions[0]['parameters']['required'].clear()
        with self.assertRaises(ValueError):registry.get('search_notes',{})


@unittest.skipUnless(PI_AVAILABLE,'actual Pi required')
class ToolConversationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=pa1.fixture(self.tmp.name).resolve()
        pa1.configure(self.home,'synthetic-model',True,synthetic_only=False)
        with core.ConversationStore(self.home) as store:self.sid=store.create()
        self.web=Web()
        self.services={'web':self.web,'resolver':lambda host:['8.8.8.8']}

    def ask(self, message='请搜索公开cache资料', provider=None, tid='t1', **kw):
        return submit(self.home,self.sid,message,turn_id=tid,provider=provider or Provider(),services=self.services,**kw)

    def approve(self, provider, control='approval1', **kw):
        return permission_reply(self.home,self.sid,'approve',request_id=control,provider=provider,services=self.services,**kw)

    def read_state(self, tid='t1'):
        with core.ConversationStore(self.home) as store:return json.loads(store.get(self.sid,tid)['state'])

    def test_default_direct_chat_is_one_call_zero_tools_no_work(self):
        provider=Provider(['你好','刚才说了你好','是同一会话'])
        for i in range(3):
            value=self.ask('普通问题'+str(i),provider,'t'+str(i))
            self.assertEqual(value['status'],'completed',value)
        self.assertEqual(value['result']['tools_protocol'],PROTOCOL)
        self.assertEqual(len(provider.calls),3)
        self.assertEqual(self.web.calls,[])
        self.assertFalse((self.home/'work.sqlite3').exists())
        self.assertEqual(len(provider.calls[-1]['messages']),6)

    def test_history_keeps_uncertainty_without_promoting_it_to_evidence(self):
        provider=Provider([{'status':'conversational','answer':'这只是暂定方向。','citations':[],'uncertainty':'尚未核实资格条件。'},
                           '刚才的方向仍是暂定的。'])
        self.ask('讨论方向',provider)
        value=self.ask('刚才说的可以确定吗',provider,'followup')
        self.assertEqual(value['status'],'completed',value)
        self.assertIn('尚未核实资格条件',json.dumps(provider.calls[-1]['messages'],ensure_ascii=False))
        self.assertEqual(value['result']['evidence'],[])

    def test_exact_query_confirmation_resume_body_evidence_and_no_duplicate_billing(self):
        provider=Provider([action('search_web',query='cache coherence public research',backend='exa'),
                           action('fetch_web',url='https://example.com/research'),supported()])
        value=self.ask('我的私人约束PRIVATE_CANARY；只需搜索一般缓存一致性资料',provider)
        self.assertEqual(value['status'],'waiting_permission',value)
        self.assertEqual(self.web.calls,[])
        self.assertEqual(value['new_usage_tokens'],50)
        self.assertIn('cache coherence public research',value['permission']['prompt'])
        completed=self.approve(provider)
        self.assertEqual(completed['status'],'completed',completed)
        self.assertEqual(completed['result']['usage_tokens'],150)
        self.assertEqual(completed['new_usage_tokens'],100)
        self.assertEqual(completed['result']['tool_usage']['search'],1)
        self.assertEqual(completed['result']['tool_usage']['fetch'],1)
        self.assertEqual(len(provider.calls),3,'paid planning step must be replayed')
        self.assertNotIn('PRIVATE_CANARY',json.dumps(self.web.calls))
        self.assertEqual(completed['result']['evidence'][0]['authority'],'external_author_not_owner_fact')
        self.assertTrue(self.approve(provider)['cached'])
        self.assertEqual(self.ask('同意',provider,'approval1')['new_usage_tokens'],0)
        self.assertEqual(len(self.web.calls),2)
        self.assertEqual(core.budget_status(self.home)['daily_tokens'],150)

    def test_natural_confirmation_and_denial_never_require_request_codes(self):
        provider=Provider([action('search_web',query='cache systems')])
        self.assertEqual(self.ask(provider=provider)['status'],'waiting_permission')
        denied=self.ask('不同意',provider,'denial1')
        self.assertEqual(denied['status'],'cancelled')
        self.assertEqual(self.web.calls,[])
        self.assertEqual(self.ask('新话题',Provider(),'next')['status'],'completed')

    def test_changed_or_expired_preview_does_not_authorize_search(self):
        provider=Provider([action('search_web',query='cache systems')])
        pending=self.ask(provider=provider)
        with self.assertRaisesRegex(ValueError,'preview_changed'):
            self.approve(provider,token='not-the-preview')
        with core.ConversationStore(self.home) as store:
            state=self.read_state();state['pending_permission']['expires_at']=0;store.save('t1',state)
        with self.assertRaisesRegex(ValueError,'preview_expired'):
            self.approve(provider)
        self.assertEqual(self.web.calls,[])

    def test_private_query_rejected_without_confirmation_or_network(self):
        provider=Provider([action('search_web',query='我的健康记录 PRIVATE_CANARY'),'不能外发私人内容。'])
        value=self.ask(provider=provider)
        self.assertEqual(value['status'],'completed',value)
        self.assertEqual(self.web.calls,[])
        self.assertEqual(self.read_state()['approved'],{})

    def test_discovery_snippets_cannot_be_cited_as_evidence(self):
        provider=Provider([action('search_web',query='cache systems'),supported()])
        self.ask(provider=provider)
        value=self.approve(provider)
        self.assertEqual(value['status'],'failed')
        self.assertEqual(self.read_state()['evidence'],[])
        self.assertEqual(len(self.web.calls),1)

    def test_arbitrary_url_private_dns_and_prompt_injection_cannot_expand_capability(self):
        provider=Provider([action('fetch_web',url='https://intranet.example/private'), '链接不在本轮公开发现范围。'])
        value=self.ask(provider=provider)
        self.assertEqual(value['status'],'completed',value)
        self.assertEqual(self.web.calls,[])
        self.services['resolver']=lambda host:['127.0.0.1']
        provider=Provider([action('search_web',query='cache systems'),'没有通过本机校验的公开来源。'])
        self.ask('第二个问题',provider,'t2')
        value=self.approve(provider,'a2')
        self.assertEqual(value['status'],'completed',value)
        self.assertEqual(len(self.web.calls),1)
        self.assertEqual(value['result']['evidence'],[])

    def test_new_query_from_external_text_requires_new_owner_confirmation(self):
        provider=Provider([action('search_web',query='cache systems'),
                           action('search_web',query='another query from external text'),'缺口仍待核对。'])
        self.ask(provider=provider)
        second=self.approve(provider)
        self.assertEqual(second['status'],'waiting_permission',second)
        self.assertEqual(len(self.web.calls),1)
        self.assertIn('another query',second['permission']['prompt'])
        result=permission_reply(self.home,self.sid,'deny',request_id='deny-second')
        self.assertEqual(result['status'],'cancelled')
        self.assertEqual(len(provider.calls),2)

    def test_network_unknown_cannot_repeat_after_interrupt_or_new_call_id(self):
        provider=Provider([action('search_web',query='cache systems'),
                           action('search_web',query='cache systems'),'公开后端失败，没有重复请求。'])
        self.web.fail=True
        self.ask(provider=provider)
        result=self.approve(provider)
        self.assertEqual(result['status'],'completed',result)
        self.assertEqual(len(self.web.calls),1)
        self.assertNotIn('PRIVATE_BACKEND_BODY',json.dumps(provider.calls))

    def test_crash_after_external_response_before_tool_commit_does_not_refetch(self):
        provider=Provider([action('search_web',query='cache systems'),'在途请求结果不可恢复，未重做。'])
        self.ask(provider=provider)
        original=ToolConversationHost.commit
        def crash(host,key,args,output):
            if key.startswith('tool:'):raise KeyboardInterrupt()
            return original(host,key,args,output)
        with patch.object(ToolConversationHost,'commit',crash):
            result=self.approve(provider)
        self.assertEqual(result['status'],'interrupted')
        value=core.send(self.home,self.sid,turn_id='t1',resume=True,provider=provider,services=self.services)
        self.assertEqual(value['status'],'completed',value)
        self.assertEqual(len(self.web.calls),1)

    def test_public_snapshot_expiry_invalidates_dependent_followup(self):
        provider=Provider([action('search_web',query='cache systems'),action('fetch_web',url='https://example.com/research'),supported()])
        self.ask(provider=provider);self.approve(provider)
        self.ask('解释刚才结果',Provider(),'t2')
        with core.ConversationStore(self.home) as store:
            state=self.read_state()
            state['evidence'][0]['fetched_at']=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
            store.save('t1',state)
        self.assertEqual(core.inspect(self.home,self.sid)['status'],'invalidated')

    def test_registry_version_drift_never_recomputes_paid_step(self):
        provider=Provider([action('search_notes',query='cache')])
        self.ask(provider=provider,step_limit=1)
        with core.ConversationStore(self.home) as store:
            state=self.read_state();state['registry']['fingerprint']='changed';store.save('t1',state)
        with self.assertRaisesRegex(ValueError,'invalidated_no_retry'):
            core.send(self.home,self.sid,turn_id='t1',resume=True,provider=provider,services=self.services)
        self.assertEqual(len(provider.calls),1)

    def test_local_source_scope_time_and_revocation(self):
        provider=Provider([action('search_notes',query='cache',sources=['synthetic']),supported()])
        value=self.ask('请从笔记检索cache',provider)
        self.assertEqual(value['status'],'completed',value)
        self.assertEqual(self.web.calls,[])
        path=self.home/'sources.yaml';data=json.loads(path.read_text());data['sources'][0]['model_providers']=[];path.write_text(json.dumps(data))
        self.assertEqual(core.inspect(self.home,self.sid)['status'],'invalidated')

    def test_reading_cache_does_not_inherit_account_or_model_grants(self):
        provider=Provider([action('search_reading',connector='folo',query='cache'),'没有获准的本机Folo正文。'])
        with patch('personal_asis.reading.fetch',side_effect=AssertionError('no live account fetch')):
            value=self.ask(provider=provider)
        self.assertEqual(value['status'],'completed',value)
        self.assertEqual(value['result']['evidence'],[])

    def test_specialist_is_opt_in_and_uses_preserved_legacy_executor(self):
        provider=Provider([action('consult_specialist',role='research',question='根据合成资料说明cache'),
                           '专业工作已保留，请查看工作状态。'])
        calls=[]
        def executor(*args,**kw):
            calls.append((args,kw));return {'status':'waiting_node'}
        self.services['specialist']=executor
        pending=self.ask('请研究角色核对',provider)
        self.assertEqual(pending['status'],'waiting_permission')
        self.assertEqual(calls,[])
        result=self.approve(provider)
        self.assertEqual(result['status'],'completed',result)
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][1]['mode'],'research')
        self.assertEqual(calls[0][0][3],['synthetic'])
        self.assertTrue(result['result']['work_refs'])

    def test_confirmation_event_id_cannot_change_question_or_create_second_paid_turn(self):
        provider=Provider([action('search_web',query='cache systems'),'没有读取正文，仅发现线索。'])
        self.ask(provider=provider);self.approve(provider)
        with self.assertRaisesRegex(ValueError,'confirmation_id_conflict'):
            self.ask('改成私人问题',provider,'approval1')
        with self.assertRaisesRegex(ValueError,'confirmation_id_conflict'):
            core.send(self.home,self.sid,'新问题',turn_id='approval1',provider=provider)
        self.assertEqual(len(provider.calls),2)

    def test_specialist_actual_pi_reuses_old_policy_budget_and_parent_invalidation(self):
        from test_agent_roles import RolesProvider
        from personal_asis.work import WorkStore
        roles=RolesProvider()
        self.services['specialist_provider']=roles
        provider=Provider([action('consult_specialist',role='research',question='cache'),supported()])
        self.ask('请专业角色核对cache',provider)
        result=self.approve(provider)
        self.assertEqual(result['status'],'completed',result)
        self.assertEqual(len(roles.calls),2)
        self.assertEqual(result['result']['usage_tokens'],260)
        self.assertEqual(core.budget_status(self.home)['daily_tokens'],260)
        state=self.read_state()
        dependency=state['work_dependencies'][0]
        from personal_asis import agent
        work=agent.inspect(self.home,dependency['request_id'])
        with WorkStore(self.home/'work.sqlite3') as store:store.control(work['delegation_id'],'cancel')
        self.assertEqual(core.inspect(self.home,self.sid)['status'],'invalidated')

    def test_specialist_generation_limit_preserves_incomplete_work(self):
        from test_agent_roles import RolesProvider
        roles=RolesProvider(search_again=True)
        self.services['specialist_provider']=roles
        provider=Provider([action('consult_specialist',role='research',question='cache'),'专业工作在本轮上限停止，结果尚未完成。'])
        self.ask('请专业角色核对cache',provider)
        result=self.approve(provider)
        self.assertEqual(result['status'],'completed',result)
        self.assertEqual(len(roles.calls),2)
        self.assertEqual(result['result']['usage_tokens'],260)
        self.assertEqual(result['result']['model_calls'],4)
        self.assertTrue(result['result']['work_refs'])
        self.assertEqual(self.read_state()['work_dependencies'],[])

    def test_expired_query_approval_cannot_authorize_new_body_read(self):
        provider=Provider([action('search_web',query='cache systems'),action('fetch_web',url='https://example.com/research'),
                           '公开读取许可已过期。'])
        self.ask(provider=provider)
        first=self.approve(provider,step_limit=1)
        self.assertEqual(first['status'],'interrupted')
        with core.ConversationStore(self.home) as store:
            state=self.read_state()
            for grant in state['approved'].values():grant['expires_at']=0
            store.save('t1',state)
        value=core.send(self.home,self.sid,turn_id='t1',resume=True,provider=provider,services=self.services)
        self.assertEqual(value['status'],'completed',value)
        self.assertEqual(len(self.web.calls),1)

    def test_missing_web_credentials_are_a_safe_tool_failure_receipt(self):
        self.web.search_web=lambda *a,**kw: (_ for _ in ()).throw(ValueError('sensitive-provider-detail'))
        provider=Provider([action('search_web',query='cache systems'),'公开工具暂不可用，没有声称已搜索。'])
        self.ask(provider=provider)
        result=self.approve(provider)
        self.assertEqual(result['status'],'completed',result)
        self.assertNotIn('sensitive-provider-detail',json.dumps(provider.calls))

    def test_question_time_scope_cannot_be_widened_by_tool_query(self):
        from personal_asis.config import load_config
        from personal_asis.index import Index
        root=self.home/'source'
        (root/'2026-10-18.md').write_text('# 当前合成记录\n\ncache TODAY_ALLOWED\n')
        (root/'2026-01-01.md').write_text('# 旧合成记录\n\ncache OLD_DATE_CANARY\n')
        path=self.home/'sources.yaml';data=json.loads(path.read_text());data['sources'][0]['model_all_files']=True;path.write_text(json.dumps(data))
        with Index(self.home/'index.sqlite3',load_config(path)) as index:index.reconcile()
        window={'start':'2026-10-18','end':'2026-10-18','basis':'question','unknown_dates':'excluded'}
        provider=Provider([action('search_notes',query='cache'),supported()])
        with patch('personal_asis.conversation_tools.question_window',return_value=window):
            result=self.ask('请回看昨天笔记',provider)
        self.assertEqual(result['status'],'completed',result)
        wire=json.dumps(provider.calls)
        self.assertIn('TODAY_ALLOWED',wire)
        self.assertNotIn('OLD_DATE_CANARY',wire)
        self.assertTrue(all(e.get('record_date')=='2026-10-18' for e in result['result']['evidence']))

    def test_author_attribution_from_approved_reading_cache_and_revocation(self):
        from personal_asis import reading
        from personal_asis.reading_sources import Article
        reading.configure(self.home,'folo')
        with reading.ReadingCache(self.home,'folo') as cache:
            cache.put(Article('p1-author','Synthetic article','https://example.com/article',
                       author='SYNTHETIC_AUTHOR',author_text='coherence_AUTHOR keeps replicas consistent.',
                       content_kind='feed_content'),'subscriptions')
        reading.classify(self.home,'folo','p1-author','normal')
        reading.refresh_index(self.home)
        pa1.authorize_current_files(self.home,['reading_folo'],all_source_files=True)
        provider=Provider([action('search_reading',connector='folo',query='coherence_AUTHOR'),supported()])
        value=self.ask('找订阅作者观点',provider)
        self.assertEqual(value['status'],'completed',value)
        self.assertEqual(value['result']['evidence'][0]['reading_attribution'],'author_original')
        self.assertIn('SYNTHETIC_AUTHOR',json.dumps(provider.calls))
        with reading.ReadingCache(self.home,'folo') as cache,cache.db:
            cache.db.execute("UPDATE meta SET value='0' WHERE key='enabled'")
        self.assertEqual(core.inspect(self.home,self.sid)['status'],'invalidated')
