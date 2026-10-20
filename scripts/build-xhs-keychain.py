#!/usr/bin/env python3
"""Build the pinned upstream MCP with keychain storage and bounded read/write surface."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

EXPECTED = {
    'cookies/cookies.go': '878afec64d840c8340c5f9586f85989e7401846f83f948f62c50a3a9a2746d8c',
    'mcp_server.go': 'a1a416219f39bbd4c9f8441b74da51675361b1b50b34ea8a304de56539bcb629',
    'routes.go': 'fbf6b99fab03f05dd7a317f0a27f3a8d8a8670519401c801a6f85fef0cb7be92',
    'browser/browser_download.go': '250ab35bc6fc6dfc2a83e6f4292a80d5ae1345cbd9df6c57b1a0376f7c7a85bd',
}


def patch(root, allow_writes=False):
    for name, expected in EXPECTED.items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest() != expected:
            raise ValueError('pinned_upstream_source_mismatch:' + name)
    p = root/'cookies/cookies.go'
    s = p.read_text().replace('func NewLoadCookie(path string) Cookier {\n',
        'func NewLoadCookie(path string) Cookier {\n'
        '\tif os.Getenv("ASIS_XHS_KEYCHAIN") == "1" { return &keychainCookie{} }\n', 1)
    p.write_text(s)
    shutil.copyfile(Path(__file__).resolve().parents[1]/'src/personal_asis/xhs_keychain.go',
                    root/'cookies/asis_keychain.go')
    p = root/'mcp_server.go'
    s = p.read_text()
    allowed = {'check_login_status', 'list_feeds', 'search_feeds', 'get_feed_detail', 'get_my_profile'}
    if allow_writes:
        allowed |= {'like_feed', 'favorite_feed', 'post_comment_to_feed'}
    names = set(re.findall(r'Name:\s*"([a-z_]+)"', s))
    denied = sorted(names - allowed)
    assert allowed <= names and denied
    s = s.replace('registerTools(server, appServer)', 'registerTools(server, appServer)\n'
        '\tserver.RemoveTools(' + ', '.join(json.dumps(x) for x in denied) + ')', 1)
    p.write_text(s)
    p = root/'routes.go'
    s = p.read_text()
    first, last = s.index('\t// API 路由组'), s.index('\n\treturn router')
    s = s[:first] + '\t// Personal Asis exposes authenticated MCP and health only; no REST mutations.\n' + s[last:]
    p.write_text(s)
    p = root/'browser/browser_download.go'
    s = p.read_text().replace('func browserCacheDir() (string, error) {\n',
        'func browserCacheDir() (string, error) {\n'
        '\tif base := os.Getenv("ASIS_XHS_BROWSER_CACHE"); base != "" {\n'
        '\t\treturn filepath.Join(base, browserVersion), nil\n\t}\n', 1)
    p.write_text(s)
    return {'upstream': 'v2.5.5', 'upstream_files_verified': True,
            'mcp_allowed_tools': sorted(allowed), 'removed_tools': denied,
            'rest_mutation_routes_removed': True, 'persistent_session': 'os_keychain'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--go', type=Path, required=True)
    parser.add_argument('--allow-writes', action='store_true', help='Only like/favorite/comment; native UI confirmation required by source_write')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = patch(args.source, args.allow_writes)
    subprocess.run([str(args.go), 'build', '-mod=readonly', '-trimpath',
        '-ldflags', '-X main.version=v2.5.5-asis-keychain-' + ('bounded' if args.allow_writes else 'readonly'), '-o', str(args.output), '.'],
        cwd=args.source, env={**os.environ, 'GOTOOLCHAIN': 'local', 'CGO_ENABLED': '0'}, check=True)
    report['binary_sha256'] = hashlib.sha256(args.output.read_bytes()).hexdigest()
    print(json.dumps(report), flush=True)
