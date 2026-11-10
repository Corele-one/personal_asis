"""Keep native fallback from bypassing the virtual Router's retry policy."""
import inspect


class NativeBoundary:
    def install(self):
        from astrbot.core import astr_main_agent
        original = astr_main_agent._get_fallback_chat_providers
        if list(inspect.signature(original).parameters) != [
                'provider', 'plugin_context', 'provider_settings']:
            raise RuntimeError('unsupported_router_fallback_sdk_contract')
        if getattr(self, 'installed', False):
            return

        def scoped(provider, plugin_context, provider_settings):
            if provider.provider_config.get('id', '') in (
                    'asis_router/auto', 'asis_router/complex', 'asis_router/summary'):
                return []
            return original(provider, plugin_context, provider_settings)

        self.module, self.original, self.wrapper = astr_main_agent, original, scoped
        astr_main_agent._get_fallback_chat_providers = scoped
        self.installed = True

    def close(self):
        if getattr(self, 'installed', False):
            if self.module._get_fallback_chat_providers is self.wrapper:
                self.module._get_fallback_chat_providers = self.original
            self.installed = False
