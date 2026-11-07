"""Installed-SDK preflight using synthetic attachments, no real model or messages."""
import asyncio
import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, sys.argv[1])
module = importlib.import_module('astrbot_plugin_media_agent.main')


async def main():
    with tempfile.TemporaryDirectory(prefix='asis-media-sdk-') as tmp:
        root = Path(tmp)
        path = root / 'synthetic.pdf'
        path.write_bytes(b'%PDF-synthetic')
        with patch.object(Path, 'home', return_value=root):
            bot = module.MediaAgent(SimpleNamespace(get_provider_by_id=lambda _: None),
                dict(enabled=True, owner_id='owner', owner_platform='synthetic'))
        from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
        from astrbot.core.platform.astr_message_event import AstrMessageEvent
        from astrbot.core.platform.astrbot_message import MessageType
        from astrbot.core.platform.platform_metadata import PlatformMetadata
        message = AstrBotMessage()
        message.message_id = 'synthetic-media'
        message.sender = MessageMember(user_id='owner', nickname='synthetic')
        message.type = MessageType.FRIEND_MESSAGE
        message.self_id = 'synthetic-bot'
        message.session_id = 'owner'
        message.message = [module.File(name='synthetic.pdf', file=str(path))]
        event = AstrMessageEvent('识别附件', message,
            PlatformMetadata(name='synthetic', description='synthetic', id='synthetic'), 'owner')
        event.send = AsyncMock(side_effect=AssertionError('real_messages_forbidden'))
        assert bot.owner(event)
        catalog = json.loads(await bot.attachment_media(event))
        assert len(catalog) == 1
        token = catalog[0]['attachment_id']
        req = SimpleNamespace(system_prompt='', audio_urls=[], extra_user_content_parts=[])
        await bot.instructions(event, req)
        assert 'attachment_media' in req.system_prompt and token in req.system_prompt
        assert await bot.attachment_media(event, 'invented-file') == 'current_or_quoted_attachment_required'
        media_module = importlib.import_module('astrbot_plugin_media_agent.media_files')
        with patch.object(media_module, 'worker', AsyncMock(return_value=dict(total=1, unit=1, text='synthetic OCR', method='ocr'))):
            result = json.loads(await bot.attachment_media(event, token))
        assert result['all_units_complete']
        message.sender.user_id = 'stranger'
        assert await bot.attachment_media(event, token) == 'owner_private_chat_required'
        assert await bot.attachment_send_result(event, result['combined_result_id']) == 'owner_private_chat_required'
        message.sender.user_id = 'owner'
        message.type = MessageType.GROUP_MESSAGE
        assert await bot.attachment_media(event, token) == 'owner_private_chat_required'
        message.type = MessageType.FRIEND_MESSAGE
        message.message = [module.Record(file=str(path))]
        req = SimpleNamespace(system_prompt='', audio_urls=[str(path)], extra_user_content_parts=[])
        await bot.instructions(event, req)
        assert req.audio_urls == []
        assert await bot.attachment_media(event, token) == 'whisper_backend_not_configured'
        bot.config['audio_backend'] = 'groq_whisper'
        bot.key_file = root / 'groq.key'
        assert await bot.attachment_media(event, token) == 'whisper_private_credential_unavailable'
        bot.key_file.write_text('synthetic-not-a-real-key')
        bot.key_file.chmod(0o600)
        # Exercise the installed HTTP transport with synthetic credentials and
        # an in-process transport. No socket or paid request.
        import httpx
        calls = []
        status = [200]
        async def transport(request):
            body_bytes = await request.aread()
            calls.append(body_bytes)
            assert str(request.url) == 'https://api.groq.com/openai/v1/audio/transcriptions'
            assert b'whisper-large-v3' in body_bytes and b'audio/flac' in body_bytes
            body = dict(text='合成转写', segments=[dict(start=0,end=1,text='合成转写')])
            if status[0] != 200:
                body = {'error': 'synthetic failure body must not be exposed'}
            return httpx.Response(status[0], json=body)
        original_client = httpx.AsyncClient
        def synthetic_client(**kwargs):
            kwargs['transport'] = httpx.MockTransport(transport)
            return original_client(**kwargs)
        segment = root / 'segment.flac'
        segment.write_bytes(b'fLaC-synthetic')
        with patch.object(httpx,'AsyncClient',side_effect=synthetic_client):
            assert (await bot.transcribe(segment))['text'] == '合成转写'
            assert len(calls) == 1
            status[0] = 503
            try:
                await bot.transcribe(segment)
            except module.WhisperError as error:
                assert error.code == 'whisper_http_error' and error.status == 503
            else:
                raise AssertionError('synthetic_503_must_fail')
        assert len(calls) == 2  # one attempt even for a retryable 503
        event.send.assert_not_awaited()
        await bot.terminate()
        print(json.dumps(dict(sdk='passed', tools=['attachment_media','attachment_send_result'],
            owner_and_attachment_boundaries='passed', whisper_multipart_mock_transport='passed',
            whisper_503_no_retry=True, real_model_calls=0, real_messages_sent=0)))


asyncio.run(main())
