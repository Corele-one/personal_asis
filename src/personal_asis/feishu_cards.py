"""Owner-only card forms and metadata receipts; no plaintext form persistence."""
import uuid

from .agent_roles import LABELS, MODES
from .coordinator import ProtocolError
from .data_policy import exclusion_reason
from .work import encoded, fingerprint


TTL=1800

def text(value):return {'tag':'plain_text','content':value}
def paragraph(value):return {'tag':'div','text':text(value)}

def button(session,action,label,*,form=False,primary=False):
    value={'asis_card':session['id'],'revision':str(session['revision']),'action':action}
    result={'tag':'button','text':text(label),'type':'primary' if primary else 'default',
            'behaviors':[{'type':'callback','value':value}]}
    if form:result.update(name='submit_'+action,form_action_type='submit')
    return result

def card(session,body=None):
    if body is None and not session.get('target_id'):
        elements=[paragraph('围绕研究、申请与职业、生活复盘提问。选择本次资料范围，结果会更新在这张卡片中。'),
            {'tag':'form','name':'new_work','elements':[
                paragraph('工作方式'),
                {'tag':'select_static','name':'mode','required':True,'initial_option':'auto','width':'fill',
                 'options':[{'text':text(label),'value':mode} for mode,label in (
                    ('auto','总管自动分工'),('research',LABELS['research']),('career',LABELS['career']),
                    ('life',LABELS['life']),('team','三个领域共同分析'))]},
                paragraph('资料范围'),
                {'tag':'select_static','name':'sources','required':True,'initial_option':'study','width':'fill',
                 'options':[{'text':text(label),'value':value} for value,label in (
                     ('study','Study'),('life','Life'),('study,life','Study + Life'))]},
                {'tag':'input','name':'question','required':True,'input_type':'multiline_text','max_length':512,
                 'placeholder':text('写下你的问题；说明希望核对的材料、目标和局限。')},
                button(session,'run','开始分析',form=True,primary=True)]},
            {'tag':'hr'},paragraph('继续已有工作'),
            {'tag':'form','name':'existing_work','elements':[
                {'tag':'input','name':'target','required':True,'max_length':36,'placeholder':text('粘贴原工作编号')},
                button(session,'lookup','查看原工作',form=True)]}]
    else:
        body=body or ('工作 '+session['target_id']+'\n指令已接收，等待 Mac 核实；不会自动重复模型调用。')
        # Plain text prevents model output becoming active links, mentions or buttons.
        bounded=body.encode()[:18000].decode('utf-8','ignore')
        elements=[paragraph(bounded[i:i+1800]) for i in range(0,len(bounded),1800)]
        if session.get('target_id'):
            elements.append(paragraph('工作编号：'+session['target_id']))
            elements.extend(button(session,action,label) for action,label in (
                ('status','刷新状态'),('pause','暂停这项工作'),('resume','明确恢复'),('cancel','取消工作')))
        elements.append(button(session,'new','新建问题'))
    elements.append(paragraph('由在线 Mac 检索获准资料，MiMo 共用现有预算。关闭卡片不会停止工作；新建问题也不会取消原工作。此卡片交互有效 30 分钟，过期后重新发送 /asis。'))
    return {'schema':'2.0','config':{'update_multi':True,'enable_forward':False},
            'header':{'template':'turquoise','title':text('Personal Asis · 个人助手')},
            'body':{'elements':elements}}


class Cards:
    def __init__(self,bridge):
        self.bridge=bridge;self.db=bridge.db
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS card_sessions (
                id TEXT PRIMARY KEY,platform TEXT NOT NULL,owner TEXT NOT NULL,source_message TEXT NOT NULL,
                card_message TEXT UNIQUE,revision INTEGER NOT NULL,target_id TEXT,state TEXT NOT NULL,
                created REAL NOT NULL,expires REAL NOT NULL,UNIQUE(platform,source_message));
            CREATE TABLE IF NOT EXISTS card_actions (
                command TEXT PRIMARY KEY,session TEXT NOT NULL,revision INTEGER NOT NULL,
                fingerprint TEXT NOT NULL,action TEXT NOT NULL,target_id TEXT,task_id TEXT,
                state TEXT NOT NULL,created REAL NOT NULL,UNIQUE(session,revision));
        ''')
        with self.db:
            self.db.execute('DELETE FROM card_actions WHERE created<?',(bridge.clock()-180*86400,))
            self.db.execute('DELETE FROM card_sessions WHERE expires<?',(bridge.clock()-180*86400,))

    def session(self,sid):
        row=self.db.execute('SELECT * FROM card_sessions WHERE id=?',(sid,)).fetchone()
        if row is None:raise ValueError('card_session_not_found')
        return dict(row)

    def create(self,platform,owner,message):
        if not self.bridge.authorized(platform,owner):raise ProtocolError('unauthorized',403)
        old=self.db.execute('SELECT id FROM card_sessions WHERE platform=? AND source_message=?',(platform,message)).fetchone()
        if old:return self.session(old[0]),False
        sid=str(uuid.uuid4());now=self.bridge.clock()
        with self.db:
            self.db.execute('INSERT INTO card_sessions VALUES(?,?,?,?,NULL,0,NULL,?,?,?)',
                            (sid,platform,owner,message,'sending',now,now+TTL))
        return self.session(sid),True

    def sent(self,sid,message):
        with self.db:
            self.db.execute('UPDATE card_sessions SET card_message=?,state=? WHERE id=?',
                (message,'ready' if message else 'unknown',sid))

    def accept(self,platform,owner,message,value,form):
        if not self.bridge.authorized(platform,owner):raise ValueError('card_owner_required')
        if not isinstance(value,dict) or set(value)!={'asis_card','revision','action'}:
            raise ValueError('card_invalid_action')
        current=self.session(value['asis_card'])
        if (current['platform']!=platform or current['owner']!=owner or current['card_message']!=message
                or current['state']!='ready' or current['expires']<=self.bridge.clock()):
            raise ValueError('card_expired_or_wrong_context')
        revision=value['revision'];action=value['action'];form=form or {}
        if not isinstance(revision,str) or revision!=str(current['revision']):
            # Old callbacks can neither reapply a resume nor start another paid work.
            return current,None,True
        if not isinstance(form,dict) or action not in ('run','lookup','status','pause','resume','cancel','new'):
            raise ValueError('card_invalid_action')
        query,sources,mode=None,None,None
        target=current['target_id']
        if action=='run':
            if target is not None or set(form)-{'question','sources','mode'}:
                raise ValueError('card_new_work_required')
            query=form.get('question');source=form.get('sources');mode=form.get('mode')
            if (not isinstance(query,str) or not query.strip() or len(query)>512 or exclusion_reason('',query)
                    or source not in ('study','life','study,life') or mode not in MODES):
                raise ValueError('card_invalid_form')
            query=query.strip();sources=source.split(',')
        elif action=='lookup':
            if set(form)!={'target'} or target is not None:raise ValueError('card_invalid_form')
            try:
                target=str(uuid.UUID(form['target']))
            except (ValueError,TypeError,AttributeError):raise ValueError('card_invalid_target') from None
        elif form or (action!='new' and target is None):
            raise ValueError('card_control_uses_saved_scope')
        command='card:'+current['id']+':'+revision
        if action=='run':
            target=str(uuid.uuid5(uuid.NAMESPACE_URL,f'asis-agent-work:{platform}:{owner}:{command}'))
        if action=='new':target=None
        digest=fingerprint([value,form])
        with self.db:
            # Compare-and-swap fences any concurrent callback at the old revision.
            changed=self.db.execute('UPDATE card_sessions SET revision=revision+1,target_id=? WHERE id=? AND revision=?',
                                    (target,current['id'],int(revision))).rowcount
            if not changed:return self.session(current['id']),None,True
            self.db.execute('INSERT INTO card_actions VALUES(?,?,?,?,?,?,NULL,?,?)',
                (command,current['id'],int(revision),digest,action,target,'accepted',self.bridge.clock()))
        job=None if action=='new' else {'session':current['id'],'revision':int(revision)+1,'command':command,
            'platform':platform,'owner':owner,'message':message,'action':'status' if action=='lookup' else action,
            'target_id':target,'query':query,'source_ids':sources,'mode':mode}
        return self.session(current['id']),job,False

    def submitted(self,job,task_id):
        with self.db:self.db.execute("UPDATE card_actions SET task_id=?,state='submitted' WHERE command=?",(task_id,job['command']))

    def current_job(self,job):
        session=self.session(job['session'])
        return (session['revision']==job['revision'] and session['target_id']==job['target_id']
            and session['expires']>self.bridge.clock()
            and self.bridge.authorized(job['platform'],job['owner']))

    def for_delivery(self,message,delivery):
        row=self.db.execute('''SELECT s.* FROM card_sessions s JOIN card_actions a ON a.session=s.id
            JOIN deliveries d ON d.task_id=a.task_id WHERE s.card_message=? AND d.id=?
            AND s.revision=a.revision+1 AND s.target_id=a.target_id''',(message,delivery)).fetchone()
        if row is None:return None
        session=dict(row)
        if session['expires']<=self.bridge.clock() or not self.bridge.authorized(session['platform'],session['owner']):return None
        return session
