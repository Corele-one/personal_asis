"""Single-attempt Groq Whisper transport. Never log key, audio, or error bodies."""
import json
import math
from pathlib import Path


class WhisperError(ValueError):
    def __init__(self, code, status=None):
        self.code = code
        self.status = status
        super().__init__(code)


def read_key(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise WhisperError('whisper_private_credential_unavailable')
    key = path.read_text().strip()
    if not key or any(c.isspace() for c in key):
        raise WhisperError('whisper_private_credential_invalid')
    return key


def parse_response(data):
    if not isinstance(data, dict) or not isinstance(data.get('text'), str):
        raise WhisperError('whisper_invalid_response')
    text = data['text'].strip()
    if len(text) > 50000:
        raise WhisperError('whisper_response_too_large')
    segments = []
    rows = data.get('segments', [])
    if not isinstance(rows, list) or len(rows) > 5000:
        raise WhisperError('whisper_invalid_segments')
    previous = 0
    for row in rows:
        try:
            start, end = float(row['start']), float(row['end'])
            content = row['text']
        except (TypeError, ValueError, KeyError):
            raise WhisperError('whisper_invalid_segments') from None
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start <= end <= 301
                and start >= previous and isinstance(content, str)):
            raise WhisperError('whisper_invalid_segments')
        previous = start
        segments.append(dict(start=round(start, 3), end=round(end, 3), text=content.strip()))
    return dict(text=text or '[无可辨识语音]', segments=segments, method='whisper_large_v3')


async def transcribe(path, key_file, *, transport=None):
    import httpx
    suffix = Path(path).suffix.lower()
    if suffix not in {'.flac', '.m4a'}:
        raise WhisperError('whisper_invalid_audio_format')
    mime = 'audio/mp4' if suffix == '.m4a' else 'audio/flac'
    key = read_key(key_file)
    data = dict(model='whisper-large-v3', response_format='verbose_json', temperature='0',
                **{'timestamp_granularities[]': 'segment'})
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(70, connect=10), follow_redirects=False,
                                     transport=transport) as client:
            with Path(path).open('rb') as audio:
                async with client.stream('POST', 'https://api.groq.com/openai/v1/audio/transcriptions',
                    headers={'Authorization': 'Bearer ' + key}, data=data,
                    files={'file': ('segment' + suffix, audio, mime)}) as response:
                    if response.status_code != 200:
                        raise WhisperError('whisper_http_error', response.status_code)
                    content = bytearray()
                    async for block in response.aiter_bytes():
                        content.extend(block)
                        if len(content) > 2 * 1024**2:
                            raise WhisperError('whisper_response_too_large')
                    try:
                        return parse_response(json.loads(content))
                    except (ValueError, TypeError) as error:
                        if isinstance(error, WhisperError):
                            raise
                        raise WhisperError('whisper_invalid_response') from None
    except httpx.TimeoutException:
        raise WhisperError('whisper_request_timeout') from None
    except httpx.RequestError:
        raise WhisperError('whisper_transport_error') from None
