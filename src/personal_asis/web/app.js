'use strict';
const $ = id => document.getElementById(id);
const initialParams = new URLSearchParams(location.hash.slice(1));
let csrf = '', selected = initialParams.get('task') || '', authenticated = false;
let setupToken = initialParams.get('setup') || '';
if (setupToken) history.replaceState(null, '', '/');
const message = text => { $('notice').textContent = text; };
const errors = {invalid_credentials:'密码或动态验证码无效。已使用的验证码不能再次登录。',login_rate_limited:'登录尝试过多，请 15 分钟后再试。',invalid_setup_token:'设置链接无效或已过期，请通过服务器管理入口重新生成。',password_length_14_to_256:'密码需为 14 到 256 个字符。',unauthorized:'登录已过期，请重新登录。',origin_rejected:'请求来源校验失败。',temporarily_unavailable:'服务暂时不可用，请稍后重试。',invalid_query:'请输入 1 到 512 个字符的搜索词。'};
async function api(path, data) {
  const options = {credentials:'same-origin',cache:'no-store',headers:{}};
  if (data !== undefined) { options.method='POST';options.headers['Content-Type']='application/json';options.headers['X-CSRF-Token']=csrf;options.body=JSON.stringify(data); }
  let res;try{res=await fetch(path,options);}catch{throw new Error('网络暂不可用。页面显示的是上次获取的状态。');}
  let body;try{body=await res.json();}catch{throw new Error(res.status===429?'请求过于频繁，请稍后再试。':'服务暂时不可用，请稍后再试。');}
  if (!res.ok) { if(res.status===401&&authenticated){authenticated=false;show('login');}throw new Error(errors[body.error]||'请求未完成，请重试。'); }
  return body;
}
function show(section) { if(section!=='console'){closeReader();clearAnalysis();clearAgent();}for(const id of ['login','setup','console']) $(id).hidden=id!==section;$('logout').hidden=section!=='console'; }
function element(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
let readerSession=null;
const encode64=raw=>btoa(String.fromCharCode(...new Uint8Array(raw)));
const decode64=text=>Uint8Array.from(atob(text),c=>c.charCodeAt(0));
function closeReader(){readerSession=null;$('reader-text').textContent='';$('reader-location').textContent='';$('reader-status').textContent='';if($('reader').open)$('reader').close();}
function locatorText(loc){return [loc.page&&`第 ${loc.page} 页`,loc.slide&&`第 ${loc.slide} 张幻灯片`,loc.paragraph&&`第 ${loc.paragraph} 段`,loc.sheet&&`工作表 ${loc.sheet}`,loc.cell&&`单元格 ${loc.cell}`,loc.line&&`第 ${loc.line} 行`].filter(Boolean).join(' · ');}
async function readChunk(session,cursor){
  $('reader-text').textContent='';$('reader-location').textContent='';$('reader-status').textContent='等待设备加密返回文本…';$('reader-previous').disabled=true;$('reader-next').disabled=true;
  try{
    const keys=await crypto.subtle.generateKey({name:'RSA-OAEP',modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},false,['encrypt','decrypt']);
    if(readerSession!==session)return;
    const data={task_id:session.task,document_id:session.hit.document_id,content_hash:session.hit.content_hash,mode:session.mode,cursor,client_nonce:encode64(crypto.getRandomValues(new Uint8Array(16))),public_key:encode64(await crypto.subtle.exportKey('spki',keys.publicKey))};
    const request=await api('/api/reader/request',data);const deadline=Date.now()+75000;
    while(readerSession===session&&Date.now()<deadline){
      const result=await api('/api/reader/result',{request_id:request.request_id});if(readerSession!==session)return;
      if(result.status==='waiting'){await new Promise(resolve=>setTimeout(resolve,1500));continue;}
      if(result.status!=='ready')throw new Error(({denied:'本机权限不允许读取此文本。',stale:'文件版本已改变，请重新搜索。',missing:'文件暂不可用，请检查本机。',failed:'设备未能完成加密读取。'})[result.status]||'文本暂不可用。');
      const wrapped=await crypto.subtle.decrypt({name:'RSA-OAEP'},keys.privateKey,decode64(result.envelope.wrapped_key));
      const key=await crypto.subtle.importKey('raw',wrapped,'AES-GCM',false,['decrypt']);new Uint8Array(wrapped).fill(0);
      const context=new TextEncoder().encode([data.document_id,data.content_hash,data.mode,data.cursor,data.client_nonce].join('\n'));
      const plain=await crypto.subtle.decrypt({name:'AES-GCM',iv:decode64(result.envelope.nonce),additionalData:context},key,decode64(result.envelope.ciphertext));
      const value=JSON.parse(new TextDecoder().decode(plain));new Uint8Array(plain).fill(0);if(readerSession!==session)return;
      $('reader-text').textContent=value.text;$('reader-location').textContent=`${value.format.toUpperCase()} · ${locatorText(value.locator)}`;
      $('reader-status').textContent=session.mode==='excerpt'?'与搜索词相关的最小摘录':`正文文本 · ${cursor+1}–${cursor+Array.from(value.text).length} / ${value.total_characters} 字符`;
      session.next=value.next_cursor;$('reader-previous').disabled=session.history.length<2;$('reader-next').disabled=value.next_cursor===null;return;
    }
    if(readerSession===session)throw new Error('设备尚未返回文本，请确认设备在线后重试。');
  }catch(error){if(readerSession===session)$('reader-status').textContent=error.name==='OperationError'?'文本完整性校验失败，请重新打开。':error.message;}
}
function openReader(hit,mode){closeReader();const session={task:selected,hit,mode,history:[0],next:null};readerSession=session;$('reader-title').textContent=`${mode==='excerpt'?'查看摘录':'查看正文'} · ${hit.title}`;$('reader').showModal();readChunk(session,0);}
$('reader-close').addEventListener('click',closeReader);
$('reader').addEventListener('cancel',e=>{e.preventDefault();closeReader();});
$('reader-next').addEventListener('click',()=>{const s=readerSession;if(s&&s.next!==null){s.history.push(s.next);readChunk(s,s.next);}});
$('reader-previous').addEventListener('click',()=>{const s=readerSession;if(s&&s.history.length>1){s.history.pop();readChunk(s,s.history[s.history.length-1]);}});
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden')closeReader();});
window.addEventListener('pagehide',closeReader);
async function state(){
  const data=await api('/api/state');$('nodes').replaceChildren(...data.nodes.map(n=>element('span',`${n.node_id} · ${n.online?'在线':'离线，任务等待恢复'}`,`node ${n.online?'online':''}`)));
  $('tasks').replaceChildren(...data.tasks.map(t=>{const b=element('button',t.query,`task ${t.task_id===selected?'selected':''}`);b.append(element('small',`${t.state==='completed'?'已完成':'等待补全'} · ${t.channel==='feishu'?'飞书':'控制台'} · ${new Date(t.created*1000).toLocaleString()}`));b.addEventListener('click',async()=>{selected=t.task_id;try{await result();await state();}catch(e){message(e.message);}});return b;}));
  if(!data.tasks.length)$('tasks').append(element('p','还没有搜索。输入关键词开始。','hint'));
}
async function result(){
  if(!selected)return;const data=await api(`/api/tasks/${encodeURIComponent(selected)}`);const box=$('results');box.replaceChildren();
  box.append(element('p',data.partial?`部分结果，等待：${data.waiting_nodes.join('、')}`:'搜索完成','status'));
  box.append(element('p',data.nodes.map(n=>`${n.node_id}：${n.state==='completed'?'已搜索':n.state==='waiting_for_source'?'来源暂不可用':n.online?'处理／排队中':'离线等待'}`).join('；'),'hint'));
  (data.coverage||[]).forEach(s=>box.append(element('p',`文本覆盖不完整：${s.node_id} / ${s.source_id} 有 ${s.skipped_documents} 个文件未能索引。扫描件、加密、损坏和超限文件请在本机查看具体原因。`,'status')));
  if(!data.results.length)box.append(element('p','目前没有获准远程显示的命中。来源权限保持由本机配置控制。','hint'));
  data.results.forEach(group=>{const card=element('article',undefined,'card');card.append(element('h3',group.replicas[0].title));group.replicas.forEach(hit=>{card.append(element('p',`${hit.node_id} / ${hit.source_id} · ${hit.path_hint}`));card.append(element('p',`文档 ${hit.document_id} · 版本 ${hit.content_hash.slice(0,12)}`,'hint'));if(hit.reader_allowed){for(const [mode,label] of [['excerpt','查看摘录'],['text','查看正文']]){const button=element('button',label);button.addEventListener('click',()=>openReader(hit,mode));card.append(button);}}});if(group.replicas.length>1)card.append(element('p',`相同内容版本，共 ${group.replicas.length} 个副本。`,'hint'));box.append(card);});
}
async function entered(data){csrf=data.csrf;authenticated=true;setupToken='';$('otp-secret').textContent='';$('new-password').value='';$('confirm-password').value='';$('password').value='';$('code').value='';$('setup-code').value='';message('');show('console');await state();await result();}
$('login-form').addEventListener('submit',async e=>{e.preventDefault();try{await entered(await api('/auth/login',{password:$('password').value,code:$('code').value}));}catch(error){message(error.message);}});
$('setup-form').addEventListener('submit',async e=>{e.preventDefault();if($('new-password').value!==$('confirm-password').value){message('两次输入的密码不同。');return;}try{await entered(await api('/auth/setup/finish',{setup_token:setupToken,password:$('new-password').value,code:$('setup-code').value}));}catch(error){message(error.message);}});
let requestId='', lastQuery='';
$('search-form').addEventListener('submit',async e=>{e.preventDefault();const query=$('query').value.trim();if(!requestId||query!==lastQuery){requestId=crypto.randomUUID();lastQuery=query;}try{const task=await api('/api/search',{query,request_id:requestId});selected=task.task_id;requestId='';message('搜索已接收。离线设备恢复后会自动补全。');await state();await result();}catch(error){message(error.message);}});
$('refresh').addEventListener('click',async()=>{try{await state();await result();}catch(e){message(e.message);}});
$('logout').addEventListener('click',async()=>{try{await api('/auth/logout',{});authenticated=false;selected='';csrf='';$('tasks').replaceChildren();$('results').replaceChildren();$('audit').replaceChildren();$('nodes').replaceChildren();show('login');message('已退出。');}catch(e){message(e.message);}});
$('audit-button').addEventListener('click',async()=>{try{const data=await api('/api/audit');$('audit').replaceChildren(...data.events.map(e=>element('div',`${new Date(e.at*1000).toLocaleString()} · ${e.kind}${e.node_id?' · '+e.node_id:''}`,'audit-row')));}catch(e){message(e.message);}});
function configureAuth(method){const useOtp=method==='password_totp';$('login-otp-label').hidden=!useOtp;$('setup-otp-label').hidden=!useOtp;$('otp-secret').hidden=!useOtp;$('code').required=useOtp;$('setup-code').required=useOtp;if(!useOtp)$('setup-instructions').textContent='设置一个仅用于此控制台的密码。使用至少 14 个字符的密码或短语，之后可直接用此密码登录。';}
async function start(){try{const data=await api('/auth/status');configureAuth(data.auth_method);if(data.authenticated){await entered(data);}else if(!data.initialized&&setupToken){const setup=await api('/auth/setup/start',{setup_token:setupToken});$('otp-secret').textContent=setup.secret||'';show('setup');}else{show('login');if(!data.initialized)message('尚未设置登录，请使用服务器生成的一次性设置链接。');}}catch(e){message(e.message);}}
setInterval(async()=>{if(authenticated&&document.visibilityState==='visible'){try{await state();await result();}catch(e){message(e.message);}}},5000);
if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{});
start();

let analysisSession=null;
function clearAnalysis(){analysisSession=null;$('analysis-result').replaceChildren();$('analysis-status').textContent='';}
function renderAnalysis(value,box=$('analysis-result')){
  box.replaceChildren();
  if(value.error){
    const code=value.error;
    let reason='本轮未能生成通过校验的回答；系统保留计费与防重状态。';
    if(code.startsWith('model_output_'))reason='模型回答未通过引用或格式校验，本轮结果未展示，实际用量已计入共享预算。';
    else if(code.includes('unknown')||code.includes('not_retryable'))reason='原请求已执行或结果未知，保留计费和防重状态。';
    else if(code.includes('budget_exhausted'))reason='已达到设定的模型预算，本机资料搜索仍可使用。';
    else if(code.startsWith('context_')||code.startsWith('analysis_permission'))reason='资料版本或权限发生变化，已停止展示本轮结果。';
    else if(code.startsWith('research_'))reason='未取得足够的可用公开证据，请补充公开原始链接。';
    box.append(element('p',reason+' 不会自动重复模型调用。','status'));return;
  }
  box.append(element('pre',value.answer));box.append(element('p','不确定性：'+value.uncertainty,'hint'));
  const report=value.report;
  if(report){
    for(const [key,label] of [['existing_knowledge','已有资料'],['external_findings','公开证据'],['knowledge_gaps','知识缺口'],['disagreements','分歧与限制']]){box.append(element('h3',label),element('pre',report[key]));}
    report.directions.forEach((d,i)=>{box.append(element('h3',`方向假设 ${i+1}：${d.hypothesis}`));for(const [key,label] of [['connection','资料关联'],['gap','能力缺口'],['opportunity','机会'],['risk','风险'],['next_step','下一步验证']])box.append(element('p',`${label}：${d[key]}`));});
  }
  for(const e of value.evidence){
    const card=element('article',undefined,'card');card.append(element('h3',`[${e.id}] ${e.title}`));
    if(e.kind==='external'){
      const link=element('a',e.url);const url=new URL(e.url);if(url.protocol==='https:'){link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';card.append(link);}
      card.append(element('p',`类型：${e.source_class} · 页面日期（未核实）：${e.published_at||'未知'} · 获取：${e.retrieved_at}`,'hint'));
    }else{card.append(element('p',`${e.source_id} / ${e.path_hint} · 第${e.line_start}行 · 版本${e.content_hash.slice(0,12)}`,'hint'));}
    card.append(element('pre',e.excerpt));box.append(card);
  }
  if(value.research_strategy){for(const gap of value.research_strategy.gaps)box.append(element('p',gap,'status'));}
  box.append(element('p',`本次 ${value.usage.total_tokens} Token · ${value.cached?'复用已验证结果':'已结算'} · ${value.sensitivity==='private'?'含私密资料':'普通资料'}；未创建任务或日历。`,'hint'));
}
async function pollAnalysis(session){
  const deadline=Date.now()+14*60*1000;
  while(analysisSession===session&&Date.now()<deadline){
    let result;try{result=await api('/api/analysis/result',{request_id:session.data.request_id});}catch(error){if(analysisSession!==session)return;$('analysis-status').textContent=error.message+' 正在等待原请求；不会重新调用模型。';await new Promise(r=>setTimeout(r,3000));continue;}
    if(analysisSession!==session)return;
    $('analysis-status').textContent=`${session.data.request_id} · ${result.status==='running'?'Mac 正在处理':result.status==='waiting'?'等待 Mac 在线':'已返回'} · ${result.plan}`;
    if(result.status==='waiting'||result.status==='running'){await new Promise(r=>setTimeout(r,2000));continue;}
    if(result.status!=='ready'){throw new Error('本轮结果已过期或权限改变；不会自动再次付费执行。');}
    const wrapped=await crypto.subtle.decrypt({name:'RSA-OAEP'},session.keys.privateKey,decode64(result.envelope.wrapped_key));
    const key=await crypto.subtle.importKey('raw',wrapped,'AES-GCM',false,['decrypt']);new Uint8Array(wrapped).fill(0);
    const context=new TextEncoder().encode(['analysis',session.data.request_id,session.data.client_nonce,'pwa'].join('\n'));
    const plain=await crypto.subtle.decrypt({name:'AES-GCM',iv:decode64(result.envelope.nonce),additionalData:context},key,decode64(result.envelope.ciphertext));
    const value=JSON.parse(new TextDecoder().decode(plain));new Uint8Array(plain).fill(0);if(analysisSession!==session)return;
    renderAnalysis(value);$('analysis-status').textContent=session.data.request_id+' · '+(value.error?'受限结束':'分析完成');return;
  }
  if(analysisSession===session)$('analysis-status').textContent='等待已超时；本页不会自动新建模型请求。';
}
$('analysis-form').addEventListener('submit',async e=>{
  e.preventDefault();
  const query=$('analysis-query').value.trim(),publicQuery=$('research-query').value.trim(),urls=$('research-urls').value.split('\n').map(s=>s.trim()).filter(Boolean),source=$('analysis-source').value;
  if(urls.length>3||(!publicQuery&&urls.length)){message('公开研究需填写公开检索词，链接最多三条。');return;}
  const request={query,source_ids:source?[source]:null,research:publicQuery?{public_query:publicQuery,urls}:null};
  if(action==='run'&&$('agent-mode').value)request.mode=$('agent-mode').value;
  const identity=JSON.stringify(request);
  try{
    if(!analysisSession||analysisSession.identity!==identity){
      clearAnalysis();const session={identity};analysisSession=session;
      session.keys=await crypto.subtle.generateKey({name:'RSA-OAEP',modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},false,['encrypt','decrypt']);
      if(analysisSession!==session)return;
      session.data={...request,request_id:crypto.randomUUID(),client_nonce:encode64(crypto.getRandomValues(new Uint8Array(16))),public_key:encode64(await crypto.subtle.exportKey('spki',session.keys.publicKey))};
    }
    const session=analysisSession;if(!session.data)return;
    await api('/api/analysis/request',session.data);
    if(analysisSession!==session)return;
    message('分析已接收。Mac 将检索证据，在预算内完成；此页显示进度。');
    if(!session.polling){session.polling=true;try{await pollAnalysis(session);}finally{session.polling=false;}}
  }catch(error){message(error.message);}
});
$('analysis-clear').addEventListener('click',clearAnalysis);
window.addEventListener('pagehide',clearAnalysis);


let agentPage={commands:new Map()};
function clearAgent(){agentPage={commands:new Map()};$('agent-target').value='';$('agent-result').replaceChildren();$('agent-status').textContent='';}
function renderAgent(value,page){
  if(agentPage!==page)return;
  if(value.error){
    const codes={agent_request_not_found:'Mac 没有找到此工作编号。',agent_channel_command_conflict:'原指令的内容不一致，已拒绝执行。',agent_channel_request_expired:'本轮执行期限已到，后续步骤已停止。',inactive_or_stale_work_claim:'运行已被暂停或停止，旧进程不能继续提交。',cancelled_delegation_cannot_resume:'已取消的工作不能恢复。'};
    $('agent-status').textContent=(codes[value.error]||'本轮受限或结果未知，未自动重试。请查看原编号状态。')+' 共享计费与防重记录保留。';return;
  }
  const labels={completed:'已完成',running:'执行中',queued:'等待执行',waiting_node:'等待恢复或核对',paused:'已暂停',cancelled:'已取消',stopped:'本轮已停止'};
  $('agent-status').textContent=`${value.target_id} · ${labels[value.state]||value.state}${value.delegation_state==='cancelled'?'（工作已取消）':value.delegation_state==='paused'&&value.state!=='paused'?'（工作已暂停）':''} · 已提交 ${value.committed_actions} 个步骤`+(value.usage?` · ${value.usage.total_tokens} Token`:'')+(value.unresolved_executions?' · 有结果未知的动作，需本机核对；不会自动重试':'');
  if(value.role_plan){const names={research:'知识研究',career:'申请与职业',life:'生活复盘'};$('agent-status').textContent+=' · 总管分工：'+value.role_plan.roles.map(r=>names[r]).join('、');}
  if(value.result)renderAnalysis(value.result,$('agent-result'));
  else $('agent-result').replaceChildren();
}
async function agentCommand(action){
  const page=agentPage;
  let target=$('agent-target').value.trim();
  if(!target&&action==='run'){target=crypto.randomUUID();$('agent-target').value=target;}
  if(!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(target)){message('请先开始工作或填写有效的原工作编号。');return;}
  const request={target_id:target,action,query:action==='run'?$('agent-query').value.trim():null,source_ids:action==='run'?$('agent-source').value.split(','):null};
  if(action==='run'&&$('agent-mode').value)request.mode=$('agent-mode').value;
  const identity=JSON.stringify(request);
  let session=page.commands.get(identity);
  try{
    if(!session){
      session={};page.commands.set(identity,session);
      session.keys=await crypto.subtle.generateKey({name:'RSA-OAEP',modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},false,['encrypt','decrypt']);
      if(agentPage!==page)return;
      session.data={...request,request_id:crypto.randomUUID(),client_nonce:encode64(crypto.getRandomValues(new Uint8Array(16))),public_key:encode64(await crypto.subtle.exportKey('spki',session.keys.publicKey))};
    }
    if(!session.data||session.polling)return;
    session.polling=true;
    await api('/api/agent/request',session.data);
    $('agent-status').textContent=`${target} · 指令已接收，等待 Mac 核实并执行。`;
    const deadline=Date.now()+14*60*1000;
    while(agentPage===page&&Date.now()<deadline){
      let reply;
      try{reply=await api('/api/agent/result',{request_id:session.data.request_id});}
      catch(error){if(agentPage!==page)return;$('agent-status').textContent=error.message+' 保留原指令，不新建模型请求。';await new Promise(r=>setTimeout(r,3000));continue;}
      if(agentPage!==page)return;
      if(reply.status==='waiting'||reply.status==='running'){$('agent-status').textContent=target+' · '+(reply.plan||'等待 Mac 执行');await new Promise(r=>setTimeout(r,2000));continue;}
      if(reply.status!=='ready')throw new Error('中转已过期或权限改变。请用原工作编号查看状态；不会自动再次付费。');
      const wrapped=await crypto.subtle.decrypt({name:'RSA-OAEP'},session.keys.privateKey,decode64(reply.envelope.wrapped_key));
      const key=await crypto.subtle.importKey('raw',wrapped,'AES-GCM',false,['decrypt']);new Uint8Array(wrapped).fill(0);
      const context=new TextEncoder().encode(['agent',session.data.request_id,target,session.data.client_nonce,'pwa'].join('\n'));
      const plain=await crypto.subtle.decrypt({name:'AES-GCM',iv:decode64(reply.envelope.nonce),additionalData:context},key,decode64(reply.envelope.ciphertext));
      const value=JSON.parse(new TextDecoder().decode(plain));new Uint8Array(plain).fill(0);
      renderAgent(value,page);
      // Each deliberate status/control click gets a new receipt. Network retries above retain this one.
      page.commands.delete(identity);return;
    }
    if(agentPage===page)$('agent-status').textContent='等待已超时。请用原编号查看状态或明确恢复；不会自动新建模型请求。';
  }catch(error){message(error.name==='OperationError'?'结果完整性校验失败，请用原编号查看状态。':error.message);}
  finally{if(session)session.polling=false;}
}
$('agent-form').addEventListener('submit',e=>{e.preventDefault();agentCommand('run');});
for(const [id,action] of [['agent-status-button','status'],['agent-pause','pause'],['agent-resume','resume'],['agent-cancel','cancel']])$(id).addEventListener('click',()=>agentCommand(action));
$('agent-clear').addEventListener('click',clearAgent);
window.addEventListener('pagehide',clearAgent);
