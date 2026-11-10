// Native Alma plain generation with memory resident/offline; no platform sends.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync,writeFileSync,existsSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
const require=createRequire('/opt/alma-work/current/lib/server.mjs');
const WebSocket=require('ws');
const offline=process.argv.includes('--memory-offline');
const receipt='/home/mac/.local/share/personal-asis-memory-acceptance/work-'+(offline?'offline':'resident')+'.json';
if(existsSync(receipt)){console.log(readFileSync(receipt,'utf8'));process.exit(0);}
writeFileSync(receipt,JSON.stringify({state:'sent_or_unknown'}),{mode:0o600});
async function api(path,method='GET',body) {
  const response=await fetch('http://127.0.0.1:23001'+path,{method,
    headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),
    signal:AbortSignal.timeout(15000)});
  if(!response.ok)throw new Error('native_api_failed');return response.json();
}
let state;
try{state=execFileSync('systemctl',['is-active','personal-asis-memory'],{encoding:'utf8'}).trim();}
catch(error){state=String(error.stdout).trim();}
assert.equal(state,offline?'inactive':'active');
const settings=await api('/api/settings');
const thread=await api('/api/threads','POST',{title:'M1 synthetic: memory '+(offline?'offline':'resident')+' plain Work'});
const ws=new WebSocket('ws://127.0.0.1:23001/ws/threads');
const start=Date.now();
try {
  await new Promise((resolve,reject)=>{ws.once('open',resolve);ws.once('error',reject);});
  await new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{ws.send(JSON.stringify({type:'stop_generation',data:{threadId:thread.id}}));reject(new Error('generation_unknown_no_retry'));},120000);
    ws.on('message',raw=>{
      const event=JSON.parse(raw.toString());
      if(event.type==='error'){clearTimeout(timer);reject(new Error('native_generation_error'));}
      if(event.type==='generation_completed'&&event.data?.threadId===thread.id){clearTimeout(timer);resolve();}
    });
    ws.send(JSON.stringify({type:'generate_response',data:{threadId:thread.id,noTools:true,reasoningEffort:'off',
      userMessage:{role:'user',parts:[{type:'text',text:'合成验收，不是本人经历。不调用工具，只回复 M1_WORK_OK。'}]}}}));
  });
  const messages=await api(`/api/threads/${thread.id}/messages`);
  assert(JSON.stringify(messages).includes('M1_WORK_OK'));
  const result={state:'passed',memory_state:state,actual_configured_model:settings.chat.defaultModel.split(':').slice(1).join(':'),
    elapsed_ms:Date.now()-start,tools:0,synthetic_only:true,feishu_messages:0,automatic_retry:false};
  writeFileSync(receipt,JSON.stringify(result));console.log(JSON.stringify(result));
} finally {ws.close();}
