"""Reproducible real-Pi / fake-provider trial, with synthetic evidence only."""

import json
import os
from pathlib import Path
import tempfile

from .model_budget import ModelBudget
from .runtime_adapter import run_pi
from .work import WorkStore, fingerprint


TOOL_SCHEMA = {'type': 'object', 'properties': {'value': {'type': 'string', 'maxLength': 2000}},
               'required': ['value'], 'additionalProperties': False}
TOOLS = [{'name': name, 'description': description, 'parameters': TOOL_SCHEMA}
         for name, description in (
             ('lookup', 'Search synthetic authorized evidence for a topic.'),
             ('artifact', 'Save a synthetic summary to one confined output file.'))]


class SyntheticHost:
    """Test-only policy gateway; never load Study/Life, keys or source policies.

    This exercises host/runtime boundaries. It does not replace PA1's real
    source policy/revalidation or make these fixtures into a production grant.
    """
    def __init__(self, store, claim, ledger, directory, replies, after_model=None):
        self.store, self.claim, self.ledger = store, claim, ledger
        self.directory, self.replies = Path(directory), iter(replies)
        self.after_model = after_model
        self.revoked = False
        self.used = False
        self.model_inputs, self.tool_calls = [], []
        self.approved = {tool['name']: fingerprint(tool) for tool in TOOLS}
        self.turn = 0
        self.documents = [
            {'id': 'E1', 'source': 'synthetic', 'roles': ['research'], 'providers': ['synthetic'],
             'title': 'Synthetic cache', 'path': 'cache.md', 'body': 'Cache invalidation removes stale entries.',
             'coverage': 'full_text'},
            {'id': 'E2', 'source': 'synthetic', 'roles': ['research'], 'providers': ['synthetic'],
             'title': 'Synthetic media', 'path': 'media.md', 'body': 'Synthetic summary only.',
             'coverage': 'summary_only'},
            {'id': 'PRIVATE_TITLE', 'source': 'synthetic', 'roles': ['life'], 'providers': [],
             'title': 'PRIVATE_TITLE', 'path': 'PRIVATE_PATH.md', 'body': 'PRIVATE_BODY', 'coverage': 'full_text'},
            {'id': 'UNGRANTED', 'source': 'ungranted', 'roles': ['research'], 'providers': ['synthetic'],
             'title': 'UNGRANTED_TITLE', 'path': 'UNGRANTED_PATH.md', 'body': 'UNGRANTED_BODY', 'coverage': 'full_text'},
        ]

    def check(self):
        c = self.claim
        self.store._check(c['id'], 'synthetic-node', c['epoch'])
        if self.revoked:
            raise ValueError('synthetic_permission_revoked')

    def start(self, key, kind, args):
        self.check()
        c = self.claim
        self.store.begin_execution(c['id'], 'synthetic-node', c['epoch'], key, kind, args)

    def settle(self, key, state):
        c = self.claim
        self.store.finish_execution(c['id'], 'synthetic-node', c['epoch'], key, state)

    def tool(self, event):
        self.check()
        name, args = event['name'], event['args']
        tool = next((t for t in TOOLS if t['name'] == name), None)
        if tool is None or self.approved.get(name) != fingerprint(tool):
            raise ValueError('tool_not_registered_or_version_changed')
        if not isinstance(args, dict) or set(args) != {'value'} or not isinstance(args['value'], str) or len(args['value']) > 2000:
            raise ValueError('invalid_tool_arguments')
        if name == 'artifact':
            # The provider cannot choose a filename, traverse parents or overwrite.
            # Only this fixed output name is supported; no scripts or shell exist.
            if not self.used:
                raise ValueError('artifact_requires_evidence')
            if args['value'] != 'Synthetic evidence [E1]; E2 is summary_only.':
                raise ValueError('synthetic_artifact_content_rejected')
        key = 'tool:' + event['callId']
        self.start(key, 'tool', event)
        try:
            if name == 'lookup':
                scope = self.store.view(self.claim['delegation'])['scope']['sources']
                records = [{k: d[k] for k in ('id', 'title', 'path', 'body', 'coverage')}
                           for d in self.documents if d['source'] in scope and self.claim['role'] in d['roles']
                           and 'synthetic' in d['providers']]
                self.used = bool(records)
                result = {'evidence': records, 'coverage': 'partial_synthetic_fixture'}
            else:
                directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    descriptor = os.open('result.txt', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                         0o600, dir_fd=directory_fd)
                    with os.fdopen(descriptor, 'w') as output:
                        output.write(args['value'])
                finally:
                    os.close(directory_fd)
                result = {'saved': True, 'artifact': 'result.txt'}
            self.check()
            self.settle(key, 'done')
        except BaseException:
            # Unknown includes a crash after creation, before committing its receipt.
            try:
                self.settle(key, 'unknown')
            except ValueError:
                pass
            raise
        self.tool_calls.append(name)
        return result

    def __call__(self, kind, event):
        self.check()
        if kind == 'tool':
            return self.tool(event)
        if kind == 'done':
            messages = event['messages']
            tail = messages[-1]
            if tail['role'] != 'assistant' or tail['stopReason'] != 'stop':
                raise ValueError('runtime_result_incomplete')
            answer = ''.join(c.get('text', '') for c in tail['content'])
            if answer != 'Synthetic evidence [E1]; E2 is summary_only.' or not self.used:
                raise ValueError('synthetic_final_evidence_invalid')
            self.store.progress(self.claim['id'], 'synthetic-node', self.claim['epoch'],
                                {'phase': 'complete', 'evidence': ['E1', 'E2'], 'answer': answer}, completed=True)
            return {'answer': answer, 'events': event['events'], 'model_turns': self.turn,
                    'tools': list(self.tool_calls), 'coverage': 'partial_synthetic_fixture'}
        if kind != 'model' or self.turn >= 6 or event['turn'] != self.turn+1:
            raise ValueError('invalid_model_turn')
        self.turn += 1
        key = f'model:{self.turn}'
        request_id = self.claim['id'] + ':' + key
        # Budget shared across roles; no runtime-owned counter is authoritative.
        fp = fingerprint(event['messages'])
        self.start(key, 'model', {'fingerprint': fp})
        reserved = False
        try:
            self.ledger.reserve(request_id, fp, 100)
            reserved = True
            self.model_inputs.append(event['messages'])
            reply = next(self.replies)
            if self.after_model:
                self.after_model(self)
            self.check()
            # Fake usage only, never reported as real MiMo Tokens.
            self.ledger.finish(request_id, 'succeeded', tokens=20)
            reserved = False
            self.settle(key, 'done')
            return reply
        except BaseException:
            if reserved:
                self.ledger.finish(request_id, 'unknown')
            try:
                self.settle(key, 'unknown' if reserved else 'rejected')
            except ValueError:
                pass
            raise


def tool_reply(name, call_id, value):
    return {'content': [{'type': 'toolCall', 'id': call_id, 'name': name, 'arguments': {'value': value}}],
            'stopReason': 'toolUse'}


def validate():
    """Complete optional integration trial, in a disposable private directory."""
    with tempfile.TemporaryDirectory(prefix='asis-runtime-validation-') as root:
        directory = Path(root)
        with WorkStore(directory/'work.sqlite3') as store:
            ledger = ModelBudget(directory/'budget.sqlite3', 'synthetic-node', daily=1000, monthly=1000)
            try:
                did = store.create('synthetic-trial', 'synthetic-node', 'Synthetic cache study', ['synthetic'])
                parent = store.enqueue(did, 'supervisor')
                rid = store.enqueue(did, 'research', 'research', parent)
                # Explicit trial settings, not defaults for a production scheduler.
                parent_claim = store.claim('synthetic-node', capacity=2, foreground_reserve=1)
                assert parent_claim['id'] == parent
                claim = store.claim('synthetic-node', capacity=2, foreground_reserve=1)
                assert claim['id'] == rid
                store.progress(rid, 'synthetic-node', claim['epoch'],
                               {'phase': 'plan', 'plan': 'Read synthetic cache evidence, save a cited summary.'})
                answer = 'Synthetic evidence [E1]; E2 is summary_only.'
                host = SyntheticHost(store, claim, ledger, directory, [
                    tool_reply('lookup', 'lookup-1', 'cache'),
                    tool_reply('artifact', 'artifact-1', answer),
                    {'content': [{'type': 'text', 'text': answer}], 'stopReason': 'stop'}])
                result = run_pi('Study synthetic cache evidence; report coverage.', TOOLS, claim['session'], host)
                store.progress(parent, 'synthetic-node', parent_claim['epoch'],
                               {'phase': 'complete', 'child': rid, 'evidence': ['E1', 'E2']}, completed=True)
                serialized = json.dumps(host.model_inputs)
                isolated = all(s not in serialized for s in ('PRIVATE_', 'UNGRANTED_'))
                artifact = (directory/'result.txt').read_text() == answer
                checks = {'private_metadata_and_body_filtered': isolated,
                          'confined_artifact_created': artifact,
                          'supervisor_and_specialist_completed': all(r['state']=='completed' for r in store.view(did)['runs']),
                          'tool_loop_observed': 'tool_execution_end' in result['events'],
                          'shared_fake_budget_settled': ledger.status()['daily_tokens'] == 60}
                return {'passed': all(checks.values()), 'synthetic_only': True,
                        'runtime': '@earendil-works/pi-agent-core', 'version': '1.2.0',
                        'model': 'fake_host_provider', 'real_model_calls': 0,
                        'model_turns': result['model_turns'], 'tool_calls': result['tools'],
                        'checks': checks,
                        'limitations': ['No real MiMo tool-call compatibility claim',
                                         'No production scheduler or account/source integration',
                                         'No general script/browser isolation claim']}
            finally:
                ledger.close()
