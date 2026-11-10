// Actual official MCP client/transport. Never print private source content.
import assert from 'node:assert/strict';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';
import {fileURLToPath} from 'node:url';

const bridge = fileURLToPath(new URL('./server.mjs', import.meta.url));
const client = new Client({name:'w2-acceptance',version:'1.0.0'});
const transport = new StdioClientTransport({command:process.execPath,
  args:['--max-old-space-size=48',bridge],env:process.env,stderr:'ignore'});
try {
  await client.connect(transport);
  const tools = (await client.listTools()).tools;
  const offline = process.argv.includes('--offline');
  assert.equal(tools.length, offline ? 0 : 2);
  async function call(name, args) {
    const raw=await client.callTool({name, arguments:args},undefined,{timeout:180000});
    return {value:JSON.parse(raw.content[0].text),isError:raw.isError};
  }
  if (offline) {
    const result = await call('shared_knowledge',{action:'status'});
    assert(result.isError);
    assert.equal(result.value.error,'knowledge_unavailable_no_retry');
    console.log(JSON.stringify({offline_explicit:true,tool_count:0,automatic_retry:false}));
  } else {
    const status=await call('shared_knowledge',{action:'status'});
    assert(!status.isError);
    const page=await call('shared_knowledge',{action:'list',source:'study',limit:1});
    const ref=page.value.results[0];assert(ref);
    let args={action:'read',origin:ref.origin,collection:ref.collection,record_id:ref.id,
      expected_version:ref.version,expected_hash:ref.content_hash};
    let result, pages=0, chars=0;
    do {
      result=await call('shared_knowledge',args);assert(!result.isError);
      chars+=result.value.body.text.length;pages++;
      args=result.value.next_arguments;
      assert(pages<=40);
    } while(args);
    assert(result.value.read_complete);
    const denied=await call('shared_knowledge',{action:'annotate'});
    assert(denied.isError);
    const wucaiDenied=await call('wucai_read',{operation:'delete-article'});
    assert(wucaiDenied.isError);
    console.log(JSON.stringify({tool_count:tools.length,source_catalog:true,
      complete_versioned_read:true,read_pages:pages,returned_chars:chars,
      write_actions_denied:true,private_source_output:false}));
  }
} finally {
  await client.close();
}
