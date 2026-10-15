import json,shutil,subprocess,unittest
from pathlib import Path

@unittest.skipUnless(shutil.which('node'),'Node required for shipped UI WebCrypto validation')
class ContextUiTests(unittest.TestCase):
    def test_actual_ui_encrypted_goal_commands_and_continuity_options(self):
        value=subprocess.run(['node',str(Path(__file__).with_name('context-ui.cjs'))],capture_output=True,text=True,timeout=20)
        self.assertEqual(value.returncode,0,value.stderr)
        result=json.loads(value.stdout);self.assertTrue(result['encrypted_goal_read_save_replace_delete'])
        self.assertTrue(result['continuity_options_sent']);self.assertEqual(result['model_calls'],0)
