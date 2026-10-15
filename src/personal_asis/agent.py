"""Owner-local on-demand Pi/MiMo execution with policy-checked durable replay.

No background scheduler, shell, platform writes, new grants or role spawning.
Only search_notes is exposed; actual disclosure uses PA1 ContextBundle checks.
"""

import copy
import hashlib
import json
from pathlib import Path

from . import pa1
from .agent_model import TOOLS, ToolMiMo, runtime_reply, text_content, unknown_diagnostic
from .config import load_pa1_config, root_identity
from .data_policy import exclusion_reason
from .model_provider import ProviderRejected, validate_answer
from .provider_diagnostics import diagnostic_for
from .retrieval import ContextBundle, build_bundle
from .runtime_adapter import run_pi
from .work import WorkStore, fingerprint, encoded


MAX_TURNS=6
MAX_SEARCHES=3
MAX_EVIDENCE=6
SYNTHETIC_QUESTION=('请先调用 search_notes，检索词为 cache。根据检索到的合成资料，'
                    '简要比较 cache invalidation 和 cache coherence 的作用，并引用两条证据。')
FINAL_ONLY='检索次数已用完。现在必须只根据已返回的证据输出最终 JSON，说明证据缺口；不能再调用工具。'


def search_count(actions):
    return sum(a['key'].startswith('tool:') and a['output'].get('status')!='search_limit_reached'
               for a in actions)


def tool_wire_result(output):
    # The tool result becomes JSON *text* in Pi's transcript. SQLite's sorted
    # storage keys must not change that text (or a paid request fingerprint)
    # during replay. Keep the original protocol's field order, including old
    # checkpoints written before bounded finalization was implemented.
    if output.get('status')=='search_limit_reached':
        return {'status':output['status'],'evidence':output['evidence'],
                'coverage':output['coverage'],'next_step':output['next_step']}
    return {'evidence':[{'id':e['id'],'title':e['title'],'text':e['text']} for e in output['evidence']],
            'coverage':output['coverage'],'retrieval_mode':output['retrieval_mode'],
            'degradation':output['degradation']}


class CheckpointReached(Exception):
    pass


def validate_state(home, source_home, state):
    data=pa1.settings(home)
    config=load_pa1_config(source_home)
    if not data['enabled'] or fingerprint(data)!=state['settings']:
        raise ValueError('agent_model_configuration_disabled_or_changed')
    if data['synthetic_only'] and not state['synthetic']:
        raise ValueError('pa1_synthetic_only_real_sources_disabled')
    sources={s.id:s for s in config.sources}
    for sid,identity in state['roots'].items():
        source=sources.get(sid)
        if (source is None or not source.root.is_dir() or root_identity(source.root)!=identity or
                not source.index or 'mimo' not in source.model_providers or
                not (source.model_all_files or source.model_paths)):
            raise ValueError('agent_source_scope_revoked_or_changed')
    bundle=ContextBundle(state['question'],'mimo',state['evidence'],state['mode'],state['degradation'])
    bundle.revalidate(source_home)
    if state['synthetic']:
        pa1.verify_synthetic_bundle(ContextBundle('cache','mimo',state['evidence'],state['mode']))
    return bundle


class AgentHost:
    def __init__(self, home, source_home, work, claim, state, provider=None, encoder=None, step_limit=None):
        self.home,self.source_home=Path(home),Path(source_home)
        self.work,self.claim,self.state=work,claim,state
        self.data=pa1.settings(home)
        self.node=load_pa1_config(home).node_id
        self.provider=provider or ToolMiMo(self.node,self.data['model'])
        self.encoder=encoder
        self.ledger=pa1.budget(home,self.node,self.data)
        self.index=0
        self.new_steps=0
        self.step_limit=step_limit

    def close(self):
        self.ledger.close()

    def check(self):
        self.work._check(self.claim['id'],self.node,self.claim['epoch'])
        try:
            return validate_state(self.home,self.source_home,self.state)
        except (OSError,ValueError):
            self.work.clean(self.claim['delegation'])
            raise

    def _replay(self, key, arguments):
        self.check()
        actions=self.state['actions']
        if self.index<len(actions):
            action=actions[self.index]
            if action['key']!=key or action['fingerprint']!=fingerprint(arguments):
                raise ValueError('agent_replay_input_mismatch_no_retry')
            self.index+=1
            output=copy.deepcopy(action['output'])
            return tool_wire_result(output) if key.startswith('tool:') else output
        return None

    def _begin(self, key, kind, arguments):
        self.work.heartbeat(self.claim['id'],self.node,self.claim['epoch'],900)
        self.work.begin_execution(self.claim['id'],self.node,self.claim['epoch'],key,kind,arguments)

    def _settle_failure(self, key, state):
        try:
            self.work.finish_execution(self.claim['id'],self.node,self.claim['epoch'],key,state)
        except ValueError:
            pass  # A pause/recovery has fenced this worker and retained unknown.

    def _commit(self, key, arguments, output):
        self.check()
        self.state['actions'].append({'key':key,'fingerprint':fingerprint(arguments),'output':output,
                                      'model_final_only':key.startswith('model:') and 'tools' not in arguments})
        self.work.commit_action(self.claim['id'],self.node,self.claim['epoch'],key,self.state)
        self.index+=1
        self.new_steps+=1
        if self.step_limit is not None and self.new_steps>=self.step_limit:
            raise CheckpointReached()
        return output

    def model(self, event):
        turn=event['turn']
        if type(turn) is not int or not 1<=turn<=MAX_TURNS:
            raise ValueError('agent_turn_limit')
        payload=self.provider.tool_payload(event['messages'],self.data['max_completion_tokens'])
        key=f'model:{turn}'
        # Historical paid steps keep their original protocol; fresh steps at the
        # search bound finalize without tool declarations. Persist this choice
        # so later replay reconstructs the exact same request fingerprint.
        old=self.state['actions'][self.index] if self.index<len(self.state['actions']) else None
        final_only=old.get('model_final_only',False) if old else search_count(self.state['actions'])>=MAX_SEARCHES
        if final_only:
            payload.pop('tools',None)
            payload.pop('tool_choice',None)
            payload['messages'][0]['content']+=FINAL_ONLY
        replay=self._replay(key,payload)
        if replay is not None:
            return replay
        if turn!=1+sum(a['key'].startswith('model:') for a in self.state['actions']):
            raise ValueError('agent_model_turn_out_of_order')
        prompt_bytes=len(encoded({'messages':payload['messages'],'tools':payload.get('tools',[])}).encode())
        if prompt_bytes>self.data['max_prompt_bytes']:
            raise ValueError('agent_context_exceeds_prompt_limit')
        self.ledger.check_provider()
        secret=self.provider.credential()
        reservation=prompt_bytes+1024+self.data['max_completion_tokens']
        request_id=self.claim['id']+':'+key
        self._begin(key,'model',payload)
        reserved=False
        try:
            booked=self.ledger.reserve(request_id,fingerprint(payload),reservation)
            if 'cached' in booked:
                raise ValueError('agent_ledger_result_without_committed_action_no_retry')
            reserved=True
            self.check()
        except BaseException:
            if reserved:
                self.ledger.finish(request_id,'rejected',0)
            self._settle_failure(key,'rejected')
            raise
        try:
            response=self.provider.complete(payload,secret)
        except ProviderRejected:
            self.ledger.finish(request_id,'rejected',0)
            self._settle_failure(key,'rejected')
            raise
        except BaseException as error:
            diagnostic=unknown_diagnostic(error)
            self.ledger.finish(request_id,'unknown',diagnostic=diagnostic_for(error))
            self._settle_failure(key,'unknown')
            self.work._event(self.claim['delegation'],'agent_unknown_'+diagnostic,self.claim['id'])
            raise ValueError('agent_model_result_unknown_no_retry:'+diagnostic) from None
        total=response['usage']['total_tokens']
        try:
            if total>reservation or response['usage']['completion_tokens']>self.data['max_completion_tokens']:
                raise ValueError('provider_usage_exceeded_reservation')
            output=runtime_reply(response)
            if final_only and output['stopReason']!='stop':
                raise ValueError('agent_tool_requested_after_search_limit')
            if output['stopReason']=='toolUse':
                prior={c['id'] for a in self.state['actions'] if a['key'].startswith('model:')
                       for c in a['output']['content'] if c['type']=='toolCall'}
                if any(c['id'] in prior for c in output['content'] if c['type']=='toolCall'):
                    raise ValueError('agent_model_reused_tool_call_id')
            self.check()
        except BaseException:
            category={'length':'output_limit','content_filter':'content_filter',
                      'repetition_truncation':'repetition_truncated'}.get(response['finish_reason'])
            diagnostic=({'http_status':None,'category':category,'retry_after_seconds':None} if category else None)
            self.ledger.finish(request_id,'invalid_output',total,diagnostic=diagnostic)
            self._settle_failure(key,'rejected')
            raise
        # Billing is authoritative even if a crash prevents committing its body.
        self.ledger.finish(request_id,'succeeded',total)
        self.state['usage']['prompt_tokens']+=response['usage']['prompt_tokens']
        self.state['usage']['completion_tokens']+=response['usage']['completion_tokens']
        self.state['usage']['total_tokens']+=total
        return self._commit(key,payload,output)

    def tool(self, event):
        if event['name']!='search_notes' or not isinstance(event['args'],dict) or set(event['args'])!={'query'}:
            raise ValueError('agent_tool_not_allowed')
        query=event['args']['query']
        if not isinstance(query,str) or not query.strip() or len(query)>512 or exclusion_reason('',query):
            raise ValueError('agent_invalid_search_query')
        key='tool:'+event['callId']
        arguments={'name':'search_notes','args':event['args']}
        replay=self._replay(key,arguments)
        if replay is not None:
            return replay
        # Only calls requested by a committed model response may execute.
        if not any(c['type']=='toolCall' and c['id']==event['callId'] and c['name']==event['name']
                   and c['arguments']==event['args'] for a in self.state['actions']
                   if a['key'].startswith('model:') for c in a['output']['content']):
            raise ValueError('agent_tool_not_requested')
        self._begin(key,'tool',arguments)
        try:
            if search_count(self.state['actions'])>=MAX_SEARCHES:
                # A saved old-protocol response may have already requested one
                # extra call. Commit a refusal receipt; never run that search.
                return self._commit(key,arguments,{
                    'status':'search_limit_reached','evidence':[],
                    'coverage':'current_authorized_matches_only','next_step':'final_answer_from_existing_evidence'})
            try:
                bundle=build_bundle(self.source_home,query,'mimo',self.encoder,list(self.state['roots']))
            except ValueError as error:
                if str(error)!='no_current_provider_authorized_evidence':
                    raise
                bundle=ContextBundle(query,'mimo',[],'lexical','no_authorized_match')
            bundle.revalidate(self.source_home)
            if self.state['synthetic']:
                pa1.verify_synthetic_bundle(ContextBundle('cache','mimo',bundle.evidence,bundle.retrieval_mode))
            evidence=self.state['evidence']
            result=[]
            for entry in bundle.evidence:
                identity=[entry[k] for k in ('document_id','content_hash','excerpt','line_start','column_start')]
                position=next((i for i,e in enumerate(evidence) if identity==[e[k] for k in (
                    'document_id','content_hash','excerpt','line_start','column_start')]),None)
                if position is None:
                    if len(evidence)>=MAX_EVIDENCE:
                        break
                    evidence.append(entry)
                    position=len(evidence)-1
                result.append({'id':f'E{position+1}','title':entry['title'],'text':entry['excerpt']})
            self.state['mode']=bundle.retrieval_mode
            self.state['degradation']=bundle.degradation
            output={'evidence':result,'coverage':'current_authorized_matches_only',
                    'retrieval_mode':bundle.retrieval_mode,'degradation':bundle.degradation}
            return self._commit(key,arguments,output)
        except CheckpointReached:
            raise
        except BaseException:
            self._settle_failure(key,'unknown')
            raise

    def done(self, event):
        bundle=self.check()
        tail=event['messages'][-1]
        if tail.get('role')!='assistant' or tail.get('stopReason')!='stop':
            raise ValueError('agent_run_incomplete_turn_limit')
        if not any(a['key'].startswith('tool:') for a in self.state['actions']):
            raise ValueError('agent_answer_requires_search')
        answer=validate_answer({'finish_reason':'stop','tool_calls':None,
                                'content':text_content(tail['content'])},bundle)
        result={**answer,'provider':'mimo','model':self.data['model'],'request_id':self.state['request_id'],
                'evidence':[{'id':f'E{i+1}',**e} for i,e in enumerate(bundle.evidence)],
                'sensitivity':'private' if any(e['sensitivity']=='private' for e in bundle.evidence) else 'normal',
                'retrieval_mode':bundle.retrieval_mode,'degradation':bundle.degradation,
                'coverage':'current_authorized_matches_only','usage':self.state['usage'],
                'model_turns':sum(a['key'].startswith('model:') for a in self.state['actions']),
                'searches':search_count(self.state['actions'])}
        self.work.progress(self.claim['id'],self.node,self.claim['epoch'],result,completed=True)
        return {'status':'completed','delegation_id':self.claim['delegation'],'run_id':self.claim['id'],
                'cached':False,'result':result}

    def __call__(self, kind, event):
        return {'model':self.model,'tool':self.tool,'done':self.done}[kind](event)


def _source_home(home, request_id, synthetic):
    return home/'agent-validation'/hashlib.sha256(request_id.encode()).hexdigest()[:24] if synthetic else home


def execute(home, query, request_id, source_ids=None, *, resume=False, provider=None,
            synthetic=False, step_limit=None, encoder_override=None):
    home=Path(home)
    if not isinstance(request_id,str) or not 1<=len(request_id)<=96:
        raise ValueError('agent_request_id_required_max_96')
    if step_limit is not None and (type(step_limit) is not int or not 1<=step_limit<=12):
        raise ValueError('agent_invalid_step_limit')
    if resume and (query is not None or source_ids is not None):
        raise ValueError('agent_resume_uses_saved_question_and_scope')
    data=pa1.settings(home)
    node=load_pa1_config(home).node_id
    with WorkStore(home/'work.sqlite3') as work:
        prior=work.db.execute('SELECT id FROM delegations WHERE request_id=?',('agent:'+request_id,)).fetchone()
        if resume:
            if prior is None:
                raise ValueError('agent_request_not_found')
            view=work.view(prior['id'])
            query=view['goal']
            source_ids=view['scope']['sources']
            previous=work.session(view['runs'][0]['id'])
            if previous:
                synthetic=previous['synthetic']
            if view['state']=='paused':
                work.control(view['id'],'resume')
        if not isinstance(query,str) or not query.strip() or len(query)>512 or exclusion_reason('',query):
            raise ValueError('agent_invalid_question')
        if not source_ids:
            raise ValueError('agent_explicit_sources_required')
        source_home=_source_home(home,request_id,synthetic)
        config=load_pa1_config(source_home)
        sources={s.id:s for s in config.sources}
        if set(source_ids)-set(sources):
            raise ValueError('agent_scope_contains_unknown_source')
        did=work.create('agent:'+request_id,node,query,source_ids)
        rid=work.enqueue(did,'on-demand')
        initial={'version':1,'question':query,'request_id':request_id,'synthetic':synthetic,
                 'roots':{sid:root_identity(sources[sid].root) for sid in sorted(set(source_ids))},
                 'settings':fingerprint(data),'actions':[],'evidence':[],
                 'mode':'lexical','degradation':None,
                 'usage':{'prompt_tokens':0,'completion_tokens':0,'total_tokens':0}}
        # Changes to schemas, model settings, question or source roots cannot reuse a run.
        contract=fingerprint([TOOLS,initial])
        state=work.session(rid)
        if state is not None:
            try:
                validate_state(home,source_home,state)
            except (OSError,ValueError):
                work.clean(did)
                raise
        run=work._run(rid)
        if run['state']=='completed':
            if state is None or run['result'] is None:
                raise ValueError('agent_result_expired_or_cleared_no_retry')
            return {'status':'completed','delegation_id':did,'run_id':rid,'cached':True,'result':json.loads(run['result'])}
        claim=work.claim(node,capacity=2,foreground_reserve=1,lease_seconds=900,run_id=rid)
        if claim is None:
            return {'status':work._run(rid)['state'],'delegation_id':did,'run_id':rid,
                    'unresolved_executions':sum(e['state']=='unknown' for e in work.executions(rid)),
                    'automatic_execution':False}
        host=None
        try:
            state=work.start_session(rid,node,claim['epoch'],contract,initial)
            validate_state(home,source_home,state)
            encoder=encoder_override
            if not synthetic and encoder is None:
                encoder,_=pa1.encoder_for(data)
            host=AgentHost(home,source_home,work,claim,state,provider,encoder,step_limit)
            return run_pi(query,TOOLS,claim['session'],host,max_turns=MAX_TURNS,timeout=900)
        except CheckpointReached:
            work.yield_run(rid,node,claim['epoch'])
            return {'status':'checkpointed','delegation_id':did,'run_id':rid,
                    'committed_actions':len(state['actions']),'usage':state['usage'],'automatic_execution':False}
        except BaseException:
            try:
                work.yield_run(rid,node,claim['epoch'])
            except ValueError:
                pass
            raise
        finally:
            if host is not None:
                host.close()


def live_self_test(home, request_id, step_limit=None):
    home=Path(home)
    if not isinstance(request_id,str) or not 1<=len(request_id)<=96:
        raise ValueError('agent_request_id_required_max_96')
    data=pa1.settings(home)
    node=load_pa1_config(home).node_id
    provider=ToolMiMo(node,data['model'])
    if data['model'] not in provider.models():
        raise ValueError('agent_configured_model_not_available')
    source_home=_source_home(home,request_id,True)
    if not source_home.exists():
        source_home.mkdir(parents=True,mode=0o700)
        pa1.fixture(source_home,node)
    return execute(home,SYNTHETIC_QUESTION,request_id,['synthetic'],provider=provider,
                   synthetic=True,step_limit=step_limit)


def inspect(home, request_id):
    home=Path(home)
    with WorkStore(home/'work.sqlite3') as work:
        row=work.db.execute('''SELECT r.* FROM runs r JOIN delegations d ON d.id=r.delegation
            WHERE d.request_id=? AND r.request_id='on-demand' ''',('agent:'+str(request_id),)).fetchone()
        if row is None:
            raise ValueError('agent_request_not_found')
        state=work.session(row['id'])
        if state:
            try:
                validate_state(home,_source_home(home,request_id,state['synthetic']),state)
            except (OSError,ValueError):
                work.clean(row['delegation'])
                raise
        return {'status':row['state'],'delegation_id':row['delegation'],'run_id':row['id'],
                'progress':json.loads(row['checkpoint']) if row['checkpoint'] else None,
                'result':json.loads(row['result']) if row['result'] else None,
                'executions':work.executions(row['id']),'automatic_execution':False}


def clean_sessions(home):
    """Fresh PA1 permissions/versions before status or ordinary maintenance."""
    home=Path(home)
    if not (home/'work.sqlite3').exists():
        return 0
    removed=0
    with WorkStore(home/'work.sqlite3') as work:
        rows=work.db.execute('SELECT run,payload FROM agent_sessions WHERE payload IS NOT NULL').fetchall()
        for row in rows:
            state=json.loads(row['payload'])
            try:
                validate_state(home,_source_home(home,state['request_id'],state['synthetic']),state)
            except (OSError,ValueError,KeyError):
                work.clean(work._run(row['run'])['delegation'])
                removed+=1
    return removed


def provider_status(home, probe=False, provider=None):
    """Local diagnostics; optional /models read never generates a completion."""
    home=Path(home)
    data=pa1.settings(home)
    node=load_pa1_config(home).node_id
    ledger=pa1.budget(home,node,data)
    try:
        result={'provider':'mimo','model':data['model'],'budget':ledger.status(),
                **ledger.provider_status(),'probe_made':False}
    finally:
        ledger.close()
    if probe:
        client=provider or ToolMiMo(node,data['model'])
        result['probe_made']=True
        try:
            result['configured_model_listed']=data['model'] in client.models()
        except ProviderRejected:
            result['probe_error']={'category':'authentication_rejected'}
        except (OSError,ValueError) as error:
            result['probe_error']=diagnostic_for(error)
    return result
