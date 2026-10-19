"""Native Pi terminal transport. Python owns all data, paid work and permissions."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid

from . import agent, pa1
from .config import load_pa1_config
from .data_policy import exclusion_reason
from .work import WorkStore

RUNTIME = Path(__file__).resolve().parents[2]/'runtime/pi-terminal'
MODES = ('auto','research','career','life','team','conversation')


def safe_error(error):
    value = str(error)
    return value if re.fullmatch(r'[a-z][a-z0-9_:.-]{0,160}',value) else 'terminal_request_failed_check_local_status'


def render(value):
    result = value.get('result')
    if not result:
        return '工作状态：'+value['status']+'。未自动重试。'
    text = result['answer']
    if result.get('uncertainty'):
        text += '\n\n资料局限：'+result['uncertainty']
    evidence = result.get('evidence',[])
    if evidence:
        text += '\n\n资料来源：\n'+'\n'.join(
            '- ['+e['id']+'] '+e['title'] for e in evidence if e['id'] in result.get('citations',[]))
    return text


class Chats:
    def __init__(self, home):
        self.home = Path(home)
        self.db = sqlite3.connect(self.home/'terminal.sqlite3',timeout=20)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS chats (
            id TEXT PRIMARY KEY, at REAL NOT NULL, sources TEXT NOT NULL, mode TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS turns (
            chat TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE, seq INTEGER NOT NULL,
            request TEXT NOT NULL UNIQUE, PRIMARY KEY(chat,seq));''')
        self.db.execute('DELETE FROM chats WHERE at<?',(time.time()-30*86400,))
        self.db.commit()
        (self.home/'terminal.sqlite3').chmod(0o600)

    def close(self): self.db.close()

    def create(self, sources, mode):
        config=load_pa1_config(self.home)
        if (not isinstance(sources,list) or not sources or set(sources)-{s.id for s in config.sources}
                or mode not in MODES):
            raise ValueError('terminal_invalid_scope_or_mode')
        cid=str(uuid.uuid4())
        self.db.execute('INSERT INTO chats VALUES(?,?,?,?)',(cid,time.time(),json.dumps(sources),mode))
        self.db.commit()
        return cid

    def get(self, cid):
        row=self.db.execute('SELECT * FROM chats WHERE id=?',(cid,)).fetchone()
        if row is None:raise ValueError('terminal_chat_not_found')
        return dict(row)

    def turns(self, cid):
        self.get(cid)
        return [r[0] for r in self.db.execute('SELECT request FROM turns WHERE chat=? ORDER BY seq',(cid,))]

    def load(self, cid):
        chat=self.get(cid);messages=[];last=None
        # No transcript copies: authority and 30-day/source checks are in WorkStore.
        for rid in self.turns(cid):
            value=agent.inspect(self.home,rid)
            with WorkStore(self.home/'work.sqlite3') as work:
                view=work.view(value['delegation_id'])
            messages.append({'question':view['goal'],'answer':render(value),'request_id':rid})
            last=rid
        return {'thread':cid,'sources':json.loads(chat['sources']),'mode':chat['mode'],
                'messages':messages,'last_request':last}

    def add(self, cid, request, expected=None):
        if not re.fullmatch(r'terminal-[a-f0-9-]{36}',request):raise ValueError('terminal_invalid_request_id')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            ids=self.turns(cid)
            if request in ids:return
            if expected is not None and ids!=expected:
                raise ValueError('terminal_chat_changed_reload_before_new_turn')
            if len(ids)>=32:raise ValueError('terminal_chat_limit_start_new_chat')
            self.db.execute('INSERT INTO turns VALUES(?,?,?)',(cid,len(ids)+1,request))

    def drop(self,cid):
        for rid in self.turns(cid):
            try:
                value=agent.inspect(self.home,rid)
                with WorkStore(self.home/'work.sqlite3') as work:
                    work.control(value['delegation_id'],'cancel')
                    work.clean(value['delegation_id'])
            except ValueError:
                # Missing/invalid results must still be cleared without reading their body.
                with WorkStore(self.home/'work.sqlite3') as work:
                    row=work.db.execute('SELECT id FROM delegations WHERE request_id=?',('agent:'+rid,)).fetchone()
                    if row:
                        work.control(row['id'],'cancel');work.clean(row['id'])
        with self.db:self.db.execute('DELETE FROM chats WHERE id=?',(cid,))


def handle(home, request, emit=lambda value:None):
    home=Path(home)
    action=request.get('action')
    chats=Chats(home)
    try:
        cid=request.get('thread')
        if action=='new':
            return chats.load(chats.create(request['sources'],request.get('mode','auto')))
        if action=='list':
            return {'chats':[dict(r) for r in chats.db.execute('SELECT id,at,mode FROM chats ORDER BY at DESC LIMIT 50')]}
        if action=='load':return chats.load(cid)
        if action=='forget':
            chats.drop(cid);return {'forgotten':True}
        if action not in ('run','status','resume','pause','cancel'):raise ValueError('terminal_unknown_action')
        chat=chats.get(cid);ids=chats.turns(cid)
        if action=='run':
            query=request.get('query')
            if not isinstance(query,str) or not query.strip() or len(query)>512 or exclusion_reason('',query):
                raise ValueError('terminal_invalid_question')
            rid=request['request_id']
            # Refuse silent continuation past unresolved or invalid work.
            prior=[]
            for old in ids:
                if old==rid:continue
                value=agent.inspect(home,old)
                if value['status']!='completed':raise ValueError('terminal_previous_turn_unfinished_use_status_or_new')
                prior.append(old)
            chats.add(cid,rid,expected=ids)
            mode=chat['mode']
            if mode=='auto' and re.fullmatch(r'\s*(你好|您好|谢谢|早上好|晚安|hello|hi)[！!。 .]*',query,re.I):
                mode='conversation'
            value=agent.execute(home,query,rid,json.loads(chat['sources']),mode=mode,
                                terminal_history=prior[-2:],on_event=emit)
        else:
            if not ids:raise ValueError('terminal_chat_has_no_work')
            rid=ids[-1]
            if action=='resume':value=agent.execute(home,None,rid,resume=True,on_event=emit)
            else:
                value=agent.inspect(home,rid)
                if action in ('pause','cancel'):
                    with WorkStore(home/'work.sqlite3') as work:
                        work.control(value['delegation_id'],action)
                    value=agent.inspect(home,rid)
        return {'thread':cid,'request_id':rid,'status':value['status'],'text':render(value),
                'cached':value.get('cached',False),'usage':value.get('result',{}).get('usage'),
                'model_turns':value.get('result',{}).get('model_turns'),
                'searches':value.get('result',{}).get('searches')}
    finally:chats.close()


def worker():
    def output(value):
        try:
            print(json.dumps(value,ensure_ascii=False),flush=True)
        except (BrokenPipeError,OSError):pass
    def interrupted(signum,frame):raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM,interrupted)
    try:
        line=sys.stdin.buffer.readline(65537)
        if len(line)>65536:raise ValueError('terminal_input_too_large')
        data=json.loads(line)
        result=handle(Path(data['home']),data['request'],lambda event:output(
            {'kind':'progress','stage':event['kind'],**{k:v for k,v in event.items() if k!='kind'}}))
        output({'kind':'result','value':result})
    except BaseException as error:
        output({'kind':'error','error':safe_error(error)})
        return 1
    return 0


def main(argv=None):
    parser=argparse.ArgumentParser(description='Mac 本机 Pi 原生终端个人助手')
    parser.add_argument('--home',type=Path,default=Path.home()/'Library/Application Support/PersonalAsis')
    parser.add_argument('--source',action='append')
    parser.add_argument('--mode',choices=MODES,default='auto')
    parser.add_argument('--continue',dest='continued',action='store_true')
    parser.add_argument('--chat')
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args(argv)
    if args.worker:return worker()
    try:
        home=args.home.expanduser().resolve()
        data=pa1.settings(home);node=shutil.which('node')
        if not node or not (RUNTIME/'node_modules/@earendil-works/pi-coding-agent').is_dir():
            raise ValueError('optional_pi_terminal_not_installed')
        sources=args.source or ['study','life']
        config=load_pa1_config(home)
        if set(sources)-{s.id for s in config.sources}:raise ValueError('terminal_unknown_source')
        if args.check:
            print(json.dumps({'native_pi_terminal':True,'pi_version':'1.2.0','model':data['model'],
                'enabled':data['enabled'],'sources':sources,'default_mode':args.mode,
                'feishu_or_vps_required':False,'model_generation_calls':0}))
            return 0
        if not sys.stdin.isatty() or not sys.stdout.isatty():raise ValueError('terminal_requires_interactive_tty')
        with tempfile.TemporaryDirectory(prefix='asis-native-pi-') as tmp:
            # SDK sees no owner home, credentials, user config, project or Node startup injection.
            env={k:os.environ[k] for k in ('TERM','COLORTERM','LANG','LC_CTYPE','TERM_PROGRAM') if k in os.environ}
            tools=[str(Path(p).parent) for name in ('rg','fd') if (p:=shutil.which(name))]
            env.update(HOME=tmp,TMPDIR=tmp,PATH=os.pathsep.join(dict.fromkeys((str(Path(node).parent),*tools,'/usr/bin','/bin','/usr/sbin','/sbin'))),
                PI_OFFLINE='1',PI_SKIP_VERSION_CHECK='1',DO_NOT_TRACK='1')
            cfg={'home':str(home),'owner_home':str(Path.home()),'python':sys.executable,'model':data['model'],
                 'pythonpath':str(Path(__file__).resolve().parents[1]),'sources':sources,'mode':args.mode,
                 'thread':args.chat,'continue':args.continued,'temporary':tmp}
            path=Path(tmp)/'config.json';path.write_text(json.dumps(cfg));path.chmod(0o600)
            return subprocess.run([node,str(RUNTIME/'terminal.mjs'),str(path)],cwd=tmp,env=env).returncode
    except (OSError,ValueError) as error:
        print(safe_error(error),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
