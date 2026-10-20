import contextlib
import io
import json
import unittest
from unittest.mock import patch

from personal_asis import native_pi


class NativePiTests(unittest.TestCase):
    def test_native_preserves_args_cwd_and_environment_without_loading_core(self):
        args = ['--provider', 'xiaomi', '--model', 'mimo-v2.6-flash', '--continue']
        with patch.object(native_pi.os, 'execvpe') as execute:
            native_pi.main(['--plain', *args])
        binary, passed, environment = execute.call_args.args
        self.assertEqual(passed, [binary, str(native_pi.PACKAGE / 'dist/bundle/cli.js'), *args])
        self.assertEqual(environment, dict(native_pi.os.environ))

    def test_check_does_not_load_old_engine_or_read_credentials(self):
        output = io.StringIO()
        with patch.object(native_pi.os, 'execvpe') as execute, contextlib.redirect_stdout(output):
            self.assertEqual(native_pi.main(['--check']), 0)
        execute.assert_not_called()
        status = json.loads(output.getvalue())
        self.assertEqual(status['engine'], 'native')
        self.assertFalse(status['personal_data_extension'])
        self.assertFalse(status['asis_budget_enforced'])
        self.assertEqual(status['credential_reads'], 0)

    def test_explicit_old_engine_and_source_flags_keep_compatibility(self):
        with patch('personal_asis.pi_terminal.main', return_value=17) as old:
            self.assertEqual(native_pi.main(['--engine', 'conversation', '--continue']), 17)
            old.assert_called_once_with(['--engine', 'conversation', '--continue'])
        with patch('personal_asis.pi_terminal.main', return_value=18) as old:
            self.assertEqual(native_pi.main(['--source', 'study']), 18)
            old.assert_called_once_with(['--source', 'study'])

    def test_explicit_native_and_prompt_separator_do_not_consume_pi_prompt(self):
        args = ['--engine', 'native', '--plain', '--', '--engine', 'legacy']
        with patch.object(native_pi.os, 'execvpe') as execute:
            native_pi.main(args)
        self.assertEqual(execute.call_args.args[1][2:], ['--', '--engine', 'legacy'])

    def test_native_json_output_mode_is_not_mistaken_for_old_role(self):
        args = ['--mode', 'json', '--no-session']
        with patch.object(native_pi.os, 'execvpe') as execute:
            native_pi.main(['--plain', *args])
        self.assertEqual(execute.call_args.args[1][2:], args)

    def test_source_profile_uses_native_prompt_mcp_and_environment_without_core(self):
        from personal_asis import native_sources
        with patch.object(native_sources, 'prepare', return_value={
                'context':'/private/sources.md', 'xiaohongshu_mcp':True}), patch.object(
                native_sources, 'credential_environment', return_value={'ASIS_XHS_MCP_TOKEN':'synthetic'}), patch.object(
                native_pi.os, 'execvpe') as execute:
            native_pi.main(['--continue'])
        self.assertEqual(execute.call_args.args[1][2:], ['--append-system-prompt','/private/sources.md','--extension',str(native_pi.Path(__file__).resolve().parents[1] / 'runtime/pi-terminal/source-write.ts'),'--continue'])
        self.assertEqual(execute.call_args.args[2]['ASIS_XHS_MCP_TOKEN'], 'synthetic')

    def test_invalid_engine_stops_before_launch(self):
        with patch.object(native_pi.os, 'execvpe') as execute, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(native_pi.main(['--engine', 'unknown']), 2)
        execute.assert_not_called()
