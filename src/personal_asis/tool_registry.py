"""Versioned, frozen host tool definitions. No runtime registration by the model."""
import copy
from dataclasses import dataclass
import re
from .work import fingerprint


def validate(value, schema):
    kind = schema['type']
    if kind == 'object':
        if not isinstance(value, dict) or set(value)-set(schema['properties']) or not set(schema.get('required', [])) <= set(value):
            raise ValueError('chat_invalid_tool_arguments')
        for key, item in value.items():
            validate(item, schema['properties'][key])
    elif kind == 'string':
        if not isinstance(value, str) or not schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', 4096):
            raise ValueError('chat_invalid_tool_arguments')
    elif kind == 'integer':
        if type(value) is not int or not schema.get('minimum', 0) <= value <= schema.get('maximum', 100):
            raise ValueError('chat_invalid_tool_arguments')
    elif kind == 'array':
        if not isinstance(value, list) or not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', 20):
            raise ValueError('chat_invalid_tool_arguments')
        for item in value:
            validate(item, schema['items'])
    else:
        raise ValueError('chat_unsupported_tool_schema')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError('chat_invalid_tool_arguments')


@dataclass(frozen=True)
class Tool:
    name: str
    version: int
    description: str
    parameters: dict
    handler: str
    permission: str = 'existing_local_grants'

    def manifest(self):
        return {'name': self.name, 'version': self.version, 'description': self.description,
                'parameters': copy.deepcopy(self.parameters), 'permission': self.permission}


class ToolRegistry:
    def __init__(self, version):
        self.version, self._tools, self._frozen = version, {}, False

    def register(self, tool):
        if self._frozen or not re.fullmatch('[a-z][a-z0-9_]{0,48}', tool.name) or tool.name in self._tools:
            raise ValueError('chat_registry_frozen_or_duplicate_tool')
        self._tools[tool.name] = copy.deepcopy(tool)
        return self

    def freeze(self):
        self._frozen = True
        return self

    def manifest(self):
        return {'version': self.version, 'tools': [t.manifest() for t in self._tools.values()]}

    def snapshot(self):
        return {'version': self.version, 'fingerprint': fingerprint(self.manifest())}

    def verify(self, snapshot):
        if snapshot != self.snapshot():
            raise ValueError('chat_tool_protocol_changed_no_retry')

    def definitions(self):
        return [{k: t.manifest()[k] for k in ('name', 'description', 'parameters')} for t in self._tools.values()]

    def get(self, name, arguments):
        tool = self._tools.get(name) if isinstance(name, str) else None
        if tool is None:
            raise ValueError('chat_tool_not_allowed')
        validate(arguments, tool.parameters)
        return copy.deepcopy(tool)


def obj(properties, required):
    return {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}


def text(maximum):
    return {'type': 'string', 'minLength': 1, 'maxLength': maximum}


def registry_v1():
    registry = ToolRegistry('conversation-tools-v1')
    query = {'query': text(512)}
    registry.register(Tool('search_notes', 1, '获准个人笔记相关片段；部分覆盖，可改词补查。',
        obj({**query, 'sources': {'type':'array','items':text(80),'minItems':1,'maxItems':10}}, ['query']), 'local'))
    registry.register(Tool('search_reading', 1, '获准WUCAI/Folo/小红书本机缓存；不访问账户或扩大模型许可。',
        obj({**query, 'connector': {'type':'string','enum':['wucai','folo','xiaohongshu']}}, ['query','connector']), 'reading'))
    registry.register(Tool('search_web', 1, '提议公开检索词，待本人确认后发现公开来源；摘要不是证据。',
        obj({'query':text(128), 'backend':{'type':'string','enum':['deepseek','exa']},
             'max_results':{'type':'integer','minimum':1,'maximum':3},
             'recency_days':{'type':'integer','minimum':1,'maximum':365}}, ['query']), 'search', 'exact_public_query'))
    registry.register(Tool('fetch_web', 1, '仅阅读本轮search_web发现的公开URL，正文片段经本机校验后才可引用。',
        obj({'url':text(2000),'max_chars':{'type':'integer','minimum':200,'maximum':800}}, ['url']), 'fetch', 'discovered_public_url'))
    registry.register(Tool('consult_specialist', 1, '提议一次研究/职业/生活专业工作，待本人确认；无后台授权。',
        obj({'role':{'type':'string','enum':['research','career','life']}, 'question':text(512)}, ['role','question']),
        'specialist', 'explicit_single_work'))
    return registry.freeze()
