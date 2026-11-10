// Official MCP SDK transport; the bridge has no source credentials or DB access.
import {Server} from '@modelcontextprotocol/sdk/server/index.js';
import {StdioServerTransport} from '@modelcontextprotocol/sdk/server/stdio.js';
import {ListToolsRequestSchema, CallToolRequestSchema} from '@modelcontextprotocol/sdk/types.js';
import net from 'node:net';

const socketPath = process.env.ASIS_KNOWLEDGE_SOCKET || '/run/personal-asis-knowledge/reader.sock';
export function request(value) {
  return new Promise(resolve => {
    const socket = net.createConnection(socketPath);
    let chunks = [], bytes = 0, done = false;
    const finish = value => {
      if (done) return;
      done = true; socket.destroy(); resolve(value);
    };
    socket.setTimeout(180000, () => finish({error:'knowledge_timeout_unknown_no_retry'}));
    socket.once('error', () => finish({error:'knowledge_unavailable_no_retry'}));
    socket.once('connect', () => socket.write(JSON.stringify(value)+'\n'));
    socket.on('data', chunk => {
      bytes += chunk.length;
      if (bytes > 1024*1024) return finish({error:'knowledge_output_too_large'});
      chunks.push(chunk);
      if (chunk.includes(10)) {
        try { finish(JSON.parse(Buffer.concat(chunks).toString('utf8'))); }
        catch { finish({error:'knowledge_invalid_response'}); }
      }
    });
    socket.once('end', () => finish({error:'knowledge_response_unknown_no_retry'}));
  });
}

const server = new Server({name:'personal-asis-knowledge', version:'1.0.0'}, {capabilities:{tools:{}}});
server.setRequestHandler(ListToolsRequestSchema, async () => {
  const result = await request({method:'tools/list'});
  // Listing while the broker is offline must not prevent Work from starting.
  return {tools: result.tools || []};
});
server.setRequestHandler(CallToolRequestSchema, async ({params}) => {
  const result = await request({method:'tools/call', params:{name:params.name, arguments:params.arguments || {}}});
  const value = result.error ? result : result.result;
  return {isError: Boolean(result.error || value?.error), content:[{type:'text', text:JSON.stringify(value)}]};
});
await server.connect(new StdioServerTransport());
