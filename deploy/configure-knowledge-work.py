#!/usr/bin/env python3
"""Register only the read-only MCP using Alma's supported configuration API."""
import argparse
import json
from pathlib import Path
import urllib.request

NAME = 'personal_knowledge'
CONFIG = dict(command='/opt/alma-work/current/runtime/node',
    args=['--max-old-space-size=48', '/opt/personal-asis-knowledge/current/deploy/knowledge-mcp/server.mjs'])


def api(path, method='GET', body=None):
    request = urllib.request.Request('http://127.0.0.1:23001'+path, method=method,
        data=None if body is None else json.dumps(body).encode(), headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response) if response.status != 204 else None


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--remove', action='store_true')
    args = parser.parse_args()
    try:
        servers = api('/api/mcp-servers')
        old = next((s for s in servers if s['name'] == NAME), None)
        if args.remove:
            if old:
                api('/api/mcp-servers/'+NAME, 'DELETE')
            print(json.dumps(dict(removed=True, sources_preserved=True)))
        else:
            if old and old['config'] != CONFIG:
                raise ValueError('existing_mcp_config_differs_review_before_update')
            if not old:
                api('/api/mcp-servers', 'POST', dict(name=NAME, config=CONFIG))
            else:
                api('/api/mcp-client/reconnect/'+NAME, 'POST')
            print(json.dumps(dict(registered=True, name=NAME, expected_tools=2,
                other_servers_preserved=len(servers)-(1 if old else 0))))
    except Exception as error:
        raise SystemExit('knowledge_registration_failed:'+type(error).__name__) from None
