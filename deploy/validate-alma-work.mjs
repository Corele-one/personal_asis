// Run on the VPS with the official bundled Node. All tasks/data are synthetic.
// Native REST + WebSocket APIs only; no importing Alma internals or databases.
// Default: current user-selected auto policy. Historical ask-mode checks use
// --policy-ask (and optionally --offline), only against an ask-mode service.
import assert from 'node:assert/strict';
import http from 'node:http';
import {createRequire} from 'node:module';
import {existsSync, writeFileSync, readFileSync, unlinkSync} from 'node:fs';
const require = createRequire('/opt/alma-work/current/lib/server.mjs');
const WebSocket = require('ws');
const base = 'http://127.0.0.1:23001';
async function api(path, method='GET', body) {
  const response = await fetch(base+path, {method, headers:{'content-type':'application/json'},
    body:body===undefined?undefined:JSON.stringify(body), signal:AbortSignal.timeout(20000)});
  if (!response.ok) throw new Error(`native_api_status_${response.status}`);
  return response.status===204?null:response.json();
}
const connect = path => new Promise((resolve,reject) => {
  const ws = new WebSocket('ws://127.0.0.1:23001'+path);
  ws.once('open',()=>resolve(ws)); ws.once('error',reject);
});
const settings = await api('/api/settings');
assert.equal(settings.security.autoApproveToolRequests,false);
assert.equal(settings.memory.enabled,false);
assert.equal(settings.network.retryAttempts,0);
assert.equal((await api('/api/personal')).settings.proactive,false);
assert.equal((await api('/api/heartbeat/config')).enabled,false);
const workspace = (await api('/api/workspaces')).find(w=>w.path==='/srv/alma-work');
assert(workspace);
const threads=[];
const results=[];
async function runCase({name,model,prompt,tools=[],approval,stopOnApproval=false,noTools=false,expectedCommand,useDefaults=false}) {
  const thread=await api('/api/threads','POST',useDefaults?{title:'W1 synthetic: '+name}:
    {title:'W1 synthetic: '+name,model,workspaceId:workspace.id});
  threads.push(thread.id);
  let handoff;
  let approvals=0, deltas=0;
  if (approval || stopOnApproval) {
    handoff=await connect('/ws/handoff/tool-approvals');
    handoff.on('message', async raw=>{
      const event=JSON.parse(raw.toString());
      if(event.type!=='show'||event.request.threadId!==thread.id)return;
      approvals++;
      if(stopOnApproval) socket.send(JSON.stringify({type:'stop_generation',data:{threadId:thread.id}}));
      else await api('/api/handoff/tool-approvals','POST',{
        requestId:event.request.requestId,response:{action:
          expectedCommand && event.request.metadata?.command!==expectedCommand?'deny':approval}});
    });
  }
  const socket=await connect('/ws/threads');
  const start=Date.now();
  try {
    await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{
        socket.send(JSON.stringify({type:'stop_generation',data:{threadId:thread.id}}));
        reject(new Error('generation_unknown_no_retry'));
      },180000);
      socket.on('message',raw=>{
        const event=JSON.parse(raw.toString());
        if(event.type==='message_delta'&&event.data?.threadId===thread.id)deltas++;
        if(event.type==='error') {clearTimeout(timer);reject(new Error('native_generation_error'));}
        if(event.type==='generation_completed'&&event.data?.threadId===thread.id){clearTimeout(timer);resolve();}
        if(stopOnApproval&&event.type==='thread_generating'&&event.data?.id===thread.id&&event.data?.isGenerating===false){clearTimeout(timer);resolve();}
      });
      socket.send(JSON.stringify({type:'generate_response',data:{threadId:thread.id,model,
        userMessage:{role:'user',parts:[{type:'text',text:prompt}]},tools:useDefaults?undefined:tools,noTools,reasoningEffort:'off'}}));
    });
    const messages=await api(`/api/threads/${thread.id}/messages`);
    const serialized=JSON.stringify(messages);
    const result={name,approvals,deltas,elapsed_ms:Date.now()-start,
      persisted_messages:Array.isArray(messages)?messages.length:null,
      completed_tool_parts:messages.flatMap(m=>m.message?.parts??m.parts??[]).filter(p=>p.type?.startsWith('tool-')&&p.state==='output-available').length,
      contains_expected_text:serialized.includes('W1_OK')};
    if(stopOnApproval) {
      const pending=(await api('/api/handoff/tool-approvals')).filter(a=>a.threadId===thread.id);
      result.stale_approvals_after_stop=pending.length;
      for(const request of pending) {
        // A late click on a cancelled request must not execute the command.
        await api('/api/handoff/tool-approvals','POST',{requestId:request.requestId,response:{action:'allow_once'}});
      }
      await new Promise(resolve=>setTimeout(resolve,1500));
    }
    results.push(result);
    return result;
  } finally {socket.close();handoff?.close();}
}
if(process.argv.includes('--natural')) {
  const result=await runCase({name:'natural default workflow',useDefaults:true,
    prompt:'请在当前目录创建 natural-workflow-check.txt，写入 hello，然后读回核对。'});
  assert.equal(readFileSync('/srv/alma-work/natural-workflow-check.txt','utf8').trim(),'hello');
  assert(result.completed_tool_parts>0);
  result.file_verified=true;
  console.log(JSON.stringify({kind:'real_model_natural_language_default_settings',results}));
} else if (process.argv.includes('--live') || process.argv.includes('--live-file') || process.argv.includes('--deepseek-file')) {
  const deepseek=process.argv.includes('--deepseek-file');
  const provider=deepseek?(await api('/api/providers')).find(p=>p.name==='DeepSeek'&&p.enabled):null;
  if(deepseek)assert(provider);
  const model=deepseek?provider.id+':deepseek-v4-flash':settings.chat.defaultModel;
  const file=process.argv.includes('--live-file')||deepseek;
  const path=deepseek?'/srv/alma-work/deepseek-workflow-check.txt':'/srv/alma-work/w1-result.txt';
  const expectedCommand='printf W1_OK > '+path;
  const result=await runCase(file?{name:deepseek?'real DeepSeek bounded file task':'real MiMo bounded file task',model,
    prompt:`这是合成验收，不是本人经历。只调用一次 Bash 执行以下精确命令（不加任何其他命令）：${expectedCommand}。成功后只回复 W1_OK。`,
    tools:['Bash'],approval:'allow_once',expectedCommand}:{name:'real MiMo plain streaming',model,
    prompt:'这是合成验收，不是本人经历。只回复 W1_OK，不调用工具。',noTools:true});
  assert(result.contains_expected_text);
  if(file){assert.equal(readFileSync(path,'utf8'),'W1_OK');result.file_verified=true;}
  console.log(JSON.stringify({kind:'real_model',model:model.split(':').slice(1).join(':'),results}));
} else {
  let operation='deny', calls=0, toolCalls=0, caseToolCalls=0;
  let marker;
  const server=http.createServer(async(req,res)=>{
    const chunks=[];for await(const c of req)chunks.push(c);
    if(req.method!=='POST'){res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify({data:[]}));return;}
    const body=JSON.parse(Buffer.concat(chunks));calls++;
    const tool=body.tools?.some(t=>t.function?.name==='Bash') && caseToolCalls===0;
    if(tool){caseToolCalls++;toolCalls++;}
    if(!body.stream){res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify({
      id:'w1-synthetic',object:'chat.completion',created:1,model:'w1-fixture',
      choices:[{index:0,message:{role:'assistant',content:'W1_OK'},finish_reason:'stop'}],
      usage:{prompt_tokens:1,completion_tokens:1,total_tokens:2}}));return;}
    res.writeHead(200,{'content-type':'text/event-stream'});
    const chunk={id:'w1-synthetic',object:'chat.completion.chunk',created:1,model:'w1-fixture',choices:[{
      index:0,delta:tool?{role:'assistant',tool_calls:[{index:0,id:'w1-tool-'+operation,type:'function',
        function:{name:'Bash',arguments:JSON.stringify({command:`rm -- ${marker}`,description:'Remove disposable W1 synthetic marker'})}}]}:{role:'assistant',content:'W1_OK'},
      finish_reason:tool?'tool_calls':'stop'}]};
    res.end('data: '+JSON.stringify(chunk)+'\n\ndata: [DONE]\n\n');
  });
  await new Promise(resolve=>server.listen(23002,'127.0.0.1',resolve));
  const provider=await api('/api/providers','POST',{name:'W1 disposable fixture',type:'custom',apiKey:'synthetic-not-a-credential',baseURL:'http://127.0.0.1:23002/v1',enabled:true});
  try {
    await api(`/api/providers/${provider.id}/models`,'PUT',{models:['w1-fixture'],availableModels:[{
      id:'w1-fixture',name:'W1 fixture',isManual:true,apiFormat:'openai-chat',
      capabilityOverrides:{functionCalling:true,streaming:true,contextWindow:32768,maxOutputTokens:1024}}]});
    const autoPolicy=!process.argv.includes('--policy-ask')&&!process.argv.includes('--offline');
    const cases=autoPolicy?[{name:'automatic-workspace-bash'}]:[{name:'deny',approval:'deny'},
      {name:'allow',approval:'allow_once'},{name:'cancel',stopOnApproval:true},
      ...(process.argv.includes('--offline')?[{name:'offline'}]:[])];
    for(const test of cases) {
      operation=test.name;marker='/srv/alma-work/.w1-approval-'+operation;
      calls=0;caseToolCalls=0;writeFileSync(marker,'synthetic\n');
      const result=await runCase({...test,model:provider.id+':w1-fixture',prompt:'Synthetic approval validation. Remove only the disposable marker using Bash.' ,tools:['Bash']});
      result.provider_requests=calls;
      result.marker_exists=existsSync(marker);
      if(test.name==='allow'||autoPolicy)assert.equal(result.marker_exists,false);
      else assert.equal(result.marker_exists,true);
      if(test.approval||test.stopOnApproval)assert.equal(result.approvals,1);
      if(existsSync(marker))unlinkSync(marker);
    }
    assert.equal(toolCalls,cases.length);
    console.log(JSON.stringify({kind:'native_synthetic',results,threads}));
  } finally {
    await api('/api/providers/'+provider.id,'DELETE');
    server.close();
    if(existsSync(marker))unlinkSync(marker);
  }
}
