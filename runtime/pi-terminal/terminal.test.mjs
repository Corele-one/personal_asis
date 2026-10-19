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
