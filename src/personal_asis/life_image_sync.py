"""Stage images privately; copy to the vault only with the diary approval."""
from pathlib import Path
import os
import subprocess
import json
import tempfile
from . import life_images as images

REMOTE = 'PYTHONPATH=/home/mac/personal-asis-v2/src python3 -m personal_asis.life_image_export'
MAX_DOWNLOADS = 32


def prepare(config, state, profile, root, allowed):
    from .life_sync import safe_target, projected
    images.bind_paths(state['records'],config.get('daily_directory',images.DEFAULT_DAILY))
    pending, seen, downloads = [], set(), 0
    cache = Path(profile) / 'life-images'
    active = {images.filename(item) for r in state['records'].values()
              if not r['deleted'] for item in r.get('images', [])}
    if cache.exists():
        for path in cache.iterdir():
            if path.name not in active and path.is_file() and not path.is_symlink():
                path.unlink()
    for r in state['records'].values():
        if not projected(r):
            continue
        for item,relative in zip(r.get('images', []),images.paths(r)):
            if relative in seen:
                continue
            seen.add(relative)
            target = safe_target(root, relative)
            if not allowed(relative):
                raise ValueError('diary_image_target_excluded')
            if target.exists():
                if images.descriptor(images.read_bytes(target)) != item:
                    raise ValueError('diary_image_target_changed')
                continue
            local = safe_target(cache, images.filename(item))
            if local.exists():
                data = images.read_bytes(local)
            else:
                if downloads >= MAX_DOWNLOADS:
                    raise ValueError('diary_image_batch_limit')
                downloads += 1
                result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
                    '-o', 'ConnectionAttempts=1', '-p', str(config.get('port', 22)), config['host'], REMOTE],
                    input=json.dumps(dict(record_id=r['id'], sha256=item['sha256'])).encode(),
                    capture_output=True, timeout=30)
                if result.returncode:
                    raise ValueError('diary_image_download_unavailable')
                data = result.stdout
            if images.descriptor(data) != item:
                raise ValueError('diary_image_integrity_failed')
            if not local.exists():
                images.write_bytes(local, data)
            pending.append(dict(path=target, relative=relative, cache=local, image=item))
    return pending


def preview(pending):
    if pending:
        print('\n  图片附件（与日记一并确认后保存）：')
        for item in pending:
            print(f"    {item['path']} · {item['image']['size']} 字节")


def apply(pending, root, allowed):
    from .life_sync import safe_target
    # Validate all images before writing the first one; never replace user data.
    for item in pending:
        target = safe_target(root, item['relative'])
        if target != item['path'] or not allowed(item['relative']):
            raise ValueError('diary_image_target_changed')
        if target.exists() and images.descriptor(images.read_bytes(target)) != item['image']:
            raise ValueError('diary_image_target_changed')
        if images.descriptor(images.read_bytes(item['cache'])) != item['image']:
            raise ValueError('diary_image_cache_changed')
    for item in pending:
        target = safe_target(root, item['relative'])
        if not target.exists():
            # Exclusive creation also rejects a path created after validation.
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            safe_target(root, item['relative'])
            data = images.read_bytes(item['cache'])
            if images.descriptor(data) != item['image']:
                raise ValueError('diary_image_cache_changed')
            fd, name = tempfile.mkstemp(prefix='.image-', dir=target.parent)
            try:
                with os.fdopen(fd, 'wb') as handle:
                    handle.write(data)
                # Atomic, exclusive installation; a crash never leaves half an image.
                os.link(name, target)
            finally:
                Path(name).unlink(missing_ok=True)
