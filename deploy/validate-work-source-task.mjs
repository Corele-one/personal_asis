// Native end-to-end read task. Private messages stay on VPS; durable no-replay receipt.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync,writeFileSync,existsSync,mkdirSync} from 'node:fs';
const require=createRequire('/opt/alma-work/current/lib/server.mjs');
const WebSocket=require('ws');
const mode=process.argv.includes('--targeted')?'targeted':process.argv.includes('--missing')?'missing':'study';
const revision=process.argv.includes('--revised')?'-revised':'';
const home='/home/mac/.local/share/asis-w2-followup';
mkdirSync(home,{recursive:true,mode:0o700});
const receipt=home+'/'+mode+revision+'.json';
if(existsSync(receipt)){console.log(readFileSync(receipt,'utf8'));process.exit(0);}
const save=value=>writeFileSync(receipt,JSON.stringify(value),{mode:0o600});
async function api(path,method='GET',body){
  const r=await fetch('http://127.0.0.1:23001'+path,{method,
    headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),
    signal:AbortSignal.timeout(15000)});
  if(!r.ok)throw Error('native_api_failed');return r.json();
}
const settings=await api('/api/settings');
assert.equal(settings.memory.enabled,false);
assert.equal(settings.network.retryAttempts,0);
save({state:'reserved_no_automatic_replay',mode});
const thread=await api('/api/threads','POST',{title:'W2 followup acceptance: '+mode});
save({state:'sent_or_unknown',mode,threadId:thread.id});
const prompt=mode==='targeted'?
'这是资料工具验收，不保存偏好。请先查询共享资料状态，然后列出最多1条Study目录，选择这份已有笔记，读完全部正文后概括三个要点并附出处。说明副本同步时间，是否代表Mac实时文件，能否据此判断本人已经学完。只查询现有资料，不调用终端或创建文件。':mode==='study'?
'这是资料工具验收，不是本人经历，不保存偏好。请查看共享资料副本状态，再列出已有Study资料，选择一份课程笔记（若有多分段优先选多分段），实际读完全部正文后，用中文概括三个有内容依据的要点，附相对出处。说明最近同步时间、它是不是Mac实时资料，是否能据此判断本人已经学完。只用个人资料工具，不调用终端、不创建文件、不连接Mac。':
'这是资料工具验收，不是本人经历。请在现有Study资料中查找 ASIS_NONEXISTENT_7f92c0_NOT_A_COURSE，说明查找结果和覆盖边界，以及是否能据此断言Mac原库没有它。只用个人资料工具，不调用终端、不创建文件、不连接Mac。';
const ws=new WebSocket('ws://127.0.0.1:23001/ws/threads');
const started=Date.now();
try{
  await new Promise((resolve,reject)=>{ws.once('open',resolve);ws.once('error',reject);});
  await new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{ws.send(JSON.stringify({type:'stop_generation',data:{threadId:thread.id}}));reject(Error('generation_unknown_no_retry'));},240000);
    ws.on('message',raw=>{
      const e=JSON.parse(raw.toString());
      if(e.type==='error'&&(!e.data?.threadId||e.data.threadId===thread.id)){clearTimeout(timer);reject(Error('generation_error_no_retry'));}
      if(e.type==='generation_completed'&&e.data?.threadId===thread.id){clearTimeout(timer);resolve();}
    });
    ws.send(JSON.stringify({type:'generate_response',data:{threadId:thread.id,reasoningEffort:'off',
      userMessage:{role:'user',parts:[{type:'text',text:prompt}]}}}));
  });
  const messages=await api('/api/threads/'+thread.id+'/messages');
  writeFileSync(home+'/'+mode+revision+'-messages.json',JSON.stringify(messages),{mode:0o600});
  const parts=messages.flatMap(m=>m.message?.parts??m.parts??[]);
  const tools=parts.filter(p=>p.type?.startsWith('tool-')&&p.state==='output-available');

  const final=messages.filter(m=>(m.message?.role??m.role)==='assistant').at(-1);
  const answer=(final?.message?.parts??final?.parts??[]).filter(p=>p.type==='text').map(p=>p.text).join('\n');
  function completeRead(value){
    if(typeof value==='string'){
      try{return completeRead(JSON.parse(value));}catch{}
      // PTC stdout can label multiple JSON objects; parse balanced frames.
      for(let begin=0;begin<value.length;begin++){
        if(value[begin]!=='{' && value[begin]!=='[')continue;
        let depth=0,quoted=false,escape=false;
        for(let end=begin;end<value.length;end++){
          const c=value[end];
          if(quoted){if(escape)escape=false;else if(c==='\\')escape=true;else if(c==='"')quoted=false;}
          else if(c==='"')quoted=true;
          else if(c==='{'||c==='[')depth++;
          else if(c==='}'||c===']'){
            depth--;
            if(depth===0){
              try{if(completeRead(JSON.parse(value.slice(begin,end+1))))return true;}catch{}
              begin=end;break;
            }
          }
        }
      }
      return false;
    }
    if(Array.isArray(value))return value.some(completeRead);
    if(!value||typeof value!=='object')return false;
    if(value.read_complete===true && typeof value.body?.text==='string')return true;
    return Object.values(value).some(completeRead);
  }
  const complete=tools.some(p=>completeRead(p.output));
  const result={state:'completed_needs_review',mode,threadId:thread.id,
    configured_model:settings.chat.defaultModel.split(':').slice(1).join(':'),
    elapsed_ms:Date.now()-started,generation_steps:parts.filter(p=>p.type==='step-start').length,
    tools:tools.map(p=>p.type),terminal_used:tools.some(p=>/Bash|terminal/i.test(p.type)),
    complete_read_observed:complete,answer_present:answer.length>0,
    automatic_retry:false,private_messages_printed:false};
  save(result);console.log(JSON.stringify(result));
}catch(e){save({state:'failed_or_unknown_no_retry',mode,threadId:thread.id,error:e.message});throw e;}
finally{ws.close();}
