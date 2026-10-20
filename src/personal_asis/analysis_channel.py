"""Owner-only PA1 relay, bounded to RAM; model execution and durable results stay Mac-side."""

import base64
from contextlib import closing
import hashlib
import json
from pathlib import Path
import secrets
import re
import signal
import sqlite3
import time
import uuid
import threading

from .coordinator import ProtocolError, exact
from .data_policy import exclusion_reason
from .disclosure import validate_result  # Preserve the legacy adapter import contract.
from .evidence import Relay, encrypt, control


def aad(job):
    return '\n'.join(('analysis',job['request_id'],job['client_nonce'],job['channel'])).encode()


def relay_control(home,data):
    return control(home,data,'analysis.sock')


def error_message(code):
    if code.startswith('model_output_'):
        return '模型回答未通过引用或格式校验，本轮结果未展示；实际用量已计入共享预算。'
    if 'unknown' in code or 'not_retryable' in code:
        return '原请求已执行或结果未知，系统保留计费与防重状态，不会自动再次付费。'
    if 'budget_exhausted' in code:
        return '已达到设定的模型预算，本机资料搜索仍可使用。'
    if code.startswith(('context_','analysis_permission')):
        return '资料版本或权限发生变化，已停止展示本轮结果。'
    if code.startswith('research_'):
        return '未取得足够的可用公开证据；请补充明确的公开原始链接。'
    if code.startswith('no_current_'):
        return '没有检索到当前获准模型使用的证据，请调整问题或资料范围。'
    return '本轮未能生成通过校验的回答；系统保留计费和防重状态。'


def validate_request(data):
    exact(data,('request_id','query','channel','source_ids','research','client_nonce','public_key'))
    try:
        if not isinstance(data['request_id'],str) or str(uuid.UUID(data['request_id']))!=data['request_id']:
            raise ValueError()
        nonce=base64.b64decode(data['client_nonce'],validate=True)
        public=base64.b64decode(data['public_key'],validate=True)
        # Coordinator only relays bounded opaque key bytes. Actual RSA type,
        # size and OAEP validation happen at the source-holding Mac.
        if len(nonce)!=16 or not 200<=len(public)<=600:
            raise ValueError()
    except (ValueError,TypeError):
        raise ProtocolError('invalid_analysis_key') from None
    if (not isinstance(data['query'],str) or not 1<=len(data['query'].strip())<=512
            or exclusion_reason('',data['query']) or data['channel'] not in ('pwa','feishu')):
        raise ProtocolError('invalid_analysis_query')
    sources=data['source_ids']
    if sources is not None and (not isinstance(sources,list) or not sources or len(sources)>20
            or any(not isinstance(s,str) or not s or len(s)>64 for s in sources)):
        raise ProtocolError('invalid_analysis_sources')
    research=data['research']
    if research is not None and (not isinstance(research,dict) or set(research)!={'public_query','urls'}
            or not isinstance(research['public_query'],str) or not 1<=len(research['public_query'])<=240
            or exclusion_reason('',research['public_query']) or not isinstance(research['urls'],list)
            or len(research['urls'])>3 or any(not isinstance(u,str) or len(u)>2000 for u in research['urls'])):
        raise ProtocolError('invalid_research_request')


class AnalysisRelay(Relay):
    def __init__(self,clock=time.monotonic):
        super().__init__(clock,ttl=900)
        self.stamp=None

    def _prune(self):
        super()._prune()
        for value in self.jobs.values():
            if value['ready_at'] is not None and self.clock()-value['ready_at']>30:
                value['status'],value['envelope']='expired',None

    def request(self,data):
        validate_request(data)
        digest=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
        with self.lock:
            self._prune()
            old=self.jobs.get(data['request_id'])
            if old:
                if old['digest']!=digest:
                    raise ProtocolError('analysis_request_conflict',409)
            else:
                if len(self.jobs)>=16:
                    raise ProtocolError('analysis_busy',429)
                self.jobs[data['request_id']]={**data,'node_id':'mac','digest':digest,
                    'expires':self.clock()+self.ttl,'lease':None,'lease_until':0,
                    'status':'waiting','envelope':None,'ready_at':None}
            return {'request_id':data['request_id'],'status':self.jobs[data['request_id']]['status'],'expires_in':self.ttl}

    def poll(self,node,stamp):
        with self.lock:
            self._prune()
            if node!='mac':
                return {'job':None}
            if self.stamp is not None and stamp!=self.stamp:
                for v in self.jobs.values():
                    if v['status']=='ready':
                        v['status'],v['envelope']='revoked',None
            self.stamp=stamp
            for v in self.jobs.values():
                if v['status'] in ('waiting','running') and self.clock()>=v['lease_until']:
                    v['lease'],v['lease_until']=secrets.token_urlsafe(24),v['expires']
                    v['status']='running'
                    return {'job':{**{k:v[k] for k in ('request_id','query','channel','source_ids','research','client_nonce','public_key','lease')},
                                   'remaining_seconds':max(0,v['expires']-self.clock())}}
            return {'job':None}

    def complete(self,node,data):
        # The reader validator checks bounded envelope and an active lease.
        with self.lock:
            v=self.jobs.get(data.get('request_id'))
            if v and v['status']=='running':
                v['status']='waiting'
        try:
            result=super().complete(node,data)
        finally:
            with self.lock:
                v=self.jobs.get(data.get('request_id'))
                if v and v['status']=='waiting':
                    v['status']='running'
        with self.lock:
            v=self.jobs[data['request_id']]
            v['ready_at']=self.clock()
        return result

    def get(self,request_id):
        with self.lock:
            self._prune()
            v=self.jobs.get(request_id)
            if not v:
                raise ProtocolError('analysis_expired',404)
            if v['ready_at'] is not None and self.clock()-v['ready_at']>30:
                v['status'],v['envelope']='expired',None
            return {'request_id':request_id,'status':v['status'],'envelope':v['envelope'],
                    'plan':'检索获准资料 → 核对证据'+(' → 读取公开资料与交叉核对' if v['research'] else '')+' → 预算内分析与引用校验'}


class Worker:
    def __init__(self,home,client=None,analyzer=None):
        from .node import Client,connection_config
        from .config import load_config
        self.home=Path(home)
        self.node=load_config(self.home/'sources.yaml').node_id
        self.client=client or Client(connection_config(self.home),self.node)
        self.analyzer=analyzer
        self.encoder=None
        self.encoder_stamp=None

    def stamp(self):
        from .node import node_policy_hash
        from .config import load_config
        config=load_config(self.home/'sources.yaml')
        values=[node_policy_hash(self.home,config)]
        # Disk changes revoke a pending disclosure even before the six-hour
        # index reconcile. Only stat signatures enter this digest.
        roots={source.id:source.root for source in config.sources}
        with closing(sqlite3.connect(self.home/'index.sqlite3')) as db:
            rows=db.execute('SELECT document_id,source_id,path FROM documents WHERE active=1 ORDER BY document_id').fetchall()
        for doc,source,path in rows:
            try:
                stat=(roots[source]/path).stat()
                values.append((doc,stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns))
            except (OSError,KeyError):
                values.append((doc,'missing'))
        for filename in ('pa1.json','pa1-policy.json'):
            path=self.home/filename
            values.append(hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else '')
        return hashlib.sha256(json.dumps(values).encode()).hexdigest()

    def once(self):
        from . import pa1
        before=self.stamp()
        job=self.client.authenticated('/v1/analysis/poll',{'policy_hash':before})['job']
        if not job:
            return {'claimed':False}
        deadline=time.monotonic()+job.get('remaining_seconds',900)-2
        def before_model():
            if time.monotonic()>=deadline:
                raise ValueError('analysis_request_expired_before_model')
        try:
            # Validate the actual recipient key before any paid model request.
            encrypt({},job,aad(job))
        except (ValueError,TypeError):
            self.client.authenticated('/v1/analysis/complete',{'request_id':job['request_id'],
                'lease':job['lease'],'status':'failed','envelope':None})
            return {'claimed':True,'status':'failed'}
        status,envelope='failed',None
        try:
            # Read cache by durable request identity FIRST. Replays cannot refetch
            # public evidence or change a fingerprint to trigger another paid call.
            ledger=pa1.budget(self.home,self.node,pa1.settings(self.home))
            try:
                old=ledger.db.execute('SELECT response,state FROM model_calls WHERE node=? AND request_id=?',
                                      (self.node,job['request_id'])).fetchone()
            finally:
                ledger.close()
            if old:
                if old['state']!='succeeded' or old['response'] is None:
                    raise ValueError('analysis_previous_result_not_retryable')
                value=json.loads(old['response'])
                # Identity binds question, source filter, and explicit public request.
                expected=hashlib.sha256(json.dumps([job['query'],job['source_ids'],job['research']],sort_keys=True).encode()).hexdigest()
                if value.get('channel_request_fingerprint')!=expected:
                    raise ValueError('analysis_request_conflict')
                value['cached']=True
            else:
                if self.analyzer:
                    value=self.analyzer(self.home,job)
                else:
                    data=pa1.settings(self.home)
                    stamp=json.dumps([data[k] for k in ('semantic_model_dir','semantic_query_prefix','semantic_document_prefix')])
                    if self.encoder_stamp!=stamp:
                        self.encoder,_=pa1.encoder_for(data)
                        self.encoder_stamp=stamp
                    value=pa1.analyze(self.home,job['query'],job['request_id'],source_ids=job['source_ids'],
                                      research=job['research'],encoder_override=self.encoder,
                                      request_identity=hashlib.sha256(json.dumps([job['query'],job['source_ids'],job['research']],sort_keys=True).encode()).hexdigest(),
                                      before_model=before_model,channel=job['channel'])
                value['channel_request_fingerprint']=hashlib.sha256(json.dumps(
                    [job['query'],job['source_ids'],job['research']],sort_keys=True).encode()).hexdigest()
                # Persist the channel identity alongside the already validated local result.
                with closing(sqlite3.connect(self.home/'pa1.sqlite3')) as db, db:
                    db.execute('UPDATE model_calls SET response=? WHERE node=? AND request_id=? AND state=\'succeeded\'',
                               (json.dumps(value,ensure_ascii=False),self.node,job['request_id']))
            if before!=self.stamp() or not pa1.settings(self.home)['enabled']:
                raise ValueError('analysis_permission_changed')
            value=validate_result(self.home,value,job['channel'])
            envelope=encrypt(value,job,aad(job))
            status='ready'
        except (OSError,ValueError,TypeError,KeyError,sqlite3.Error) as exc:
            # Error payload is encrypted too; neither personal content nor provider
            # responses are included in server logs or durable coordination state.
            code=str(exc)
            allowed=('model_','pa1_','research_','context_','no_current_','analysis_','mimo_')
            code=code if code.startswith(allowed) and re.fullmatch(r'[a-z_]+(?::[a-z_]+)?',code) and len(code)<120 else 'analysis_failed'
            envelope=encrypt({'error':code,'retry_automatically':False},job,aad(job))
            status='ready'
        self.client.authenticated('/v1/analysis/complete',{'request_id':job['request_id'],
            'lease':job['lease'],'status':status,'envelope':envelope})
        return {'claimed':True,'status':status}


def serve_worker(home,emit):
    stop=False
    agent_stop=threading.Event()
    def shutdown(*_):
        nonlocal stop
        stop=True
        agent_stop.set()
    signal.signal(signal.SIGTERM,shutdown)
    signal.signal(signal.SIGINT,shutdown)
    worker=Worker(home)
    from .agent_channel import serve as serve_agent
    agent_thread=threading.Thread(target=serve_agent,args=(home,agent_stop,emit),daemon=True)
    agent_thread.start()
    while not stop:
        try:
            value=worker.once()
            if value['claimed']:
                emit({'event':'analysis_completed','status':value['status']})
        except Exception as exc:
            emit({'event':'analysis_transport_error','error_type':type(exc).__name__})
        for _ in range(3):
            if stop:
                break
            time.sleep(1)
