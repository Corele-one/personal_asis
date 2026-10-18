// Keep signed note URLs off OS argv. Input/output stay on anonymous pipes.
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const request = JSON.parse(readFileSync(0, 'utf8'));
const { entry, operation, limit, value } = request;
if (!['feed', 'saved', 'search', 'note'].includes(operation)
    || !Number.isInteger(limit) || limit < 1 || limit > 20
    || typeof entry !== 'string' || !entry.endsWith('/dist/src/main.js')) {
  process.exit(2);
}
const args = ['xiaohongshu', operation];
if (operation === 'search' || operation === 'note') {
  if (typeof value !== 'string' || !value || value.length > 4096) process.exit(2);
  if (operation === 'note') {
    const url = new URL(value);
    if (!['https://www.xiaohongshu.com', 'https://xiaohongshu.com'].includes(url.origin)
        || !/^\/(?:(?:explore|discovery\/item|search_result|note)\/[a-f0-9]{24}|user\/profile\/[a-f0-9]{24}\/[a-f0-9]{24})$/.test(url.pathname)
        || !url.searchParams.get('xsec_token')) process.exit(2);
  }
  args.push(value);
}
if (operation !== 'note') args.push('--limit', String(limit));
args.push('--format', 'json', '--trace', 'off', '--window', 'background');
process.argv = [process.execPath, entry, ...args];
await import(pathToFileURL(entry).href);
