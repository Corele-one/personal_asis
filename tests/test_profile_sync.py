import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from personal_asis import profile_sync as sync
from personal_asis import profile_transfer as transfer
from test_personal_profile import fixture


class ProfileSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.home=self.root/'mac';self.home.mkdir()
        self.profile=self.root/'profile';self.profile.mkdir();self.remote=self.root/'vps'
        self.study=self.root/'study';(self.study/'Plan').mkdir(parents=True)
        self.source=self.study/'Plan/synthetic.md';self.source.write_text('synthetic\n'*6)
        (self.home/'sources.yaml').write_text(json.dumps(dict(node_id='synthetic',sources=[
            dict(id='study',root=str(self.study),index=True,policy='private',exclude=[])])))
        self.value=fixture();self.value['facts'][0]['citations'][0]['sha256']=hashlib.sha256(self.source.read_bytes()).hexdigest()
        transfer.handle(dict(operation='replace',expected=None,profile=self.value),self.remote)
        self.config=dict(host='owner@example.test',profile_sync_mode='confirm')
        self.calls=[]

    def exchange(self, config, request):
        self.calls.append(copy.deepcopy(request))
        return transfer.handle(request,self.remote)

    def current(self):
        return transfer.handle(dict(operation='read'),self.remote)

    def proposal(self):
        value=copy.deepcopy(self.value);value.update(status='draft',approved_on=None)
        value['facts'][0]['statement']='合成的新背景，待本人确认。'
        (self.profile/'personal-profile-next.json').write_text(json.dumps(value))
        return value

    def run_sync(self):
        with patch.object(sync,'exchange',side_effect=self.exchange),contextlib.redirect_stdout(io.StringIO()):
            return sync.run(self.config,self.home,self.profile,interactive=True)

    def test_check_only_snapshots_current_profile_and_flags_source_changes(self):
        self.config['profile_sync_mode']='check';self.proposal()
        with patch('builtins.input') as question:
            self.assertEqual(self.run_sync(),'checked')
        question.assert_not_called()
        cache=self.profile/'personal-profile-remote.json'
        self.assertEqual(json.loads(cache.read_text())['profile'],self.value)
        self.assertEqual(cache.stat().st_mode&0o777,0o600)
        self.source.write_text('changed source')
        self.assertEqual(len(sync.sources_changed(self.value,self.home)),1)
        self.assertTrue(all(r['operation']=='read' for r in self.calls))

    def test_skip_then_confirm_updates_once_and_preserves_evidence(self):
        proposal=self.proposal()
        with patch('builtins.input',return_value='跳过'):
            self.assertEqual(self.run_sync(),'skipped')
        self.assertEqual(self.current()['profile'],self.value)
        with patch('builtins.input',return_value='确认更新背景'):
            self.assertEqual(self.run_sync(),'updated')
        current=self.current()['profile']
        self.assertEqual(current['facts'],proposal['facts'])
        self.assertEqual(current['status'],'approved')
        with patch('builtins.input') as question:
            self.assertEqual(self.run_sync(),'up_to_date')
        question.assert_not_called()
        self.assertEqual(sum(r['operation']=='replace' for r in self.calls),1)

    def test_wrong_confirmation_never_publishes(self):
        self.proposal()
        with patch('builtins.input',return_value='确认写入'):
            self.assertEqual(self.run_sync(),'skipped')
        self.assertTrue(all(r['operation']=='read' for r in self.calls))

    def test_candidate_and_source_changes_after_preview_require_reconfirmation(self):
        self.proposal();pending=self.profile/'personal-profile-next.json'
        for changed in ('candidate','source'):
            with self.subTest(changed=changed):
                self.proposal();self.source.write_text('synthetic\n'*6)
                def confirm(_):
                    if changed=='candidate':pending.write_text('{}')
                    else:self.source.write_text('changed during confirmation')
                    return '确认更新背景'
                with patch('builtins.input',side_effect=confirm),self.assertRaises(ValueError):self.run_sync()
        self.assertTrue(all(r['operation']=='read' for r in self.calls))

    def test_unknown_delivery_is_read_back_and_not_retried(self):
        self.proposal()
        def lost_ack(config,request):
            value=self.exchange(config,request)
            if request['operation']=='replace':raise subprocess.TimeoutExpired('synthetic',12)
            return value
        with patch.object(sync,'exchange',side_effect=lost_ack),patch('builtins.input',return_value='确认更新背景'),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sync.run(self.config,self.home,self.profile,interactive=True),'unknown')
        with patch('builtins.input') as question:
            self.assertEqual(self.run_sync(),'up_to_date')
        question.assert_not_called()
        self.assertEqual(sum(r['operation']=='replace' for r in self.calls),1)
        receipt=json.loads((self.profile/'personal-profile-sync-receipt.json').read_text())
        self.assertEqual(receipt['state'],'confirmed_after_readback')

    def test_remote_concurrent_edit_is_not_overwritten(self):
        self.proposal();external=copy.deepcopy(self.value);external['facts'][0]['statement']='另一端已经修订的合成背景。'
        def concurrent(_):
            transfer.handle(dict(operation='replace',expected=self.current()['hash'],profile=external),self.remote)
            return '确认更新背景'
        with patch('builtins.input',side_effect=concurrent):
            self.assertEqual(self.run_sync(),'unknown')
        self.assertEqual(self.current()['profile'],external)

    def test_remote_forget_scrubs_cache_without_restoring_approved_local_copy(self):
        self.run_sync()
        (self.profile/'personal-profile-approved.json').write_text(json.dumps(self.value))
        (self.remote/'personal-profile.json').unlink()
        with patch('builtins.input') as question:self.assertEqual(self.run_sync(),'checked')
        question.assert_not_called()
        self.assertIsNone(json.loads((self.profile/'personal-profile-remote.json').read_text())['profile'])
        self.assertIsNone(self.current()['profile'])

    def test_disabled_and_noninteractive_never_use_network_or_read_candidate(self):
        self.proposal()
        with patch.object(sync,'exchange') as network,patch('builtins.input') as question:
            self.assertEqual(sync.run(self.config,self.home,self.profile,interactive=False),'disabled')
            self.assertEqual(sync.run(dict(self.config,profile_sync_mode='off'),self.home,self.profile,interactive=True),'disabled')
        network.assert_not_called();question.assert_not_called()

    def test_excluded_or_symlinked_source_cannot_be_published(self):
        self.proposal()
        for change in ('exclude','symlink'):
            with self.subTest(change=change):
                if change=='exclude':
                    c=json.loads((self.home/'sources.yaml').read_text());c['sources'][0]['exclude']=['Plan/**'];(self.home/'sources.yaml').write_text(json.dumps(c))
                else:
                    c['sources'][0]['exclude']=[];(self.home/'sources.yaml').write_text(json.dumps(c))
                    self.source.unlink();self.source.symlink_to(self.root/'outside.md');(self.root/'outside.md').write_text('synthetic\n'*6)
                with patch('builtins.input') as question,self.assertRaises(ValueError):self.run_sync()
                question.assert_not_called()
        self.assertTrue(all(r['operation']=='read' for r in self.calls))

    def test_fixed_transfer_rejects_drafts_arbitrary_paths_and_stale_versions(self):
        before=self.current()
        bad=copy.deepcopy(self.value);bad.update(status='draft',approved_on=None)
        requests=[dict(operation='replace',expected=before['hash'],profile=bad),dict(operation='read',path='/etc/passwd'),
                  dict(operation='replace',expected='0'*64,profile=self.value)]
        for request in requests:
            with self.subTest(request=request['operation']),self.assertRaises(ValueError):transfer.handle(request,self.remote)
        self.assertEqual(self.current(),before)
        self.assertEqual((self.remote/'personal-profile.json').stat().st_mode&0o777,0o600)

    def test_transfer_rejects_symlink_target(self):
        target=self.remote/'personal-profile.json';target.unlink();target.symlink_to(self.root/'outside.json')
        with self.assertRaises(ValueError):transfer.handle(dict(operation='replace',expected=None,profile=self.value),self.remote)
        self.assertFalse((self.root/'outside.json').exists())

    def test_client_validates_snapshot_hash_before_caching(self):
        response=dict(version=1,hash='0'*64,profile=self.value)
        with patch('subprocess.run',return_value=subprocess.CompletedProcess([],0,json.dumps(response),'')):
            with self.assertRaises(ValueError):sync.exchange(self.config,dict(operation='read'))

    def test_life_sync_checks_profile_independently_of_diary_confirmation(self):
        from personal_asis.life_sync import startup
        config=dict(self.config,enabled=True);(self.profile/'life-sync.json').write_text(json.dumps(config))
        life=self.root/'life';life.mkdir()
        c=json.loads((self.home/'sources.yaml').read_text());c['sources'].append(dict(id='life',root=str(life),index=True,policy='private'))
        (self.home/'sources.yaml').write_text(json.dumps(c))
        with patch('personal_asis.life_sync.pull'),patch('personal_asis.life_sync.publish_status'),patch.object(sync,'run',return_value='checked') as background,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(startup(self.home,self.profile,interactive=True),'up_to_date')
            background.assert_called_once()
        with patch('personal_asis.life_sync.pull') as pull,patch.object(sync,'run') as background:
            self.assertEqual(startup(self.home,self.profile,interactive=False),'interactive_sync_required')
            pull.assert_not_called();background.assert_not_called()
