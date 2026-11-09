"""Native AstrBot Provider, with single-shot child transports and no Agent loop."""
import asyncio
import copy
from pathlib import Path

import httpx
from google import genai
from google.genai import types

from astrbot.api.provider import Provider
from astrbot.core.provider.entities import LLMResponse
from astrbot.core.provider.register import register_provider_adapter
from astrbot.core.provider.sources.gemini_source import ProviderGoogleGenAI
from astrbot.core.provider.sources.openai_source import ProviderOpenAIOfficial
from .llm_router import Router, State, Failure, classify_error, MODELS, fingerprint

_context = None
_runtime = None


def bind(context):
    global _context
    _context = context


class SingleGoogle(ProviderGoogleGenAI):
    def _init_client(self):
        cfg = self.provider_config
        options = dict(timeout=self.timeout, trust_env=not bool(cfg.get('proxy')))
        if cfg.get('proxy'):
            options['proxy'] = cfg['proxy']
        self._http_client = httpx.AsyncClient(**options)
        http = types.HttpOptions(base_url=self.api_base, timeout=self.timeout*1000,
            httpx_async_client=self._http_client, retry_options=types.HttpRetryOptions(attempts=1))
        self.client = genai.Client(api_key=self.chosen_api_key, http_options=http)

    async def _handle_api_error(self, error, keys):
        raise classify_error(error) from None

    async def _query(self, payloads, tools, *, request_max_retries=None):
        # Do not call the stock _query: it can remove tools/system instructions
        # and repeat a generation inside its compatibility/recitation loops.
        system = next((m['content'] for m in payloads['messages'] if m['role']=='system'), None)
        config = await self._prepare_query_config(payloads, tools,
            payloads.get('tool_choice','auto'), system, ['TEXT'], .7)
        if self.get_model().startswith(('gemini-3-', 'gemini-3.')):
            config.thinking_config = types.ThinkingConfig(
                thinking_level=types.ThinkingLevel(self.provider_config['gm_thinking_config']['level']))
        config.automatic_function_calling = types.AutomaticFunctionCallingConfig(disable=True)
        if self.get_model().startswith('gemma-'):
            config.thinking_config = None
        try:
            result = await self.client.aio.models.generate_content(model=payloads['model'],
                contents=self._prepare_conversation(payloads), config=config)
        except Exception as error:
            raise classify_error(error) from None
        if not result.candidates:
            raise Failure('content_filter' if result.prompt_feedback else 'empty_response')
        candidate = result.candidates[0]
        if not candidate.content or not candidate.content.parts:
            raise Failure('empty_response')
        finish = str(candidate.finish_reason)
        if any(v in finish for v in ('SAFETY','PROHIBITED','SPII','BLOCKLIST')):
            raise Failure('content_filter')
        try:
            response = LLMResponse('assistant')
            response.raw_completion = result
            response.result_chain = self._process_content_parts(candidate, response)
            response.id = result.response_id
            if result.usage_metadata:
                response.usage = self._extract_usage(result.usage_metadata)
                # Google's prompt count includes cached tokens, unlike AstrBot's
                # input_other + input_cached convention.
                response.usage.input_other = max(0, (result.usage_metadata.prompt_token_count or 0)
                    - (result.usage_metadata.cached_content_token_count or 0))
            return response
        except Exception:
            raise Failure('invalid_tool_response') from None


class SingleOpenAI(ProviderOpenAIOfficial):
    async def text_chat(self, *, contexts=None, func_tool=None, **kwargs):
        payload, _ = await self._prepare_chat_payload(None, None, None,
            contexts, None, None, model=self.get_model())
        try:
            # Explicitly disable both the SDK retry and AstrBot's retry helper.
            self.client.max_retries = 0
            return await self._query(payload, func_tool, request_max_retries=1)
        except Exception as error:
            raise classify_error(error) from None


class Runtime:
    def __init__(self):
        self.state = State(Path.home()/'.local/share/personal-asis-router/router.sqlite3')
        self.children = {}
        self.retired = []
        self.version = ''
        self.router = Router(self.state, self.send, available=[])
        self.refresh()

    def refresh(self):
        """Respect disabled/deleted sources and repaired credentials on new calls."""
        manager = _context.provider_manager
        version = fingerprint([manager.provider_sources_config, getattr(manager,'providers_config',[])])
        if version == self.version:
            return
        self.state.config_version(fingerprint(manager.provider_sources_config))
        self.retired.extend(self.children.values())
        self.children = {}
        self.version = version
        available = []
        for model in MODELS:
            source = next((s for s in manager.provider_sources_config if s.get('id')==model.source), None)
            configured = manager.get_provider_config_by_id(model.source+'/'+model.name, merged=True)
            if model.paid and configured is None:
                continue
            if source and source.get('enable',True) and (not configured or configured.get('enable',True)):
                available.append(model.name)
        self.router.available = set(available)

    def config(self, model, task):
        manager = _context.provider_manager
        if model.paid:
            cfg = manager.get_provider_config_by_id(model.source+'/'+model.name, merged=True)
            if not cfg:
                raise Failure('configuration')
        else:
            source = next((s for s in manager.provider_sources_config if s.get('id')==model.source), None)
            if not source or not source.get('enable', True):
                raise Failure('configuration')
            cfg = copy.deepcopy(source)
        cfg = copy.deepcopy(cfg)
        cfg.update(id='router-child/'+model.name, model=model.name, timeout=60,
            gm_resp_image_modal=False, gm_native_search=False, gm_native_coderunner=False,
            gm_url_context=False)
        cfg['gm_thinking_config'] = dict(level='MEDIUM' if task=='complex' or model.pool in ('flash','spare_flash') else 'LOW',
                                         budget=1024 if task=='complex' else 0)
        # Existing keys remain on this VPS; one key is selected, never rotated.
        keys = cfg.get('key', [''])
        cfg['key'] = keys[:1] if isinstance(keys,list) else [keys]
        if not cfg['key'] or not cfg['key'][0]:
            raise Failure('configuration')
        return cfg

    async def send(self, model, messages, tools, task):
        self.refresh()
        if model.name not in self.router.available:
            raise Failure('configuration')
        key = (model.name, task)
        if key not in self.children:
            cfg = self.config(model, task)
            cls = SingleOpenAI if model.paid else SingleGoogle
            self.children[key] = cls(cfg, dict(streaming_response=False))
        child = self.children[key]
        try:
            return await child.text_chat(contexts=copy.deepcopy(messages), func_tool=tools,
                                         request_max_retries=1)
        except Exception as error:
            raise classify_error(error) from None

    async def close(self):
        for child in [*self.children.values(),*self.retired]:
            if isinstance(child, SingleGoogle):
                await child.client.aio.aclose()
            else:
                await child.client.close()
        self.state.db.close()


def runtime():
    global _runtime
    if _runtime is None:
        _runtime = Runtime()
    return _runtime


@register_provider_adapter('asis_smart_router', 'Personal Asis Smart LLM Router')
class SmartProvider(Provider):
    def __init__(self, provider_config, provider_settings):
        super().__init__(provider_config, provider_settings)
        self.set_model(provider_config.get('model','auto'))

    def get_current_key(self):
        return ''

    def set_key(self, key):
        if key:
            raise ValueError('router_uses_existing_sources')

    async def get_models(self):
        return ['auto','complex','summary']

    async def text_chat(self, prompt=None, contexts=None, system_prompt=None,
                        func_tool=None, model=None, tool_calls_result=None,
                        image_urls=None, audio_urls=None, extra_user_content_parts=None, **kwargs):
        from .llm_router import as_dict
        messages = [as_dict(m) for m in contexts or []]
        if system_prompt:
            messages.insert(0, dict(role='system',content=system_prompt))
        # Native Agent contexts already contain the user prompt and its extra
        # parts. Those same parts are passed again on every tool-loop step.
        # Append them only when assembling a new prompt, as the stock SDK does.
        if prompt is not None or image_urls or audio_urls:
            content = []
            if prompt:
                content.append(dict(type='text',text=prompt))
            content.extend(dict(type='image_url',image_url={'url':u}) for u in image_urls or [])
            content.extend(dict(type='audio_url',audio_url={'url':u}) for u in audio_urls or [])
            content.extend(as_dict(p) for p in extra_user_content_parts or [])
            messages.append(dict(role='user',content=content))
        for result in (tool_calls_result if isinstance(tool_calls_result,list) else [tool_calls_result]) or []:
            if result:
                messages.extend(result.to_openai_messages())
        selector = model or self.get_model()
        pieces = selector.split('|')
        profile = pieces[0] if pieces[0] in ('auto','daily','complex','summary') else self.get_model()
        scope = pieces[1] if len(pieces)>1 else fingerprint(['background', messages[:1]])
        try:
            current = runtime()
            current.refresh()
            return await current.router.generate(messages, func_tool, profile, scope,
                abort=kwargs.get('abort_signal'))
        except Failure as error:
            # A non-empty role=err avoids AstrBot's empty-output retries.
            messages = {
                'context_too_large':'这次必要材料超过可处理范围，请缩小范围后再试。',
                'timeout':'这次模型请求超时，结果尚未确定，已停止自动重发。',
                'unknown':'这次模型请求结果尚未确定，已停止自动重发。',
                'summary_failed':'历史摘要未能完成，这次回答已暂停，原始对话仍保留。',
                'content_filter':'模型未能处理这次内容。',
                'empty_response':'模型没有返回可用内容，这次已停止自动重发。',
                'invalid_tool_response':'模型返回的工具结果格式不可用，这次已停止自动重发。',
            }
            text = messages.get(error.kind,'当前模型暂时不可用，请稍后再试。')
            if error.status:
                text += f'（HTTP {error.status}）'
            return LLMResponse(role='err', completion_text=text)

    async def text_chat_stream(self, **kwargs):
        # No chunks are exposed until the single-shot generation is complete.
        yield await self.text_chat(**kwargs)
