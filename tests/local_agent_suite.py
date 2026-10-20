"""Local acceptance suite: remote adapters must be unavailable, even transitively."""
import importlib.abc
import sys
import unittest


REMOTE_MODULES = frozenset('personal_asis.' + name for name in (
    'coordinator', 'node', 'transport', 'service', 'evidence',
    'analysis_channel', 'agent_channel', 'retrieval_channel',
    'feishu', 'agent_feishu', 'feishu_cards', 'pwa', 'web_auth',
))
LOCAL_TESTS = (
    'test_local_isolation', 'test_conversation', 'test_conversation_tools',
    'test_conversation_terminal', 'test_conversation_web', 'test_pi_terminal',
    'test_work', 'test_runtime', 'test_agent', 'test_agent_roles',
    'test_role_context', 'test_work_history', 'test_local_review',
)


class NoRemoteAdapters(importlib.abc.MetaPathFinder):
    def __init__(self):
        self.attempts = []

    def find_spec(self, fullname, path=None, target=None):
        if fullname in REMOTE_MODULES:
            self.attempts.append(fullname)
            raise ImportError('local_agent_remote_dependency_forbidden: ' + fullname)


if __name__ == '__main__':
    guard = NoRemoteAdapters()
    sys.meta_path.insert(0, guard)
    suite = unittest.defaultTestLoader.loadTestsFromNames(LOCAL_TESTS)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    loaded = REMOTE_MODULES.intersection(sys.modules)
    if guard.attempts or loaded:
        print('Remote dependency boundary failed: ' + ', '.join(sorted(set(guard.attempts) | loaded)), file=sys.stderr)
    sys.exit(0 if result.wasSuccessful() and not guard.attempts and not loaded else 1)
