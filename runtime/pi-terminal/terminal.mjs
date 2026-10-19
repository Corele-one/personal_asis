// Native Pi UI only. No direct model endpoint, credential, file or shell tools.
import fs from 'node:fs';
import net from 'node:net';
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';

// Defense in depth for the UI process; Python is the only network/model owner.
net.Socket.prototype.connect = function () { throw new Error('asis_ui_network_disabled'); };
globalThis.fetch = async () => { throw new Error('asis_ui_network_disabled'); };

const { createAgentSession, createAgentSessionRuntime, ModelRuntime, SettingsManager,
  SessionManager, DefaultResourceLoader, InteractiveMode } = await import('@earendil-works/pi-coding-agent');
const { AssistantMessageEventStream } = await import('@earendil-works/pi-ai/utils/event-stream');
const { Type } = await import('typebox');

export function worker(config, request, onProgress, signal) {
  return new Promise((resolve, reject) => {
    const env = { HOME:config.owner_home, PATH:process.env.PATH, LANG:'en_US.UTF-8',
      PYTHONPATH:config.pythonpath, HF_HUB_OFFLINE:'1', TRANSFORMERS_OFFLINE:'1',
      HF_HUB_DISABLE_TELEMETRY:'1', TOKENIZERS_PARALLELISM:'false' };
    const child = spawn(config.python, ['-m','personal_asis.pi_terminal','--worker'],
      { cwd:config.temporary, env, stdio:['pipe','pipe','ignore'] });
    let settled=false, seen=0;
    const abort=()=>{ child.kill('SIGTERM'); };
    signal?.addEventListener('abort',abort,{once:true});
    if (signal?.aborted) abort();
    const lines=createInterface({input:child.stdout});
    lines.on('line',line=>{
      if (settled) return;
      seen+=Buffer.byteLength(line);
      if (seen>2*1024*1024) { abort();reject(new Error('terminal_worker_output_limit'));settled=true;return; }
      try {
        const event=JSON.parse(line);
        if (event.kind==='progress') onProgress?.(event);
        else if (event.kind==='result') { settled=true;resolve(event.value); }
        else if (event.kind==='error') { settled=true;reject(new Error(event.error)); }
      } catch { settled=true;abort();reject(new Error('terminal_worker_protocol_error')); }
    });
    child.on('error',()=>{if(!settled){settled=true;reject(new Error('terminal_worker_start_failed'));}});
    child.on('close',()=>{
      signal?.removeEventListener('abort',abort);lines.close();
      if(!settled)reject(new Error('terminal_worker_interrupted_check_status_no_retry'));
    });
    child.stdin.on('error',()=>{});
    child.stdin.end(JSON.stringify({home:config.home,request})+'\n');
  });
}

const contentText = content => typeof content==='string' ? content : (content??[]).filter(c=>c.type==='text').map(c=>c.text).join('');
const emptyUsage = () => ({input:0,output:0,cacheRead:0,cacheWrite:0,totalTokens:0,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}});
export function hostStream(model, context) {
  const stream=new AssistantMessageEventStream();
  const last=context.messages.at(-1);
  let content,reason='stop',usage=emptyUsage();
  if(last?.role==='toolResult') {
    // Tool output is host-assembled, never a fresh model generation.
    const details=last.details??{};
    content=[{type:'text',text:contentText(last.content)}];
    if(details.usage) usage={...usage,input:details.usage.prompt_tokens,output:details.usage.completion_tokens,totalTokens:details.usage.total_tokens};
  } else {
    const user=[...context.messages].reverse().find(m=>m.role==='user');
    const query=contentText(user?.content);
    content=[{type:'toolCall',id:'host_'+randomUUID().replaceAll('-',''),name:'personal_assistant',
      arguments:{query,request_id:'terminal-'+randomUUID()}}];reason='toolUse';
  }
  const message={role:'assistant',content,stopReason:reason,api:model.api,provider:model.provider,
    model:model.id,timestamp:Date.now(),usage};
  stream.push({type:'start',partial:message});
  stream.push({type:'done',reason,message});stream.end(message);return stream;
}

export async function createTerminal(config, invoke=worker) {
  let selected=config.thread??null;
  if(config.continue && !selected) selected=(await invoke(config,{action:'list'})).chats[0]?.id??null;
  let thread,ui,scope=config.sources,role=config.mode;
  const modelRuntime=await ModelRuntime.create({authPath:config.temporary+'/auth.json',modelsPath:null,
    modelsStorePath:config.temporary+'/catalog.json',allowModelNetwork:false,refreshOnCreate:false});
  modelRuntime.registerProvider('asis-local', {api:'asis-host',baseUrl:'http://127.0.0.1/unused-host-transport',
    apiKey:'local-transport-placeholder',streamSimple:hostStream,
    models:[{id:config.model??'mimo-v2.6-flash',name:'Personal Asis · '+(config.model??'MiMo Flash')+'（原共享预算）',reasoning:false,input:['text'],
      contextWindow:16000,maxTokens:512,cost:{input:0,output:0,cacheRead:0,cacheWrite:0}}]});
  const model=modelRuntime.getModel('asis-local',config.model??'mimo-v2.6-flash');
  const factory=async()=>{
    const loaded=await invoke(config,selected ? {action:'load',thread:selected} : {action:'new',sources:config.sources,mode:config.mode});
    thread=loaded.thread;selected=thread;
    scope=loaded.sources??config.sources;role=loaded.mode??config.mode;
    const settingsManager=SettingsManager.inMemory({compaction:{enabled:false},retry:{enabled:false,maxRetries:0,provider:{maxRetries:0}},
      cacheWarming:'off',quietStartup:true,images:{blockImages:true},
      enableSkillCommands:false,sessionDir:config.temporary+'/sessions'});
    const resourceLoader=new DefaultResourceLoader({cwd:config.temporary,agentDir:config.temporary,
      settingsManager,noExtensions:true,noSkills:true,noPromptTemplates:true,noThemes:true,noContextFiles:true,
      systemPrompt:'本机个人助手界面。资料与模型调用由独立Python宿主管理。'});
    await resourceLoader.reload();
    const manager=SessionManager.inMemory(config.temporary);
    for(const m of loaded.messages) {
      manager.appendMessage({role:'user',content:[{type:'text',text:m.question}],timestamp:Date.now()});
      manager.appendMessage({role:'assistant',content:[{type:'text',text:m.answer}],stopReason:'stop',
        api:model.api,provider:model.provider,model:model.id,timestamp:Date.now(),usage:emptyUsage()});
    }
    manager.appendSessionInfo('Personal Asis · '+thread.slice(0,8));
    const tools=[{name:'personal_assistant',label:'个人助手',description:'本机获准资料、角色与共享预算',
      parameters:Type.Object({query:Type.String(),request_id:Type.String()}),
      execute:async(_id,args,signal,onUpdate)=>{
        const active=thread;
        const update=text=>onUpdate?.({content:[{type:'text',text}],details:{}});
        update('正在准备获准上下文…');
        try {
          const result=await invoke(config,{action:'run',thread:active,query:args.query,request_id:args.request_id},
            event=>update(event.stage==='tool' ? '资料检索 · '+event.phase : '模型步骤 '+(event.turn??'')+' · '+event.phase),signal);
          return {content:[{type:'text',text:result.text}],details:result};
        } catch(error) {
          return {content:[{type:'text',text:'本次停止：'+error.message+'\n使用 /status 查看；不会自动重试。'}],
            details:{failed:true},isError:true};
        }
      }}];
    const result=await createAgentSession({cwd:config.temporary,agentDir:config.temporary,modelRuntime,model,
      thinkingLevel:'off',scopedModels:[{model,thinkingLevel:'off'}],settingsManager,resourceLoader,
      sessionManager:manager,tools:['personal_assistant'],customTools:tools});
    // Bypass the SDK provider path entirely. Even a UI setting cannot send a direct call.
    result.session.agent.streamFunction=hostStream;
    result.session.executeBash=async()=>{throw new Error('terminal_shell_disabled');};
    const services={cwd:config.temporary,agentDir:config.temporary,modelRuntime,settingsManager,resourceLoader,diagnostics:[]};
    return {...result,services,diagnostics:[]};
  };
  const runtime=await createAgentSessionRuntime(factory,{cwd:config.temporary,agentDir:config.temporary,
    sessionManager:SessionManager.inMemory(config.temporary)});
  ui=new InteractiveMode(runtime,{tuiMode:'fullscreen',startupDiagnostics:[{type:'info',message:
    'Personal Asis · 本机直连 · '+scope.join(' / ')+' · '+role+'\n/new 新聊天 · /chats 列表 · /open ID 恢复 · /status 状态 · /quit 退出'}]});
  // The UI's synthetic transport has no price rate. Never display its $0 as actual cloud cost.
  ui.footer.render=width=>{
    const tokens=runtime.session.agent.state.messages.filter(m=>m.role==='assistant')
      .reduce((n,m)=>n+(m.usage?.totalTokens??0),0);
    return [('Personal Asis | MiMo Flash | '+tokens+' tokens | shared budget').slice(0,width)];
  };
  const setup=ui.setupEditorSubmitHandler.bind(ui);
  ui.setupEditorSubmitHandler=()=>{
    setup();const original=ui.defaultEditor.onSubmit;
    ui.defaultEditor.onSubmit=async text=>{
      const q=text.trim();const [command,...rest]=q.split(/\s+/);const arg=rest.join(' ');
      if(q.startsWith('/')) {
        try {
          if(command==='/quit' || command==='/exit') {await ui.shutdown();return;}
          if(command==='/help' || command==='/hotkeys') {
            ui.showStatus('/new 新聊天 · /chats 列表 · /open ID 恢复 · /scope 范围 · /status 状态\n/resume-work 明确恢复工作 · /pause 暂停 · /cancel 取消 · /forget 清除聊天 · /quit 退出\nEnter 提交 · Shift+Enter 换行 · Esc 中断 · Ctrl+D 退出');
            ui.clearEditor();return;
          }
          if(command==='/copy') {await ui.handleCopyCommand();ui.clearEditor();return;}
          if(command==='/new' || command==='/open') {
            if(command==='/open' && !/^[a-f0-9-]{36}$/.test(arg))throw new Error('请输入 /chats 中的会话ID');
            selected=command==='/open'?arg:null;
            await runtime.newSession();ui.clearEditor();return;
          }
          if(command==='/chats') {
            const list=await invoke(config,{action:'list'});
            ui.showStatus(list.chats.map(c=>c.id+' · '+c.mode+' · '+new Date(c.at*1000).toLocaleDateString()).join('\n')||'没有已保存聊天');ui.clearEditor();return;
          }
          if(command==='/scope') {ui.showStatus(scope.join(' / ')+' · '+role);ui.clearEditor();return;}
          if(['/status','/resume-work','/pause','/cancel'].includes(command)) {
            const action={'/status':'status','/resume-work':'resume','/pause':'pause','/cancel':'cancel'}[command];
            const value=await invoke(config,{action,thread});ui.showStatus(value.text);ui.clearEditor();return;
          }
          if(command==='/forget') {
            await invoke(config,{action:'forget',thread});selected=null;await runtime.newSession();ui.clearEditor();return;
          }
          ui.showWarning('可用：/new /chats /open ID /scope /status /resume-work /pause /cancel /forget /quit');return;
        } catch(error){ui.showError(error.message);return;}
      }
      if(q.startsWith('!')) {ui.showWarning('个人助手入口不执行 shell 命令。');return;}
      await original(text);
    };
  };
  for(const method of ['handleBashCommand','handleModelCommand','handleLoginCommand','handleImportCommand',
    'handleExportCommand','handleShareCommand','handleBugCommand','handleCompactCommand','handleReloadCommand',
    'handleCloneCommand','handleResumeSession','handleDebugCommand']) {
    ui[method]=async()=>ui.showWarning('此入口只使用本机个人助手。');
  }
  ui.handleClearCommand=async()=>{selected=null;await runtime.newSession();};
  ui.handleHotkeysCommand=()=>ui.showStatus('Enter 提交 · Shift+Enter 换行 · Esc 中断 · Ctrl+D 退出 · /help 命令');
  ui.handleClipboardPaste=ui.handleRightClickPaste.bind(ui);
  return {runtime,ui,getThread:()=>thread};
}

if(process.argv[1]===fileURLToPath(import.meta.url)) {
  try {
    const config=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
    const {ui}=await createTerminal(config);await ui.run();
  } catch {
    console.error('Personal Asis terminal startup failed; run asis-pi --check.');process.exitCode=1;
  }
}
