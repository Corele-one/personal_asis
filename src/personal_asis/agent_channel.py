"""Owner channel control plane. VPS jobs/keys are RAM-only; Mac owns all work state."""

import hashlib
from contextlib import closing
import json
from pathlib import Path
import queue
import re
import secrets
import sqlite3
import threading
import time
import uuid

from .analysis_channel import AnalysisRelay, validate_request, validate_result
from .coordinator import ProtocolError, exact
from .evidence import control, encrypt
from .work import WorkStore


def aad(job):
    return '\n'.join(('agent', job['request_id'], job['target_id'], job['client_nonce'], job['channel'])).encode()


def relay_control(home, data):
    return control(home, data, 'agent.sock')


class AgentRelay(AnalysisRelay):
    def __init__(self, clock=time.monotonic):
        super().__init__(clock)
        self.lock=threading.RLock()

    def _prune(self):
        super()._prune()
        # Finished transport receipts do not occupy the bounded queue for 15 min.
        for key in [k for k,v in self.jobs.items() if v['ready_at'] is not None
                    and self.clock()-v['ready_at']>30]:
            del self.jobs[key]

    def request(self, data):
        exact({k:v for k,v in data.items() if k!='mode'}, ('request_id','target_id','action','query','source_ids','channel','client_nonce','public_key'))
        if data['channel'] not in ('pwa','feishu') or data['action'] not in ('run','status','pause','resume','cancel'):
            raise ProtocolError('invalid_agent_action')
        try:
            if str(uuid.UUID(data['target_id']))!=data['target_id']:
                raise ValueError()
        except (ValueError,TypeError,AttributeError):
            raise ProtocolError('invalid_agent_target') from None
        if data['action']=='run':
            if not data['source_ids']:
                raise ProtocolError('agent_explicit_sources_required')
            if 'mode' in data:
                from .agent_roles import MODES
                if data['mode'] not in MODES:
                    raise ProtocolError('agent_unknown_role_mode')
        elif data['query'] is not None or data['source_ids'] is not None:
            raise ProtocolError('agent_control_uses_saved_scope')
        elif 'mode' in data:
            raise ProtocolError('agent_control_uses_saved_role_plan')
        validate_request({**{k:data[k] for k in ('request_id','channel','source_ids','client_nonce','public_key')},
                          'query':data['query'] if data['action']=='run' else 'Agent control', 'research':None})
        digest=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
        with self.lock:
            self._prune()
            old=self.jobs.get(data['request_id'])
            if old and old['digest']!=digest:
                raise ProtocolError('agent_request_conflict',409)
            if old is None:
                if len(self.jobs)>=16:
                    raise ProtocolError('agent_busy',429)
                self.jobs[data['request_id']]={**data,'research':None,'node_id':'mac','digest':digest,
                    'expires':self.clock()+self.ttl,'lease':None,'lease_until':0,
                    'status':'waiting','envelope':None,'ready_at':None}
            return {'request_id':data['request_id'],'target_id':data['target_id'],
                    'status':self.jobs[data['request_id']]['status'],'expires_in':self.ttl}

    def poll(self, node, stamp, busy=False):
        with self.lock:
            self._prune()
            if node!='mac':
                return {'job':None}
            if self.stamp is not None and stamp!=self.stamp:
                for value in self.jobs.values():
                    if value['status']=='ready':
                        value['status'],value['envelope']='revoked',None
            self.stamp=stamp
            for value in self.jobs.values():
                if busy and value['action'] in ('run','resume'):
                    continue
                if value['status']=='waiting':
                    value['lease']=secrets.token_urlsafe(24)
                    value['lease_until']=value['expires']
                    value['status']='running'
                    keys=('request_id','target_id','action','query','source_ids','channel',
                          'client_nonce','public_key','lease')
                    return {'job':{**{k:value[k] for k in keys},
                        **({'mode':value['mode']} if 'mode' in value else {}),
                        'remaining_seconds':max(0,value['expires']-self.clock())}}
            return {'job':None}

    def get(self, request_id):
        result=super().get(request_id)
        result['plan']='Mac 核对来源和权限 → 最多三次检索 → 共享预算内分析；支持暂停、恢复和取消'
        with self.lock:
            job=self.jobs.get(request_id)
            if job and 'mode' in job:
                from .agent_roles import LABELS,plan
                from .request_intent import response_plan
                roles=plan(job['mode'],job['query'])['roles']
                result['plan']='Mac 核对来源和权限 → 检索原始证据 → '+ '、'.join(LABELS[r] for r in roles)+' → 总管核对汇总；共享预算，支持暂停与恢复'
                if response_plan(job['query'],job['mode']):
                    result['plan']='回应本轮消息，不检索历史笔记；共用现有预算。'
        return result

    def complete(self, node, data):
        # Older workers remain compatible. New workers bind a receipt to the
        # post-validation policy stamp, invalidating other cached ciphertext
        # atomically without revoking their own fresh control/result receipt.
        stamp=data.get('policy_hash')
        if 'policy_hash' in data and (node!='mac' or not isinstance(stamp,str)
                or not re.fullmatch('[0-9a-f]{64}',stamp)):
            raise ProtocolError('invalid_agent_policy_hash')
        with self.lock:
            result=super().complete(node,{k:v for k,v in data.items() if k!='policy_hash'})
            if stamp is not None:
                if self.stamp is not None and self.stamp!=stamp:
                    for key,value in self.jobs.items():
                        if key!=data['request_id'] and value['status']=='ready':
                            value['status'],value['envelope']='revoked',None
                self.stamp=stamp
            return result


def snapshot(home, target, channel='pwa'):
    from .agent import inspect
    value=inspect(home,target)
    with WorkStore(Path(home)/'work.sqlite3') as work:
        session=work.session(value['run_id'])
        delegation=work._delegation(value['delegation_id'])
    result={'target_id':target,'state':value['status'],'delegation_state':delegation['state'],
            'committed_actions':len(session['actions']) if session else 0,
            'usage':session['usage'] if session else None,
            'unresolved_executions':sum(e['state']=='unknown' for e in value['executions']),
            'automatic_retry':False}
    if session and 'role_plan' in session:
        result['role_plan']=session['role_plan']
        with WorkStore(Path(home)/'work.sqlite3') as work:
            result['roles']=[{'role':r['role'],'state':r['state']} for r in work.db.execute(
                'SELECT role,state FROM runs WHERE parent=? ORDER BY created,rowid',(value['run_id'],))]
    if session:
        result['question']=session['question']
        if session.get('response_plan'):
            result['response_plan']=session['response_plan']
        if session.get('temporal_scope'):
            result['temporal_scope']=session['temporal_scope']
    if value['result'] is not None:
        result['result']=validate_result(home,value['result'],channel)
    return result


class AgentWorker:
    """One foreground execution thread; polling/control stays responsive during a call."""
    def __init__(self, home, client=None, executor=None):
        from .analysis_channel import Worker
        from .agent import execute
        self.home=Path(home)
        self.policy=Worker(home,client)
        self.client=self.policy.client
        self.node=self.policy.node
        self.executor=executor or execute
        self.active=None
        self.finished=queue.Queue()
        self.stopped=threading.Event()

    def stamp(self):
        # Hash only permission/retention/control metadata. Normal creation and
        # progress must not revoke an otherwise current result on every poll.
        values=[self.policy.stamp()]
        path=self.home/'work.sqlite3'
        if path.exists():
            with closing(sqlite3.connect(path)) as db:
                tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'domain_contexts' in tables:
                    values.append(db.execute('''SELECT domain,revision,model_allowed,deleted,review_after<=?
                        FROM domain_contexts ORDER BY domain''',(time.time(),)).fetchall())
                if 'agent_sessions' in tables:
                    values.append(db.execute('''SELECT run FROM agent_sessions WHERE payload IS NULL OR at<=?
                        ORDER BY run''',(time.time()-30*86400,)).fetchall())
                if 'delegations' in tables:
                    values.append(db.execute("SELECT id,state FROM delegations WHERE state IN ('paused','cancelled') ORDER BY id").fetchall())
        return hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()

    def _complete(self, job, value):
        before=self.stamp()
        if 'error' not in value:
            try:
                value=snapshot(self.home,job['target_id'],job['channel'])
            except (ValueError,OSError) as error:
                value=self.failure(error)
        after=self.stamp()
        if before!=after:
            value=self.failure(ValueError('agent_result_changed_before_disclosure'))
        self.client.authenticated('/v1/agent/complete',{'request_id':job['request_id'],
            'lease':job['lease'],'status':'ready','envelope':encrypt(value,job,aad(job)),
            'policy_hash':after})

    def _receipt(self, job):
        # Persist only command identity, never recipient keys or private payloads.
        # A replay may view current state but cannot reapply an old resume/pause.
        digest=hashlib.sha256(json.dumps({k:v for k,v in job.items()
            if k not in ('lease','remaining_seconds')},sort_keys=True).encode()).hexdigest()
        with WorkStore(self.home/'work.sqlite3') as work:
            work.db.execute('''CREATE TABLE IF NOT EXISTS agent_channel_commands (
                id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL)''')
            with work.transaction():
                old=work.db.execute('SELECT fingerprint FROM agent_channel_commands WHERE id=?',
                    (job['request_id'],)).fetchone()
                if old:
                    if old['fingerprint']!=digest:
                        raise ValueError('agent_channel_command_conflict')
                    return False
                work.db.execute('INSERT INTO agent_channel_commands VALUES(?,?)',(job['request_id'],digest))
                return True

    @staticmethod
    def failure(error):
        code=str(error)
        if not re.fullmatch(r'(?:agent_|context_|pa1_|model_|delegation_|inactive_|cancelled_|optional_pi_|mimo_)[a-z_]+(?::[a-z_]+)?',code) or len(code)>120:
            code='agent_execution_failed'
        return {'error':code,'automatic_retry':False}

    def _execute(self, job, deadline):
        def check_deadline():
            if self.stopped.is_set() or time.monotonic()>=deadline:
                raise ValueError('agent_channel_request_expired')
        try:
            if job['action']=='run':
                self.executor(self.home,job['query'],job['target_id'],job['source_ids'],
                              channel=job['channel'],before_step=check_deadline,bootstrap=True,
                              **({'mode':job['mode']} if 'mode' in job else {}))
            else:
                self.executor(self.home,None,job['target_id'],resume=True,
                              channel=job['channel'],before_step=check_deadline,bootstrap=True)
            value=snapshot(self.home,job['target_id'],job['channel'])
        except Exception as error:
            value=self.failure(error)
        self.finished.put((job,value))

    def once(self):
        # Complete in the polling thread: the execution thread owns no transport session.
        try:
            job,value=self.finished.get_nowait()
        except queue.Empty:
            pass
        else:
            self.active=None
            # A changed source/policy invalidates results; snapshots recheck disclosure.
            if 'error' not in value:
                try:
                    value=snapshot(self.home,job['target_id'],job['channel'])
                except (ValueError,OSError) as error:
                    value=self.failure(error)
            self._complete(job,value)
        job=self.client.authenticated('/v1/agent/poll',{
            'policy_hash':self.stamp(),'busy':self.active is not None})['job']
        if not job:
            return {'claimed':False}
        try:
            encrypt({},job,aad(job))  # Recipient validated before any work/control or paid call.
        except (ValueError,TypeError):
            self.client.authenticated('/v1/agent/complete',{'request_id':job['request_id'],
                'lease':job['lease'],'status':'failed','envelope':None})
            return {'claimed':True}
        try:
            if not self._receipt(job):
                self._complete(job,snapshot(self.home,job['target_id'],job['channel']))
                return {'claimed':True}
            if job['action']=='run':
                # Persist receipt before starting the thread, so an immediate pause can fence it.
                with WorkStore(self.home/'work.sqlite3') as work:
                    did=work.create('agent:'+job['target_id'],self.node,job['query'],job['source_ids'])
                    work.enqueue(did,'on-demand')
            if job['action'] in ('run','resume'):
                deadline=time.monotonic()+job['remaining_seconds']-2
                self.active=job
                threading.Thread(target=self._execute,args=(job,deadline),daemon=True).start()
            else:
                if job['action'] in ('pause','cancel'):
                    with WorkStore(self.home/'work.sqlite3') as work:
                        row=work.db.execute('SELECT id FROM delegations WHERE request_id=?',
                            ('agent:'+job['target_id'],)).fetchone()
                        if row is None:
                            raise ValueError('agent_request_not_found')
                        work.control(row['id'],job['action'])
                self._complete(job,snapshot(self.home,job['target_id'],job['channel']))
        except (OSError,ValueError,TypeError,KeyError,sqlite3.Error) as error:
            self._complete(job,self.failure(error))
        return {'claimed':True}


def serve(home, stop, emit):
    worker=AgentWorker(home)
    try:
        while not stop.is_set():
            try:
                worker.once()
            except Exception as error:
                emit({'event':'agent_channel_error','error_type':type(error).__name__})
            stop.wait(2)
    finally:
        worker.stopped.set()
