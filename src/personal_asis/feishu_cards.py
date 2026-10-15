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

def _bounded(value,limit):
    value=value if isinstance(value,str) else ''
    raw=value.encode()
    return raw[:limit].decode('utf-8','ignore')+('…（显示已截断）' if len(raw)>limit else '')


def _section(title,body,limit=6000):
    body=_bounded(body,limit)
    return [paragraph('【'+title+'】')]+[paragraph(body[i:i+1200]) for i in range(0,len(body),1200)]


def result_elements(view,question=None):
    value=view.get('result',{})
    labels={'completed':'已完成','running':'处理中','queued':'等待执行','waiting_node':'等待恢复／核对',
            'paused':'已暂停','cancelled':'已取消','stopped':'本轮停止'}
    elements=[]
    query=value.get('question') or question
    if query:elements+=_section('你的问题',query,1600)+[{'tag':'hr'}]
    if value.get('error'):
        from .analysis_channel import error_message
        elements+=_section('系统回执 · 尚无新的 Agent 回答',error_message(value['error']),800)
        return elements
    state=labels.get(value.get('state'),'等待 Mac 核实')
    elements+=_section('系统状态',state+'；已提交 '+str(value.get('committed_actions',0))+' 个步骤。',500)
    answer=value.get('result')
    if answer:
        role='总管汇总' if answer.get('role_plan') else '本轮回应'
        elements += [{'tag':'hr'}]+_section('Agent 的回答 · '+role,answer.get('answer',''))
        if answer.get('uncertainty'):elements+=_section('回答的局限',answer['uncertainty'],1200)
        elements+=[{'tag':'hr'}]
        if answer.get('response_kind')=='conversation':
            elements+=_section('使用的信息','只使用你本轮发送的消息，未检索笔记或日记。',300)
        else:
            window=answer.get('temporal_scope') or value.get('temporal_scope')
            scope=(window['start']+' 至 '+window['end']+'；未纳入日期不明的笔记。') if window else '未指定时间范围；以下是历史资料，不代表你当前的状态。'
            if window and window.get('basis')=='recent_defaults_to_30_days':scope+=' “最近”本次按近 30 天处理。'
            if window and window.get('basis')=='question_months_as_30_days':scope+=' 相对月数按每月 30 天计算。'
            elements+=_section('本次检索范围',scope,600)
            elements+=_section('参考资料 · 原文摘录不是 Agent 的回答','',100)
            from .retrieval_time import note_date
            for entry in answer.get('evidence',[])[:6]:
                recorded=entry.get('record_date') or note_date(entry.get('path_hint',''),'')[0]
                label=entry.get('id','')+' · '+entry.get('source_id','')+' · 笔记日期：'+(recorded or '未标注')
                body=label+'\n'+entry.get('title','')+'\n原文摘录：'+_bounded(entry.get('excerpt',''),700)
                elements+=_section('资料 '+entry.get('id',''),body,1100)
    else:
        elements+=_section('Agent 的回答','尚未生成。状态回执不代表 Agent 已回答你的问题。',300)
    if value.get('role_context_used'):
        lines=[]
        for row in value['role_context_used']:
            label=LABELS.get(row['role'],row['role'])
            if row['used']:
                lines.append(label+'：已采用保存的目标；相关历史 '+str(len(row['history_used']))+' 条。')
                lines.extend('历史工作编号：'+entry['request_id'] for entry in row['history_used'])
            else:lines.append(label+'：未采用目标（未配置、待复核或许可／来源不匹配）。')
        elements+=_section('本次领域上下文','\n'.join(lines),1800)
    if value.get('roles'):
        progress='；'.join(LABELS.get(row['role'],row['role'])+'：'+labels.get(row['state'],row['state']) for row in value['roles'])
        elements+=_section('专业角色进度',progress,600)
    return elements


def context_elements(session,value=None):
    elements=[paragraph('领域目标由你明确保存，专业角色按需使用；不会自动变成个人事实或后台委托。')]
    if value:
        elements+=_section(LABELS[value['domain']]+' · 当前目标',value.get('goal') or '尚未保存目标。',6000)
        if value.get('constraints'):elements+=_section('已保存的约束',value['constraints'],12000)
        elements.append(paragraph('允许本条进入 MiMo：'+('是' if value['model_allowed'] else '否')+
                                  ('；需要你重新确认目标。' if value['needs_review'] else '')))
    elements.append({'tag':'form','name':'choose_domain','elements':[
        {'tag':'select_static','name':'domain','required':True,'initial_option':value['domain'] if value else 'research',
         'options':[{'text':text(LABELS[r]),'value':r} for r in ('research','career','life')]},
        button(session,'context_show','查看此领域',form=True)]})
    if value:
        save=button(session,'context_set','保存新目标和约束（替换当前）',form=True,primary=True)
        forget=button(session,'context_forget','删除此目标及关联工作上下文')
        for control in (save,forget):
            control['behaviors'][0]['value'].update(domain=value['domain'],expected_revision=str(value['revision']))
        elements.append({'tag':'form','name':'edit_domain','elements':[
            paragraph('填写新的完整目标和约束；不修改来源原文。'),
            {'tag':'input','name':'goal','required':True,'input_type':'multiline_text','max_length':512,'placeholder':text('新的领域目标')},
            {'tag':'input','name':'constraints','input_type':'multiline_text','max_length':512,'placeholder':text('约束或取舍（可留空，保存后替换旧约束）')},
            paragraph('目标适用的已配置来源'),
            {'tag':'select_static','name':'sources','required':True,'initial_option':','.join(value['source_ids']) if value['source_ids'] in (['study'],['life']) else 'study,life',
             'options':[{'text':text(label),'value':v} for v,label in (('study','Study'),('life','Life'),('study,life','Study + Life'))]},
            {'tag':'select_static','name':'permission','required':True,'initial_option':'mimo' if value['model_allowed'] else 'local',
             'options':[{'text':text('仅保存，暂不供模型使用'),'value':'local'}, {'text':text('允许本条目标／约束进入既有 MiMo'),'value':'mimo'}]},save]})
        if value.get('configured'):elements.append(forget)
    elements.append(button(session,'new','返回新建问题'))
    return elements


def card(session,body=None,*,view=None,question=None):
    if session.get('page')=='context':
        value=view.get('result') if view else None
        elements=[]
        if value and value.get('error'):
            elements+=_section('系统回执', '目标未变更或结果未知，请重新查看当前目标。'+value['error'],700)
            value=None
        elements+=context_elements(session,value if value and value.get('kind')=='domain_context' else None)
    elif body is None and view is None and not session.get('target_id'):
        elements=[paragraph('围绕研究、申请与职业、生活复盘提问。选择本次资料范围，结果会更新在这张卡片中。'),
            {'tag':'form','name':'new_work','elements':[
                paragraph('工作方式'),
                {'tag':'select_static','name':'mode','required':True,'initial_option':'auto','width':'fill',
                 'options':[{'text':text(label),'value':mode} for mode,label in (
                    ('auto','总管自动分工'),('research',LABELS['research']),('career',LABELS['career']),
                    ('life',LABELS['life']),('team','三个领域共同分析'),('conversation','倾听与鼓励（不读笔记）'))]},
                paragraph('领域连续性'),
                {'tag':'select_static','name':'continuity','required':True,'initial_option':'off',
                 'options':[{'text':text(label),'value':v} for v,label in (('off','只看本轮资料'),('goals','采用各角色已保存的目标'),('history','采用各角色目标和相关工作历史'))]},
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
                button(session,'lookup','查看原工作',form=True)]},button(session,'manage','管理领域目标')]
    else:
        if view is not None:
            elements=result_elements(view,question)
        elif body is not None:
            elements=_section('系统回执／旧版文字结果',body,17000)
        else:
            elements=[]
            if question:elements+=_section('你的问题',question,1600)
            elements+=_section('系统状态','指令已接收，等待 Mac 核实；尚无 Agent 的回答。',400)
        if session.get('target_id'):
            elements.append(paragraph('工作编号：'+session['target_id']))
            elements.extend(button(session,action,label) for action,label in (
                ('status','刷新状态'),('pause','暂停这项工作'),('resume','明确恢复'),('cancel','取消工作')))
        elements.append(button(session,'new','新建问题'))
    elements.append(paragraph('由在线 Mac 处理；需要检索时只使用获准资料，MiMo 共用现有预算。关闭卡片不会停止工作；新建问题也不会取消原工作。此卡片交互有效 30 分钟，过期后重新发送 /asis。'))
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
        # Keep the original table shape: retained older plugins use positional inserts.
        self.db.execute('CREATE TABLE IF NOT EXISTS card_pages (session TEXT PRIMARY KEY,page TEXT NOT NULL)')
        with self.db:
            self.db.execute('DELETE FROM card_actions WHERE created<?',(bridge.clock()-180*86400,))
            self.db.execute('DELETE FROM card_sessions WHERE expires<?',(bridge.clock()-180*86400,))
            self.db.execute('DELETE FROM card_pages WHERE session NOT IN (SELECT id FROM card_sessions)')

    def session(self,sid):
        row=self.db.execute('SELECT * FROM card_sessions WHERE id=?',(sid,)).fetchone()
        if row is None:raise ValueError('card_session_not_found')
        page=self.db.execute('SELECT page FROM card_pages WHERE session=?',(sid,)).fetchone()
        return {**dict(row),'page':page[0] if page else 'work'}

    def create(self,platform,owner,message):
        if not self.bridge.authorized(platform,owner):raise ProtocolError('unauthorized',403)
        old=self.db.execute('SELECT id FROM card_sessions WHERE platform=? AND source_message=?',(platform,message)).fetchone()
        if old:return self.session(old[0]),False
        sid=str(uuid.uuid4());now=self.bridge.clock()
        with self.db:
            self.db.execute('INSERT INTO card_sessions(id,platform,owner,source_message,card_message,revision,target_id,state,created,expires) VALUES(?,?,?,?,NULL,0,NULL,?,?,?)',
                            (sid,platform,owner,message,'sending',now,now+TTL))
        return self.session(sid),True

    def sent(self,sid,message):
        with self.db:
            self.db.execute('UPDATE card_sessions SET card_message=?,state=? WHERE id=?',
                (message,'ready' if message else 'unknown',sid))

    def accept(self,platform,owner,message,value,form):
        if not self.bridge.authorized(platform,owner):raise ValueError('card_owner_required')
        extra={'domain','expected_revision'} if isinstance(value,dict) and value.get('action') in ('context_set','context_forget') else set()
        if not isinstance(value,dict) or set(value)!={'asis_card','revision','action'}|extra:
            raise ValueError('card_invalid_action')
        current=self.session(value['asis_card'])
        if (current['platform']!=platform or current['owner']!=owner or current['card_message']!=message
                or current['state']!='ready' or current['expires']<=self.bridge.clock()):
            raise ValueError('card_expired_or_wrong_context')
        revision=value['revision'];action=value['action'];form=form or {}
        if not isinstance(revision,str) or revision!=str(current['revision']):
            # Old callbacks can neither reapply a resume nor start another paid work.
            return current,None,True
        if not isinstance(form,dict) or action not in ('run','lookup','status','pause','resume','cancel','new','manage','context_show','context_set','context_forget'):
            raise ValueError('card_invalid_action')
        query,sources,mode=None,None,None
        context=None;options={}
        target=current['target_id']
        if action.startswith('context_'):
            if current.get('page')!='context':raise ValueError('card_invalid_context_page')
            op=action.removeprefix('context_')
            if op=='show':
                if set(form)!={'domain'}:raise ValueError('card_invalid_form')
                context={'op':'show','domain':form['domain']}
            else:
                if not isinstance(value['expected_revision'],str) or not value['expected_revision'].isdigit():raise ValueError('card_invalid_form')
                context={'op':'set' if op=='set' else 'forget','domain':value['domain'],'expected_revision':int(value['expected_revision'])}
                if op=='set':
                    if set(form)-{'goal','constraints','sources','permission'} or form.get('sources') not in ('study','life','study,life') or form.get('permission') not in ('local','mimo'):raise ValueError('card_invalid_form')
                    context.update(goal=form.get('goal'),constraints=form.get('constraints') or '',source_ids=form['sources'].split(','),allow_model=form['permission']=='mimo')
                elif form:raise ValueError('card_invalid_form')
            from .context_commands import validate
            validate(context)
        elif action=='run':
            if target is not None or set(form)-{'question','sources','mode','continuity'}:
                raise ValueError('card_new_work_required')
            query=form.get('question');source=form.get('sources');mode=form.get('mode')
            if (not isinstance(query,str) or not query.strip() or len(query)>512 or exclusion_reason('',query)
                    or source not in ('study','life','study,life') or mode not in MODES):
                raise ValueError('card_invalid_form')
            continuity=form.get('continuity','off')
            if continuity not in ('off','goals','history') or (continuity!='off' and mode=='conversation'):raise ValueError('card_invalid_form')
            if continuity!='off':options={'use_context':True,'role_history':continuity=='history'}
            query=query.strip();sources=source.split(',')
        elif action=='lookup':
            if set(form)!={'target'} or target is not None:raise ValueError('card_invalid_form')
            try:
                target=str(uuid.UUID(form['target']))
            except (ValueError,TypeError,AttributeError):raise ValueError('card_invalid_target') from None
        elif form or (action not in ('new','manage') and target is None):
            raise ValueError('card_control_uses_saved_scope')
        command='card:'+current['id']+':'+revision
        if action=='run' or context:
            target=str(uuid.uuid5(uuid.NAMESPACE_URL,f'asis-agent-work:{platform}:{owner}:{command}'))
        if action in ('new','manage'):target=None
        digest=fingerprint([value,form])
        with self.db:
            # Compare-and-swap fences any concurrent callback at the old revision.
            changed=self.db.execute('UPDATE card_sessions SET revision=revision+1,target_id=? WHERE id=? AND revision=?',
                                    (target,current['id'],int(revision))).rowcount
            if not changed:return self.session(current['id']),None,True
            self.db.execute('INSERT OR REPLACE INTO card_pages VALUES(?,?)',(current['id'],'context' if action=='manage' or context else 'work'))
            self.db.execute('INSERT INTO card_actions VALUES(?,?,?,?,?,?,NULL,?,?)',
                (command,current['id'],int(revision),digest,action,target,'accepted',self.bridge.clock()))
        job=None if action in ('new','manage') else {'session':current['id'],'revision':int(revision)+1,'command':command,
            'platform':platform,'owner':owner,'message':message,'action':'context' if context else 'status' if action=='lookup' else action,
            'target_id':target,'query':query,'source_ids':sources,'mode':mode,**options,**({'context':context} if context else {})}
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
        session=self.session(row['id'])
        if session['expires']<=self.bridge.clock() or not self.bridge.authorized(session['platform'],session['owner']):return None
        return session
