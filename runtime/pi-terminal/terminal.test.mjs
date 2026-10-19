import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { createTerminal } from './terminal.mjs';

test('native Pi SDK delegates exactly once, displays host result and disables discovery/retry',async()=>{
  const temporary=mkdtempSync(join(tmpdir(),'asis-pi-ui-test-'));
  let calls=0;
  const requests=[];
  const invoke=async(_config,r,progress)=>{
    requests.push(r);
    if(r.action==='new')return {thread:'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',messages:[]};
    if(r.action==='run'){
      calls++;progress({stage:'tool',phase:'start',name:'search_notes'});
      return {text:'合成资料回答 [E1]',status:'completed',usage:{prompt_tokens:100,completion_tokens:20,total_tokens:120}};
    }
    throw new Error('unexpected synthetic request');
  };
  let runtime;
  try {
    const terminal=await createTerminal({temporary,home:temporary,owner_home:temporary,sources:['synthetic'],mode:'auto'},invoke);
    ({runtime}=terminal);
    const session=runtime.session;
    assert.deepEqual(session.getActiveToolNames(),['personal_assistant']);
    assert.equal(session.resourceLoader.getExtensions().extensions.length,0);
    assert.equal(session.resourceLoader.getSkills().skills.length,0);
    assert.equal(session.resourceLoader.getAgentsFiles().agentsFiles.length,0);
    assert.equal(session.settingsManager.getRetrySettings().enabled,false);
    const events=[];session.subscribe(e=>events.push(e.type));
    await session.prompt('cache');
    const last=session.agent.state.messages.at(-1);
    assert.equal(last.content[0].text,'合成资料回答 [E1]');
    assert.equal(last.usage.totalTokens,120);
    assert.equal(calls,1);
    assert(events.includes('tool_execution_start'));
    assert(events.includes('tool_execution_update'));
    assert.equal(requests.find(r=>r.action==='run').query,'cache');
    await assert.rejects(session.executeBash('echo denied'),/shell_disabled/);
    assert(!readdirSync(temporary).some(n=>n.endsWith('.jsonl')));
    await session.prompt('second');assert.equal(calls,2);
    assert.equal(requests.filter(r=>r.action==='run')[1].query,'second');
    terminal.ui.showStatus=()=>{};terminal.ui.showWarning=()=>{};
    terminal.ui.setupEditorSubmitHandler();
    await terminal.ui.defaultEditor.onSubmit('/help');
    await terminal.ui.defaultEditor.onSubmit('/unsupported');
    assert.equal(calls,2,'local commands must never become paid questions');
  } finally {await runtime?.dispose();rmSync(temporary,{recursive:true,force:true});}
});

test('failed or unknown host work produces one visible stop with no automatic retry',async()=>{
  const temporary=mkdtempSync(join(tmpdir(),'asis-pi-ui-test-'));
  let calls=0,runtime;
  try {
    ({runtime}=await createTerminal({temporary,home:temporary,sources:['synthetic'],mode:'auto'},async(_cfg,r)=>{
      if(r.action==='new')return {thread:'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',messages:[]};
      calls++;throw new Error('agent_model_result_unknown_no_retry');
    }));
    await runtime.session.prompt('cache');
    assert.equal(calls,1);
    assert.match(runtime.session.agent.state.messages.at(-1).content[0].text,/不会自动重试/);
  } finally {await runtime?.dispose();rmSync(temporary,{recursive:true,force:true});}
});

test('conversation native UI starts without scope or role and routes commands without paid calls',async()=>{
  const temporary=mkdtempSync(join(tmpdir(),'asis-pi-chat-ui-'));
  const requests=[];
  let runtime;
  try {
    const terminal=await createTerminal({temporary,home:temporary,owner_home:temporary,
      sources:[],mode:'conversation-v1',engine:'conversation'},async(_cfg,r)=>{
      requests.push(r);
      if(r.action==='new')return {thread:'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',messages:[],sources:[],mode:'conversation-v1'};
      if(r.action==='run')return {status:'completed',text:r.query==='第一条'?'已经记住本会话约定':'继续这个话题',usage:{total_tokens:50}};
      return {text:'本机会话状态'};
    });
    ({runtime}=terminal);
    assert.deepEqual(requests[0],{action:'new'});
    await runtime.session.prompt('第一条');await runtime.session.prompt('追问');
    assert.equal(requests.filter(r=>r.action==='run').length,2);
    assert.equal(runtime.session.agent.state.messages.at(-1).usage.totalTokens,50);
    const tool=runtime.session.getAllTools().find(t=>t.name==='personal_assistant');
    assert(tool);
    terminal.ui.showStatus=()=>{};terminal.ui.showWarning=()=>{};
    terminal.ui.setupEditorSubmitHandler();
    await terminal.ui.defaultEditor.onSubmit('/budget');
    await terminal.ui.defaultEditor.onSubmit('/resume');
    assert.equal(requests.at(-2).action,'budget');
    assert.equal(requests.at(-1).action,'resume');
    assert.equal(requests.filter(r=>r.action==='run').length,2);
  } finally {await runtime?.dispose();rmSync(temporary,{recursive:true,force:true});}
});

test('native conversation shows permission preview then accepts a natural reply without request codes',async()=>{
  const temporary=mkdtempSync(join(tmpdir(),'asis-pi-consent-ui-'));
  const requests=[];let runtime;
  try {
    ({runtime}=await createTerminal({temporary,home:temporary,owner_home:temporary,
      sources:[],mode:'conversation-v1',engine:'conversation'},async(_cfg,r)=>{
      if(r.action==='new')return {thread:'cccccccc-cccc-cccc-cccc-cccccccccccc',messages:[]};
      requests.push(r);
      return r.query==='同意' ? {status:'completed',text:'本轮公开来源回答 [E1]',usage:{total_tokens:100}} :
        {status:'waiting_permission',text:'公开查询cache systems；回复同意执行。',usage:{total_tokens:50}};
    }));
    await runtime.session.prompt('搜索公开资料');
    assert.match(runtime.session.agent.state.messages.at(-1).content[0].text,/回复同意/);
    await runtime.session.prompt('同意');
    assert.match(runtime.session.agent.state.messages.at(-1).content[0].text,/公开来源回答/);
    assert.deepEqual(requests.map(r=>r.query),['搜索公开资料','同意']);
    assert.notEqual(requests[0].request_id,requests[1].request_id);
    assert.equal(runtime.session.agent.state.messages.filter(m=>m.role==='assistant').reduce((n,m)=>n+m.usage.totalTokens,0),150);
  } finally {await runtime?.dispose();rmSync(temporary,{recursive:true,force:true});}
});
