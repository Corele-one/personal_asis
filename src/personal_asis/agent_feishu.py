"""Bound-owner Agent receipts. Durable routing only; payload/key lifetime is RAM-only."""

import base64
import hashlib
import json
import secrets
import uuid

from .agent_channel import AgentRelay, aad, relay_control
from .coordinator import ProtocolError
from .work import encoded, fingerprint


def summary(view):
    value=view['result']
    if value.get('kind')=='retrieval_v2':
        from .retrieval_channel import summary as retrieval_summary
        return retrieval_summary(value)
    if value.get('kind')=='domain_context':
        from .agent_roles import LABELS
        return LABELS[value['domain']]+' · 已保存的领域目标\n'+(value.get('goal') or '尚未保存目标。')+'\n约束：'+(value.get('constraints') or '无')+'\n未调用模型。'
    lines=[f"Agent 工作 {view['target_id']}"]
    if value.get('error'):
        from .analysis_channel import error_message
        messages={'agent_request_not_found':'Mac 未找到该工作，指令可能尚未到达或编号有误。',
            'agent_transport_expired_or_unavailable':'中转已过期或结果不可用，请用新消息查询原工作编号。',
            'inactive_or_stale_work_claim':'旧执行代次已停止，请查询当前工作状态。',
            'agent_channel_request_expired':'本轮执行期限已到，后续步骤停止。'}
        return '\n'.join(lines+[messages.get(value['error'],error_message(value['error'])),
            '不会自动重试模型调用。/asis agent-status 工作编号'])
    labels={'completed':'已完成','running':'执行中','queued':'等待执行','waiting_node':'等待恢复或核对',
            'paused':'已暂停','cancelled':'已取消','stopped':'本轮已停止'}
    lines.append(labels.get(value['state'],value['state']))
    if value['delegation_state'] in ('paused','cancelled'):
        lines.append('整项工作：'+labels[value['delegation_state']])
    lines.append(f"已提交 {value['committed_actions']} 个步骤；未知动作 {value['unresolved_executions']} 项。")
    if value.get('role_plan'):
        from .agent_roles import LABELS
        lines.append('总管分工：'+'、'.join(LABELS[r] for r in value['role_plan']['roles']))
        lines.extend(LABELS[r['role']]+'：'+labels.get(r['state'],r['state']) for r in value.get('roles',[]))
    if value['unresolved_executions']:
        lines.append('未知动作需本机核对；明确恢复也不会重做未知调用。')
    if value.get('result'):
        from .feishu import analysis_summary
        lines.extend(analysis_summary({'task_id':view['target_id'],'result':value['result']}).splitlines()[1:])
    lines.append('查询：/asis agent-status 编号；暂停：/asis pause 编号；恢复：/asis resume 编号；取消：/asis cancel 编号。')
    return '\n'.join(lines)[:20000]


class AgentInbox:
    def __init__(self, bridge):
        self.bridge=bridge
        self.keys={}
        bridge.db.execute('''CREATE TABLE IF NOT EXISTS agent_routes (
            task_id TEXT PRIMARY KEY, target_id TEXT NOT NULL, platform_id TEXT NOT NULL,
            open_id TEXT NOT NULL, message_id TEXT NOT NULL, action TEXT NOT NULL,
            fingerprint TEXT NOT NULL, created REAL NOT NULL, submitted INTEGER NOT NULL)''')
        with bridge.db:
            bridge.db.execute('DELETE FROM agent_routes WHERE created<?',(bridge.clock()-180*86400,))

    def submit(self, platform, owner, message, action, *, target_id=None, query=None, source_ids=None, mode=None, reply_message_id=None, defer_transport=False, use_context=None, role_history=None, context=None, web=None, public_queries=None, web_backend=None):
        b=self.bridge
        if not b.authorized(platform,owner):
            raise ProtocolError('unauthorized',403)
        task=str(uuid.uuid5(uuid.NAMESPACE_URL,f'asis-agent-command:{platform}:{owner}:{message}'))
        if action in ('run','context','retrieve'):
            target_id=str(uuid.uuid5(uuid.NAMESPACE_URL,f'asis-agent-work:{platform}:{owner}:{message}'))
        digest=fingerprint([platform,owner,message,action,target_id,query,source_ids])
        if mode is not None:
            digest=fingerprint([digest,mode])
        options={k:v for k,v in {'use_context':use_context,'role_history':role_history,'context':context,
                                'web':web,'public_queries':public_queries,'web_backend':web_backend}.items() if v is not None}
        if options:digest=fingerprint([digest,options])
        if reply_message_id is not None:
            if not isinstance(reply_message_id,str) or not 1<=len(reply_message_id)<=128:
                raise ProtocolError('invalid_agent_reply_message')
            digest=fingerprint([digest,reply_message_id])
        old=b.db.execute('SELECT * FROM agent_routes WHERE task_id=?',(task,)).fetchone()
        if old:
            if old['fingerprint']!=digest:
                raise ProtocolError('agent_request_conflict',409)
            return {'request_id':task,'target_id':old['target_id'],'duplicate':True,
                    'submitted':bool(old['submitted'])}
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        public=key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
        job={'request_id':task,'target_id':target_id,'action':action,'query':query,'source_ids':source_ids,
            'channel':'feishu','client_nonce':base64.b64encode(secrets.token_bytes(16)).decode(),
            'public_key':base64.b64encode(public).decode()}
        if mode is not None:
            job['mode']=mode
        job.update(options)
        AgentRelay().request(job)  # Strict schema/credential filtering before durable receipt.
        with b.db:
            b.db.execute('INSERT INTO agent_routes VALUES(?,?,?,?,?,?,?,?,0)',
                (task,target_id,platform,owner,reply_message_id or message,action,digest,b.clock()))
        self.keys[task]=(key,job,b.clock())
        if defer_transport:
            return {'request_id':task,'target_id':target_id,'duplicate':False,'submitted':False,'transport_payload':job}
        # Persist-before-send: ambiguous socket delivery never reissues an old control.
        relay_control(b.home,{'op':'request',**job})
        with b.db:
            b.db.execute('UPDATE agent_routes SET submitted=1 WHERE task_id=?',(task,))
        return {'request_id':task,'target_id':target_id,'duplicate':False,'submitted':True}

    def pending(self):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        b=self.bridge
        output=[]
        for task,(key,job,created) in list(self.keys.items()):
            row=b.db.execute('SELECT * FROM agent_routes WHERE task_id=?',(task,)).fetchone()
            if not row or not b.authorized(row['platform_id'],row['open_id']):
                self.keys.pop(task,None)
                continue
            if not row['submitted']:
                if b.clock()-created>900:
                    self.keys.pop(task,None)
                continue
            if b.db.execute('SELECT 1 FROM deliveries WHERE task_id=?',(task,)).fetchone():
                self.keys.pop(task,None)
                continue
            try:
                reply=relay_control(b.home,{'op':'get','request_id':task})
            except ProtocolError as error:
                if str(error)!='analysis_expired' and b.clock()-created<=900:
                    continue
                reply={'status':'expired'}
            except OSError:
                if b.clock()-created<=900:
                    continue
                reply={'status':'expired'}
            if reply['status'] in ('waiting','running') and b.clock()-created<=900:
                continue
            envelope_digest=None
            if reply['status']=='ready':
                e=reply['envelope']
                raw=key.decrypt(base64.b64decode(e['wrapped_key']),padding.OAEP(
                    mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
                plain=AESGCM(raw).decrypt(base64.b64decode(e['nonce']),base64.b64decode(e['ciphertext']),aad(job))
                value=json.loads(plain)
                envelope_digest=fingerprint(e)
            else:
                value={'error':'agent_transport_expired_or_unavailable','automatic_retry':False}
            view={'kind':'agent','task_id':task,'target_id':row['target_id'],'result':value,
                  '_envelope_digest':envelope_digest}
            output.append((dict(row),view,hashlib.sha256(encoded(value).encode()).hexdigest()))
        return output

    def ready_for_delivery(self, route, view):
        expected=view.get('_envelope_digest')
        if expected is None:
            return True  # Fixed error receipt contains no source evidence.
        try:
            reply=relay_control(self.bridge.home,{'op':'get','request_id':route['task_id']})
        except (ProtocolError,OSError):
            return False
        return reply['status']=='ready' and fingerprint(reply['envelope'])==expected
