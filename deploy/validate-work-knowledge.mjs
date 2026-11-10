// Native Alma REST/WebSocket acceptance; synthetic prompts, no platform sends.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire('/opt/alma-work/current/lib/server.mjs');
const WebSocket=require('ws');
async function api(path, method='GET', body) {
  const r=await fetch('http://127.0.0.1:23001'+path,{method,
    headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),
    signal:AbortSignal.timeout(15000)});
  if(!r.ok)throw new Error('native_api_status_'+r.status);
  return r.json();
}
const offline=process.argv.includes('--offline');
const verifyExisting=process.argv.includes('--verify-existing');
const settings=await api('/api/settings');
assert.equal(settings.memory.enabled,false);
assert.equal(settings.network.retryAttempts,0);
const title='W2 synthetic: '+(offline?'memory-independent offline plain answer':'native knowledge tool');
const thread=verifyExisting?(await api('/api/threads')).find(t=>t.title===title):
  await api('/api/threads','POST',{title});
assert(thread);
const ws=verifyExisting?null:new WebSocket('ws://127.0.0.1:23001/ws/threads');
const started=Date.now();
if(ws)await new Promise((resolve,reject)=>{ws.once('open',resolve);ws.once('error',reject);});
try {
  if(ws)await new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{
      ws.send(JSON.stringify({type:'stop_generation',data:{threadId:thread.id}}));
      reject(new Error('native_generation_unknown_no_retry'));
    },180000);
    ws.on('message',raw=>{
      const event=JSON.parse(raw.toString());
      if(event.type==='error'){clearTimeout(timer);reject(new Error('native_generation_error'));}
      if(event.type==='generation_completed'&&event.data?.threadId===thread.id){clearTimeout(timer);resolve();}
    });
    ws.send(JSON.stringify({type:'generate_response',data:{threadId:thread.id,
      noTools:offline,reasoningEffort:'off',userMessage:{role:'user',parts:[{type:'text',text:offline?
        '合成验收，不是本人经历。不要调用工具，只回复 W2_OFFLINE_OK。':
        '合成验收，不是本人经历。请使用已连接的个人资料查询工具检查共享资料库状态（只读状态，不读取正文），然后用一句中文说明这是最近同步副本，不是Mac实时文件。不要执行终端命令。'}]}}}));
  });
  const messages=await api(`/api/threads/${thread.id}/messages`);
  const parts=messages.flatMap(m=>m.message?.parts??m.parts??[]);
  const tools=parts.filter(p=>p.type?.startsWith('tool-'));
  if(offline)assert(JSON.stringify(messages).includes('W2_OFFLINE_OK'));
  else {
    // Alma may expose MCP tools through its native PTC almaTool wrapper.
    const direct=tools.filter(p=>p.type.includes('shared_knowledge')&&p.state==='output-available');
    const wrapped=tools.filter(p=>p.type==='tool-run_script'&&p.state==='output-available'
      &&p.input?.code?.includes('__shared_knowledge')&&JSON.stringify(p.output).includes('readonly_replica'));
    assert(direct.length+wrapped.length>0);
    assert(!tools.some(p=>p.type==='tool-Bash'));
    const data=tools.filter(p=>p.type.includes('shared_knowledge')).map(p=>p.input);
    assert(data.some(a=>a?.action==='status')||wrapped.some(p=>p.input.code.includes('status')));
  }
  console.log(JSON.stringify({kind:offline?'offline_plain_real_model':'natural_tool_selection_real_model',
    completed:true,actual_configured_model:settings.chat.defaultModel.split(':').slice(1).join(':'),
    completed_tools:tools.filter(p=>p.state==='output-available').map(p=>p.type),
    elapsed_ms:verifyExisting?null:Date.now()-started,verified_existing_completed_run:verifyExisting,
    generation_steps:parts.filter(p=>p.type==='step-start').length,
    synthetic_prompt:true,private_source_body_sent:false,
    feishu_messages:0,automatic_retry:false}));
} finally {ws?.close();}
