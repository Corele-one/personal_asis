import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, AsyncMock

from personal_asis.media_files import MediaFiles, snapshot


class MediaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / 'input.media'
        self.source.write_bytes(b'synthetic input only')
        self.media = MediaFiles(self.root / 'cache')

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def local_audio(self, kind, source, directory, unit):
        (directory / 'segment.flac').write_bytes(b'synthetic flac')
        return dict(total=2, unit=unit, start_seconds=(unit-1)*300, end_seconds=unit*300)

    async def test_audio_cache_partial_then_complete_export(self):
        call = AsyncMock(return_value='synthetic transcript')
        with patch('personal_asis.media_files.worker', side_effect=self.local_audio):
            first = await self.media.process('audio', self.source, scope='owner', transcribe=call)
            self.assertFalse(first['all_units_complete'])
            self.assertEqual(first['next_unit'], 2)
            again = await self.media.process('audio', self.source, scope='owner', transcribe=call)
            self.assertTrue(again['cached'])
            self.assertEqual(call.await_count, 1)
            second = await self.media.process('audio', self.source, scope='owner', unit=2, transcribe=call)
            self.assertTrue(second['all_units_complete'])
            self.assertIsNone(second['next_unit'])
            self.assertEqual(second['completed_units'], [1, 2])
            output = Path(second['combined_output_path'])
            self.assertIn('300–600秒', output.read_text())
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ValueError):
                self.media.claim_delivery(second['combined_result_id'], 'stranger')
            self.media.claim_delivery(second['combined_result_id'], 'owner')
            with self.assertRaises(FileExistsError):
                self.media.claim_delivery(second['combined_result_id'], 'owner')

    async def test_unknown_audio_request_is_never_replayed(self):
        call = AsyncMock(side_effect=TimeoutError())
        with patch('personal_asis.media_files.worker', side_effect=self.local_audio):
            first = await self.media.process('audio', self.source, scope='owner', transcribe=call)
            self.assertIn('unknown', first['error'])
            # A fresh instance simulates process restart after an unknown request.
            restarted = MediaFiles(self.media.home)
            second = await restarted.process('audio', self.source, scope='owner', transcribe=call)
            self.assertIn('unknown', second['error'])
            self.assertEqual(call.await_count, 1)

    async def test_cancellation_leaves_durable_unknown_receipt(self):
        call = AsyncMock(side_effect=asyncio.CancelledError())
        with patch('personal_asis.media_files.worker', side_effect=self.local_audio):
            with self.assertRaises(asyncio.CancelledError):
                await self.media.process('audio', self.source, scope='owner', transcribe=call)
            result = await self.media.process('audio', self.source, scope='owner', transcribe=call)
            self.assertIn('unknown', result['error'])
            self.assertEqual(call.await_count, 1)

    async def test_ocr_and_text_pages_preserve_source_and_provenance(self):
        before = self.source.read_bytes()
        local = AsyncMock(side_effect=[dict(total=2, unit=1, text='合成识别', method='ocr', warning='待核对'),
                                      dict(total=2, unit=2, text='source text', method='text')])
        with patch('personal_asis.media_files.worker', local):
            first = await self.media.process('pdf', self.source, scope='owner')
            second = await self.media.process('pdf', self.source, scope='owner', unit=2)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(first['method'], 'ocr')
        self.assertTrue(second['all_units_complete'])
        self.assertIn('第2页', Path(second['combined_output_path']).read_text())

    async def test_busy_invalid_units_and_foreign_scope(self):
        await self.media.lock.acquire()
        self.assertIn('busy', (await self.media.process('pdf', self.source, scope='owner'))['error'])
        self.media.lock.release()
        for value in [0, -1, 1.5, True, '1']:
            self.assertIn('invalid', (await self.media.process('pdf', self.source, scope='owner', unit=value))['error'])
        with self.assertRaises(ValueError):
            self.media.claim_delivery('../not-a-result', 'owner')

    async def test_source_symlink_is_rejected(self):
        link = self.root / 'link'
        link.symlink_to(self.source)
        with self.assertRaises(ValueError):
            snapshot(link, self.root / 'out')

    async def test_no_background_audio_call_before_local_validation(self):
        call = AsyncMock()
        with patch('personal_asis.media_files.worker', side_effect=ValueError('bad file')):
            result = await self.media.process('audio', self.source, scope='owner', transcribe=call)
        self.assertIn('error', result)
        self.assertEqual(result['diagnostic']['phase'], 'local_processing')
        call.assert_not_awaited()

    async def test_whisper_segments_are_shifted_and_safe_diagnostics_retained(self):
        from personal_asis.whisper_audio import WhisperError
        call=AsyncMock(return_value=dict(text='合成文本',method='whisper_large_v3',segments=[dict(start=1,end=2,text='合成文本')]))
        with patch('personal_asis.media_files.worker',side_effect=self.local_audio):
            result=await self.media.process('audio',self.source,scope='owner',unit=2,provider_id='groq/whisper-large-v3',transcribe=call)
            self.assertEqual(result['segments'][0]['start'],301)
            self.assertIn('300–600秒',Path(result['combined_output_path']).read_text())
            failed=AsyncMock(side_effect=WhisperError('whisper_http_error',429))
            first=await self.media.process('audio',self.source,scope='owner',provider_id='groq/whisper-large-v3',transcribe=failed)
            self.assertEqual(first['diagnostic'],dict(phase='audio_transcription',code='whisper_http_error',http_status=429))
            second=await self.media.process('audio',self.source,scope='owner',provider_id='groq/whisper-large-v3',transcribe=failed)
            self.assertEqual(second['diagnostic']['http_status'],429)
            self.assertEqual(failed.await_count,1)

    async def test_local_conversion_timeout_is_actionable_without_private_error_text(self):
        from personal_asis.media_files import MediaLocalError
        error=MediaLocalError('local_command_timeout','ffmpeg')
        with patch('personal_asis.media_files.worker',side_effect=error):
            result=await self.media.process('audio',self.source,scope='owner',transcribe=AsyncMock())
        self.assertEqual(result['diagnostic'],dict(phase='local_processing',code='local_command_timeout',tool='ffmpeg'))

    async def test_worker_converts_timeout_to_safe_command_error(self):
        import subprocess
        from personal_asis.media_worker import command,CommandError
        with patch('personal_asis.media_worker.subprocess.run',side_effect=subprocess.TimeoutExpired(['ffmpeg','private-source'],45)):
            with self.assertRaises(CommandError) as raised:
                command(['ffmpeg','private-source'])
        self.assertEqual(str(raised.exception),'local_command_timeout')
        self.assertNotIn('private-source',str(raised.exception))
