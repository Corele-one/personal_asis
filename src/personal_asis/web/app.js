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
function show(section) { if(section!=='console')closeReader();for(const id of ['login','setup','console']) $(id).hidden=id!==section;$('logout').hidden=section!=='console'; }
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
