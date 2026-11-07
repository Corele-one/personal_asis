"""Private, content-addressed images for explicitly submitted diary entries."""
import base64
from datetime import datetime, timedelta
import hashlib
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

MAX_BYTES = 12 * 1024 * 1024
MAX_IMAGES = 8
DEFAULT_DAILY = 'Calendar/Journal/Daily'


def extension(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    if data.startswith((b'GIF87a', b'GIF89a')):
        return 'gif'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return 'webp'
    raise ValueError('unsupported_diary_image')


def descriptor(data):
    if not 0 < len(data) <= MAX_BYTES:
        raise ValueError('diary_image_size_limit')
    return dict(sha256=hashlib.sha256(data).hexdigest(), size=len(data), extension=extension(data))


def validate(images):
    if not isinstance(images, list) or len(images) > MAX_IMAGES:
        raise ValueError('invalid_diary_images')
    for item in images:
        if (not isinstance(item, dict) or set(item) != {'sha256', 'size', 'extension'}
                or not isinstance(item['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', item['sha256'])
                or type(item['size']) is not int or not 0 < item['size'] <= MAX_BYTES
                or item['extension'] not in ('png', 'jpg', 'gif', 'webp')):
            raise ValueError('invalid_diary_image')


def filename(item):
    validate([item])
    return item['sha256'] + '.' + item['extension']


def vault_path(item, record, index=0, daily=DEFAULT_DAILY):
    """Match the vault's assets/YYYY-MM-DD/file-YYYYMMDDHHMMSSmmm.ext convention."""
    validate([item])
    at = datetime.fromisoformat(record['occurred_at']).astimezone(ZoneInfo('Asia/Shanghai'))
    day = datetime.fromisoformat(record['day'])
    at = at.replace(year=day.year,month=day.month,day=day.day) + timedelta(milliseconds=index)
    stamp = at.strftime('%Y%m%d%H%M%S') + f'{at.microsecond//1000:03d}'
    return (Path(daily)/'assets'/record['day']/('file-'+stamp+'.'+item['extension'])).as_posix()


def bind_paths(records, daily=DEFAULT_DAILY):
    """Derive readable local targets; source descriptors remain content-addressed."""
    used = {}
    for r in sorted(records.values(),key=lambda r:(r['day'],r['occurred_at'],r['id'])):
        paths = []
        for index,item in enumerate(r.get('images',[])):
            offset = index
            path = vault_path(item,r,offset,daily)
            while path in used and used[path] != item:
                offset += 1
                path = vault_path(item,r,offset,daily)
            used[path] = item
            paths.append(path)
        if paths:
            r['_diary_image_paths'] = paths
        else:
            r.pop('_diary_image_paths',None)


def paths(record):
    return record.get('_diary_image_paths') or [vault_path(v,record,i) for i,v in enumerate(record.get('images',[]))]


def embed(record, index):
    # Timestamp filenames are unique and follow the existing short wiki embeds.
    return '![[' + Path(paths(record)[index]).name + ']]'


def read_bytes(path):
    path = Path(path)
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('diary_image_symlink_or_relative_path')
    with path.open('rb') as handle:
        data = handle.read(MAX_BYTES + 1)
    return data


def write_bytes(path, data):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('diary_image_symlink_denied')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix='.image-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
        Path(name).replace(path)
        path.chmod(0o600)
    finally:
        Path(name).unlink(missing_ok=True)


def capture(components, home):
    """Use only SDK Image components already received; never fetch a URL."""
    if not components:
        return []
    from astrbot.api.message_components import Image
    values = []
    for comp in components:
        if not isinstance(comp, Image):
            continue
        if len(values) >= MAX_IMAGES:
            raise ValueError('diary_image_count_limit')
        raw = comp.file or comp.path
        if not isinstance(raw, str):
            raise ValueError('diary_image_unavailable')
        if raw.startswith('base64://'):
            encoded = raw[len('base64://'):]
            if len(encoded) > 4 * ((MAX_BYTES + 2) // 3):
                raise ValueError('diary_image_size_limit')
            data = base64.b64decode(encoded, validate=True)
        else:
            parsed = urlsplit(raw)
            if parsed.scheme == 'file' and not parsed.netloc:
                raw = unquote(parsed.path)
            elif parsed.scheme:
                raise ValueError('diary_image_local_data_required')
            data = read_bytes(Path(raw))
        item = descriptor(data)
        write_bytes(Path(home) / 'images' / filename(item), data)
        values.append(item)
    return values


def export(store, request):
    from .life_intake import is_entry
    if (not isinstance(request, dict) or set(request) != {'record_id', 'sha256'}
            or any(not isinstance(v, str) or not re.fullmatch('[a-f0-9]{64}', v) for v in request.values())):
        raise ValueError('invalid_diary_image_request')
    r = store.get(request['record_id'])
    if r['deleted'] or not is_entry(r):
        raise ValueError('active_diary_entry_required')
    images = r.get('images', [])
    validate(images)
    item = next((v for v in images if v['sha256'] == request['sha256']), None)
    if item is None:
        raise ValueError('record_image_required')
    data = read_bytes(store.path.parent / 'images' / filename(item))
    if descriptor(data) != item:
        raise ValueError('diary_image_integrity_failed')
    return data
