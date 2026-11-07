"""Bounded local PDF/audio operations. No network, credentials, or shell strings."""
import json
import math
import os
from pathlib import Path
import resource
import subprocess
import sys


class CommandError(ValueError):
    def __init__(self, code, tool, exit_code=None):
        self.code, self.tool, self.exit_code = code, tool, exit_code
        super().__init__(code)


def command(args, timeout=35):
    env = dict(os.environ, OMP_THREAD_LIMIT='1', OPENBLAS_NUM_THREADS='1')
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        raise CommandError('local_command_timeout', args[0]) from None
    if result.returncode:
        raise CommandError('local_command_failed', args[0], result.returncode)
    if len(result.stdout) > 2 * 1024 * 1024:
        raise ValueError('media_output_too_large')
    return result.stdout.decode('utf-8', errors='replace')


def pdf(source, directory, page):
    info = command(['pdfinfo', str(source)])
    fields = dict(line.split(':', 1) for line in info.splitlines() if ':' in line)
    if fields.get('Encrypted', '').strip().startswith('yes'):
        raise ValueError('encrypted_pdf_not_supported')
    total = int(fields.get('Pages', '0'))
    if not 1 <= total <= 500 or not 1 <= page <= total:
        raise ValueError('pdf_page_out_of_range_or_limit')
    text = command(['pdftotext', '-f', str(page), '-l', str(page), '-layout', str(source), '-'])
    method = 'text'
    if len(text.strip()) < 30:
        prefix = directory / 'page'
        command(['pdftoppm', '-f', str(page), '-l', str(page), '-singlefile',
                 '-scale-to', '2000', '-gray', '-png', str(source), str(prefix)])
        text = command(['tesseract', str(prefix) + '.png', 'stdout', '-l', 'chi_sim+eng', '--psm', '3'])
        method = 'ocr'
    if len(text) > 50000:
        raise ValueError('page_text_too_large')
    return dict(total=total, unit=page, method=method, text=text.strip(),
                warning='OCR可能误识别公式、手写、多栏及表格；空白结果不证明页面没有内容。' if method == 'ocr' else '')


def audio(source, directory, unit):
    formats = 'mov,mp4,m4a,3gp,3g2,mj2,mp3,wav,flac,ogg,aac,asf,amr,matroska,webm'
    raw = command(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-format_whitelist', formats,
                   '-show_entries', 'format=duration:stream=codec_name,codec_type',
                   '-of', 'json', str(source)])
    probe = json.loads(raw)
    duration = float(probe['format']['duration'])
    if not math.isfinite(duration) or not 0 < duration <= 4 * 3600:
        raise ValueError('audio_duration_limit_4_hours')
    total = math.ceil(duration / 300)
    if not 1 <= unit <= total:
        raise ValueError('audio_unit_out_of_range')
    start = (unit - 1) * 300
    length = min(300, duration - start)
    codecs = [s.get('codec_name') for s in probe.get('streams', []) if s.get('codec_type') == 'audio']
    copy_aac = bool(codecs and codecs[0] == 'aac')
    output = directory / ('segment.m4a' if copy_aac else 'segment.flac')
    args = ['ffmpeg', '-nostdin', '-v', 'error', '-threads', '1', '-filter_threads', '1',
            '-protocol_whitelist', 'file,pipe', '-format_whitelist', formats,
            '-ss', str(start), '-i', str(source), '-t', str(length), '-map', '0:a:0', '-vn']
    if copy_aac:
        args += ['-c:a', 'copy']
    else:
        args += ['-ac', '1', '-ar', '16000', '-sample_fmt', 's16', '-c:a', 'flac',
                 '-compression_level', '0', '-threads', '1']
    command(args + ['-y', str(output)], timeout=45)
    if not output.is_file() or not 0 < output.stat().st_size <= 12 * 1024 * 1024:
        raise ValueError('audio_segment_size_limit')
    return dict(total=total, unit=unit, start_seconds=start, end_seconds=start + length,
                audio_file=output.name, audio_preprocessing='aac_stream_copy' if copy_aac else 'flac_16khz_mono_s16',
                duration_seconds=duration)


def main():
    os.umask(0o077)
    if sys.platform == 'linux':
        resource.setrlimit(resource.RLIMIT_AS, (384 * 1024**2, 384 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CPU, (70, 75))
    try:
        kind, source, directory, unit = sys.argv[1:]
        result = {'pdf': pdf, 'audio': audio}[kind](Path(source), Path(directory), int(unit))
    except CommandError as error:
        result = dict(error=error.code, tool=error.tool, exit_code=error.exit_code)
    except MemoryError:
        result = {'error': 'local_memory_limit'}
    except (ValueError, KeyError, OSError, subprocess.SubprocessError):
        result = {'error': 'local_media_processing_failed_check_format_limits_and_dependencies'}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
