"""Versioned SDK adapters: background execution has its own conversation namespace.

No files in AstrBot are patched. Delivery, provider/config and tool execution keep
using the original event; only the execution Context's conversation manager changes.
"""
import copy
from hashlib import sha256
import inspect
from types import MethodType


def namespace(origin, key):
    return 'asis_background:OtherMessage:' + sha256((origin + '\0' + key).encode()).hexdigest()


class Conversations:
    def __init__(self, manager, origin, key):
        self.manager = manager
        self.origin = origin
        self.scope = namespace(origin, key)
        self.cids = set()

    def check_origin(self, origin):
        if origin not in (self.origin, self.scope):
            raise ValueError('background_origin_mismatch')

    async def get_curr_conversation_id(self, origin):
        self.check_origin(origin)
        cid = await self.manager.get_curr_conversation_id(self.scope)
        if cid:
            self.cids.add(cid)
        return cid

    async def new_conversation(self, origin, *args, **kwargs):
        self.check_origin(origin)
        cid = await self.manager.new_conversation(self.scope, *args, **kwargs)
        self.cids.add(cid)
        return cid

    async def get_conversation(self, origin, cid, *args, **kwargs):
        self.check_origin(origin)
        if cid not in self.cids:
            raise ValueError('background_conversation_mismatch')
        return await self.manager.get_conversation(self.scope, cid, *args, **kwargs)

    async def update_conversation(self, origin, conversation_id=None, **kwargs):
        self.check_origin(origin)
        cid = conversation_id or await self.get_curr_conversation_id(origin)
        if cid not in self.cids:
            raise ValueError('background_conversation_mismatch')
        return await self.manager.update_conversation(self.scope, cid, **kwargs)


def execution_context(context, origin, key):
    clone = copy.copy(context)  # retains the installed SDK Context type
    clone.conversation_manager = Conversations(context.conversation_manager, origin, key)
    clone._asis_root_context = getattr(context, '_asis_root_context', context)
    return clone


class BackgroundIsolation:
    def __init__(self, context, binding):
        self.context, self.binding = context, binding
        self.installed = False

    def owner_origin(self, origin):
        return (bool(self.binding.get('owner_platform')) and bool(self.binding.get('owner_id'))
                and origin == '{}:FriendMessage:{}'.format(
                    self.binding['owner_platform'], self.binding['owner_id']))

    def install(self):
        from astrbot.core.astr_agent_tool_exec import FunctionToolExecutor
        manager = self.context.cron_manager
        cron = manager._woke_main_agent
        background = FunctionToolExecutor._wake_main_agent_for_background_result
        # Refuse unknown SDK contracts instead of silently running without isolation.
        if not ({'message', 'session_str', 'extras', 'delivery_session_str'} <= set(inspect.signature(cron).parameters)
                and {'run_context', 'task_id', 'tool_name', 'result_text'} <= set(inspect.signature(background).parameters)):
            raise RuntimeError('unsupported_background_sdk_contract')
        if self.installed:
            return
        self.manager, self.executor = manager, FunctionToolExecutor
        self.previous_cron = manager.__dict__.get('_woke_main_agent')
        self.previous_background = FunctionToolExecutor.__dict__['_wake_main_agent_for_background_result']

        async def isolated_cron(manager_self, *, message, session_str, extras, delivery_session_str=''):
            if not self.owner_origin(str(session_str)):
                return await cron(message=message, session_str=session_str, extras=extras,
                                  delivery_session_str=delivery_session_str)
            meta = (extras or {}).get('cron_job', {})
            key = 'cron:' + str(meta.get('id', '')) + ':' + str(meta.get('run_started_at', ''))
            clone = copy.copy(manager_self)
            clone.ctx = execution_context(manager_self.ctx, str(session_str), key)
            return await cron.__func__(clone, message=message, session_str=session_str,
                                       extras=extras, delivery_session_str=delivery_session_str)

        async def isolated_background(cls, run_context, **kwargs):
            ctx = run_context.context.context
            origin = run_context.context.event.unified_msg_origin
            if (getattr(ctx, '_asis_root_context', ctx) is not self.context or not self.owner_origin(origin)):
                return await background(run_context, **kwargs)
            clone = copy.copy(run_context)
            clone.context = copy.copy(run_context.context)
            clone.context.context = execution_context(ctx, origin, 'tool:' + kwargs['task_id'])
            return await background(clone, **kwargs)

        self.cron_wrapper = MethodType(isolated_cron, manager)
        self.background_wrapper = classmethod(isolated_background)
        manager._woke_main_agent = self.cron_wrapper
        FunctionToolExecutor._wake_main_agent_for_background_result = self.background_wrapper
        self.installed = True

    def uninstall(self):
        if not self.installed:
            return
        if self.manager.__dict__.get('_woke_main_agent') is self.cron_wrapper:
            if self.previous_cron is None:
                del self.manager._woke_main_agent
            else:
                self.manager._woke_main_agent = self.previous_cron
        if self.executor.__dict__['_wake_main_agent_for_background_result'] is self.background_wrapper:
            self.executor._wake_main_agent_for_background_result = self.previous_background
        self.installed = False
