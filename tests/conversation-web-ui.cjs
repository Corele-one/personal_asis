// Execute the actual client against a synthetic DOM/API, without network access.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {randomUUID} = require('node:crypto');
const root = path.join(__dirname, '../src/personal_asis/web');
class Element {
  constructor() { this.children = []; this.handlers = {}; this.value = ''; this.textContent = ''; }
  addEventListener(kind, callback) { this.handlers[kind] = callback; }
  append(child) { this.children.push(child); }
  replaceChildren(...children) { this.children = children; }
  querySelector() { return this.children.find(child => child.value === this.value) || null; }
  focus() {}
  requestSubmit() { this.handlers.submit({preventDefault() {}}); }
}
const ids = [...fs.readFileSync(path.join(root, 'conversation.html'), 'utf8').matchAll(/id="([^"]+)"/g)];
const elements = new Map(ids.map(match => [match[1], new Element()]));
const requests = [], sessions = [], turns = new Map(), storage = new Map();
const document = {getElementById: id => elements.get(id) || null, createElement: () => new Element()};
const budget = {daily_tokens: 0, daily_limit: 100000, monthly_tokens: 0, monthly_limit: 1000000};
async function fetch(url, options) {
  const body = options.body ? JSON.parse(options.body) : null;
  requests.push({url, body});
  let value;
  if (url === '/api/sessions') value = {sessions};
  else if (url === '/api/session/new') {
    const id = randomUUID(); sessions.push({id, at: 1}); turns.set(id, []); value = {session_id: id};
  } else if (url.startsWith('/api/session?id=')) value = {turns: turns.get(decodeURIComponent(url.split('=')[1]))};
  else if (url === '/api/budget') value = budget;
  else if (url === '/api/send') {
    turns.get(body.session_id).push({turn_id: body.turn_id, question: body.message, status: 'completed',
      result: {answer: 'Synthetic answer', evidence: [], citations: []}});
    value = {status: 'completed'};
  } else throw Error('Unexpected API request: ' + url);
  return {ok: true, json: async () => value};
}
const context = {document, fetch, crypto: {randomUUID}, CSS: {escape: s => s},
  sessionStorage: {getItem: k => storage.get(k), setItem: (k, v) => storage.set(k, v), removeItem: k => storage.delete(k)},
  EventSource: class { addEventListener() {} close() {} }, confirm: () => false};
const flush = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  vm.runInNewContext(fs.readFileSync(path.join(root, 'conversation.js'), 'utf8'), context);
  await flush();
  assert.equal(elements.get('progress').textContent, '新会话已就绪');
  assert.equal(sessions.length, 1);
  for (const id of ['new-chat', 'forget', 'approve', 'deny', 'resume', 'cancel'])
    assert.equal(typeof elements.get(id).handlers.click, 'function', id);
  assert.equal(typeof elements.get('sessions').handlers.change, 'function');
  elements.get('input').value = 'Synthetic question';
  elements.get('composer').requestSubmit();
  await flush();
  assert.equal(requests.filter(r => r.url === '/api/send').length, 1);
  assert(elements.get('messages').children.some(child => child.textContent === 'Synthetic answer'));
  assert.equal(elements.get('send').disabled, false);
  elements.get('new-chat').handlers.click();
  await flush();
  assert.equal(sessions.length, 2);
  assert.equal(elements.get('messages').children.length, 0);
  process.stdout.write('Client initialization, send/render and new-session smoke checks passed\n');
})().catch(error => { process.stderr.write(error.stack + '\n'); process.exitCode = 1; });
