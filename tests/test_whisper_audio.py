import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from personal_asis.whisper_audio import WhisperError, parse_response, read_key, transcribe


class WhisperTests(unittest.TestCase):
    def test_segment_parser_retains_original_language_and_times(self):
        result = parse_response(dict(text='合成 IC 文本', segments=[dict(start=0.1,end=1.4,text='合成 IC 文本')]))
        self.assertEqual(result['text'], '合成 IC 文本')
        self.assertEqual(result['segments'][0]['end'], 1.4)
        self.assertEqual(result['method'], 'whisper_large_v3')

    def test_rejects_invalid_timestamps_and_silent_output_is_explicit(self):
        for end in [float('nan'),float('inf'),302,-1]:
            with self.assertRaises(WhisperError):
                parse_response(dict(text='synthetic',segments=[dict(start=0,end=end,text='synthetic')]))
        self.assertEqual(parse_response(dict(text='',segments=[]))['text'], '[无可辨识语音]')

    def test_key_file_must_be_private_and_not_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'credential'
            path.write_text('synthetic-key');path.chmod(0o644)
            with self.assertRaises(WhisperError):read_key(path)
            path.chmod(0o600)
            self.assertEqual(read_key(path), 'synthetic-key')
            link=Path(tmp)/'link';link.symlink_to(path)
            with self.assertRaises(WhisperError):read_key(link)

    def test_multipart_payload_and_retryable_failure_use_one_request(self):
        try:
            import httpx
        except ImportError:
            self.skipTest('requires existing AstrBot httpx dependency')
        async def run():
            with tempfile.TemporaryDirectory() as tmp:
                key=Path(tmp)/'key';key.write_text('synthetic-key');key.chmod(0o600)
                audio=Path(tmp)/'audio.flac';audio.write_bytes(b'fLaC-synthetic')
                calls=[]
                async def ok(request):
                    body=await request.aread();calls.append(body)
                    self.assertEqual(str(request.url),'https://api.groq.com/openai/v1/audio/transcriptions')
                    self.assertEqual(request.headers['authorization'],'Bearer synthetic-key')
                    self.assertIn(b'whisper-large-v3',body)
                    self.assertIn(b'verbose_json',body)
                    self.assertIn(b'audio/flac',body)
                    return httpx.Response(200,json=dict(text='合成转写',segments=[dict(start=0,end=1,text='合成转写')]))
                result=await transcribe(audio,key,transport=httpx.MockTransport(ok))
                self.assertEqual(result['text'],'合成转写')
                async def error(request):
                    calls.append(await request.aread())
                    return httpx.Response(503,json={'secret_error_body':'must never be exposed'})
                with self.assertRaises(WhisperError) as raised:
                    await transcribe(audio,key,transport=httpx.MockTransport(error))
                self.assertEqual(raised.exception.status,503)
                self.assertEqual(str(raised.exception),'whisper_http_error')
                self.assertEqual(len(calls),2)
        asyncio.run(run())
