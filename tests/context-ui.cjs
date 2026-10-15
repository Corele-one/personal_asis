// Run the actual shipped UI with WebCrypto and synthetic encrypted Mac responses.
const {readFileSync}=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const {webcrypto,randomUUID}=require('node:crypto');
const path=require('node:path');
const subtle=webcrypto.subtle,encode=x=>Buffer.from(x).toString('base64');
class Element{
  constructor(){this.value='';this.textContent='';this.children=[];this.listeners={};this.open=false;}
  addEventListener(event,handler){this.listeners[event]=handler;}
  replaceChildren(...children){this.children=children;}
  append(...children){this.children.push(...children);}
  prepend(...children){this.children.unshift(...children);}
  close(){this.open=false;}
}
const elements=new Map();
const html=readFileSync(path.join(__dirname,'../src/personal_asis/web/index.html'),'utf8');
for(const match of html.matchAll(/id="([^"]+)"/g))elements.set(match[1],new Element());
const get=id=>{assert(elements.has(id),'unknown UI element '+id);return elements.get(id);};
const responses=new Map(),requests=[];
let goal={kind:'domain_context',domain:'research',revision:0,goal:'',constraints:'',source_ids:[],model_allowed:false,configured:false,deleted:false,needs_review:false,model_called:false};
async function encrypt(data,job){
  const key=await subtle.generateKey({name:'AES-GCM',length:256},true,['encrypt']);
  const nonce=webcrypto.getRandomValues(new Uint8Array(12));
  const context=new TextEncoder().encode((job.target_id?['agent',job.request_id,job.target_id,job.client_nonce,'pwa']:['analysis',job.request_id,job.client_nonce,'pwa']).join('\n'));
  const ciphertext=await subtle.encrypt({name:'AES-GCM',iv:nonce,additionalData:context},key,new TextEncoder().encode(JSON.stringify(data)));
  const publicKey=await subtle.importKey('spki',Buffer.from(job.public_key,'base64'),{name:'RSA-OAEP',hash:'SHA-256'},false,['encrypt']);
  const wrapped=await subtle.encrypt({name:'RSA-OAEP'},publicKey,await subtle.exportKey('raw',key));
  return {wrapped_key:encode(wrapped),nonce:encode(nonce),ciphertext:encode(ciphertext)};
}
async function fetch(url,options){
  const job=options.body?JSON.parse(options.body):null;let value;
  if(url==='/auth/status')value={authenticated:false,initialized:true,auth_method:'password_only'};
  else if(url==='/api/agent/request'){
    requests.push(job);let reply;
    if(job.action==='context'){
      const command=job.context;
      if(command.op!=='show')assert.equal(command.expected_revision,goal.revision);
      if(command.op==='set')goal={...goal,...command,revision:goal.revision+1,configured:true,model_allowed:command.allow_model};
      if(command.op==='forget')goal={...goal,revision:goal.revision+1,goal:null,constraints:null,source_ids:[],configured:false,deleted:true};
      reply=goal;
    }else reply={target_id:job.target_id,state:'completed',delegation_state:'active',committed_actions:0,usage:null,unresolved_executions:0};
    responses.set(job.request_id,await encrypt(reply,job));value={status:'waiting'};
  }else if(url==='/api/analysis/request'){requests.push(job);responses.set(job.request_id,await encrypt({answer:'SYNTHETIC_ANALYSIS',uncertainty:'',evidence:[],usage:{total_tokens:0},sensitivity:'normal'},job));value={status:'waiting'};}
  else if(url==='/api/analysis/result')value={status:'ready',envelope:responses.get(job.request_id)};
  else if(url==='/api/agent/result')value={status:'ready',envelope:responses.get(job.request_id)};
  else throw new Error('Unexpected endpoint '+url);
  return {ok:true,status:200,json:async()=>value};
}
const sandbox={crypto:{subtle,getRandomValues:x=>webcrypto.getRandomValues(x),randomUUID},fetch,TextEncoder,TextDecoder,URLSearchParams,URL,Uint8Array,Map,Date,JSON,console,
  btoa:x=>Buffer.from(x,'binary').toString('base64'),atob:x=>Buffer.from(x,'base64').toString('binary'),
  location:{hash:''},history:{replaceState(){}},navigator:{},setInterval(){},setTimeout,
  window:{addEventListener(){}},document:{getElementById:get,createElement:()=>new Element(),visibilityState:'visible',addEventListener(){}}};
vm.createContext(sandbox);
vm.runInContext(readFileSync(path.join(__dirname,'../src/personal_asis/web/app.js'),'utf8'),sandbox);
(async()=>{
  await new Promise(setImmediate);
  get('context-domain').value='research';
  await vm.runInContext("contextCommand('show')",sandbox);
  assert.match(get('context-status').textContent,/尚未保存/);
  get('context-goal').value='SYNTHETIC_UI_GOAL';get('context-source').value='study';get('context-allow').value='mimo';
  await vm.runInContext("contextCommand('set')",sandbox);
  assert.equal(goal.revision,1);assert.equal(get('context-goal').value,'SYNTHETIC_UI_GOAL');
  get('context-goal').value='SYNTHETIC_UI_REVISION';
  await vm.runInContext("contextCommand('set')",sandbox);assert.equal(goal.revision,2);
  await vm.runInContext("contextCommand('forget')",sandbox);assert.equal(get('context-goal').value,'');assert.equal(goal.deleted,true);
  get('agent-mode').value='research';get('agent-continuity').value='history';get('agent-source').value='study';get('agent-query').value='SYNTHETIC_UI_QUERY';
  await vm.runInContext("agentCommand('run')",sandbox);
  assert.equal(requests.at(-1).use_context,true,JSON.stringify({request:requests.at(-1),status:get('agent-status').textContent,notice:get('notice').textContent}));assert.equal(requests.at(-1).role_history,true);
  assert.equal(requests.at(-1).action,'run');
  get('analysis-query').value='SYNTHETIC_ANALYSIS_QUERY';get('analysis-source').value='study';
  await get('analysis-form').listeners.submit({preventDefault(){}});await new Promise(setImmediate);
  assert.equal(requests.at(-1).query,'SYNTHETIC_ANALYSIS_QUERY');assert.equal(requests.at(-1).mode,undefined);
  assert.equal(get('analysis-status').textContent.includes('分析完成'),true);
  console.log(JSON.stringify({analysis_form_without_agent_fields:true,encrypted_goal_read_save_replace_delete:true,correct_revisions:[0,1,2],continuity_options_sent:true,model_calls:0}));
})().catch(error=>{console.error(error);process.exitCode=1;});
