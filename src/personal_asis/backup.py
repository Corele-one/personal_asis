"""Authenticated encrypted local-state snapshots. Originals and OS secrets excluded."""

import base64
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import tarfile
import tempfile

from .config import load_config
from .credentials import CredentialStore, CredentialNotFound


MAGIC = b"ASISBAK1"
FILES = {"sources.yaml", "coordinator.json", "source-permissions.json", "index.sqlite3", "node-tasks.sqlite3"}


def key_store(node):
    return CredentialStore(node, service="local.personal-asis.backup")


def _key(store, create=False):
    try:
        value = store.get()
    except CredentialNotFound:
        if not create:
            raise ValueError("系统凭据库中没有备份密钥；请用离线恢复密钥解密") from None
        value = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
        store.set(value)
    try:
        raw = base64.b64decode(value.encode(), altchars=b"-_", validate=True)
        if len(raw) != 32:
            raise ValueError()
    except (ValueError, UnicodeError):
        raise ValueError("备份恢复密钥无效") from None
    return raw


def _file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_target(path):
    if not path.is_absolute():
        raise ValueError("备份或恢复目标必须为绝对路径")
    if any((parent / ".git").exists() for parent in (path, *path.parents)):
        raise ValueError("备份／恢复数据不能放在 Git 工作目录中")
    if path.is_symlink():
        raise ValueError("目标不能是符号链接")


def create(home, target, store=None):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    home, target = Path(home), Path(target)
    _check_target(target)
    config = load_config(home / "sources.yaml")
    raw_key = _key(store or key_store(config.node_id), create=True)
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Staging is private and stays on the node until the authenticated cipher is written.
    with tempfile.TemporaryDirectory(prefix="backup-", dir=home) as name:
        directory = Path(name)
        directory.chmod(0o700)
        snapshot = directory / "state"
        snapshot.mkdir(mode=0o700)
        before = (home / "sources.yaml").read_bytes()
        manifest = {"version": 1, "node_id": config.node_id, "created_at": datetime.now(timezone.utc).isoformat(), "files": {}}
        for filename in sorted(FILES):
            source, dest = home / filename, snapshot / filename
            if not source.is_file():
                continue
            if source.is_symlink():
                raise ValueError("备份状态文件不能是符号链接")
            if filename.endswith(".sqlite3"):
                with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as db, closing(sqlite3.connect(dest)) as backup:
                    db.backup(backup)
                    if backup.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise ValueError("SQLite 备份完整性校验失败")
                    backup.execute("PRAGMA journal_mode=DELETE").fetchone()
            else:
                shutil.copyfile(source, dest)
            dest.chmod(0o600)
            manifest["files"][filename] = _file_hash(dest)
        if (home / "sources.yaml").read_bytes() != before:
            raise ValueError("备份期间来源配置发生变化，请重试")
        (snapshot / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False))
        archive_path = directory / "state.tar.gz"
        with tarfile.open(archive_path, "w:gz") as archive:
            for source in (snapshot / n for n in sorted(set(manifest["files"]) | {"manifest.json"})):
                archive.add(source, arcname=source.name, recursive=False)
        nonce = secrets.token_bytes(12)
        header = MAGIC + nonce
        cipher = Cipher(algorithms.AES(raw_key), modes.GCM(nonce)).encryptor()
        cipher.authenticate_additional_data(header)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        # Do not interpolate a configurable node ID into a filesystem path.
        filename = "personal-asis-" + stamp + "-" + secrets.token_hex(4) + ".asis-backup"
        output = target / filename
        partial = target / (filename + ".partial")
        try:
            with archive_path.open("rb") as source, partial.open("xb") as dest:
                os.chmod(partial, 0o600)
                dest.write(header)
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    dest.write(cipher.update(chunk))
                dest.write(cipher.finalize())
                dest.write(cipher.tag)
                dest.flush()
                os.fsync(dest.fileno())
            os.replace(partial, output)
        finally:
            partial.unlink(missing_ok=True)
    return {"created": True, "path": str(output), "bytes": output.stat().st_size,
            "files": len(manifest["files"]), "originals_included": False, "credentials_included": False,
            "key_storage": "system_credential_store"}


def restore(archive_path, target, store=None, recovery_key=None):
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    archive_path, target = Path(archive_path), Path(target)
    _check_target(target)
    if target.exists() and any(target.iterdir()):
        raise ValueError("恢复目标必须是空目录，拒绝覆盖已有运行状态")
    if recovery_key is not None:
        class SuppliedKey:
            def get(self):
                return recovery_key
        store = SuppliedKey()
    if store is None:
        raise ValueError("需要明确指定本机备份密钥或离线恢复密钥")
    raw_key = _key(store)
    if archive_path.stat().st_size < len(MAGIC) + 12 + 16:
        raise ValueError("备份文件无效")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix="asis-restore-", dir=target.parent) as name:
        directory = Path(name)
        directory.chmod(0o700)
        plaintext = directory / "verified.tar.gz"
        with archive_path.open("rb") as source:
            header = source.read(len(MAGIC) + 12)
            if not header.startswith(MAGIC):
                raise ValueError("不支持的备份格式")
            source.seek(-16, 2)
            tag = source.read(16)
            source.seek(len(header))
            cipher = Cipher(algorithms.AES(raw_key), modes.GCM(header[len(MAGIC):], tag)).decryptor()
            cipher.authenticate_additional_data(header)
            remaining = archive_path.stat().st_size - len(header) - 16
            try:
                with plaintext.open("wb") as dest:
                    while remaining:
                        chunk = source.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise ValueError("备份文件被截断")
                        remaining -= len(chunk)
                        dest.write(cipher.update(chunk))
                    dest.write(cipher.finalize())
            except InvalidTag:
                raise ValueError("备份认证失败：密钥不匹配或文件已损坏") from None
        # Never parse or expose unauthenticated plaintext.
        contents = {}
        with tarfile.open(plaintext, "r:gz") as archive:
            for member in archive:
                if member.name not in FILES | {"manifest.json"} or not member.isfile() or member.name in contents:
                    raise ValueError("备份包含不允许的文件或路径")
                if member.size > 4 * 1024**3:
                    raise ValueError("备份状态文件超限")
                extracted = archive.extractfile(member)
                dest = directory / member.name
                with dest.open("wb") as output:
                    shutil.copyfileobj(extracted, output)
                dest.chmod(0o600)
                contents[member.name] = dest
        manifest = json.loads(contents["manifest.json"].read_text())
        if manifest.get("version") != 1 or set(manifest["files"]) != set(contents) - {"manifest.json"}:
            raise ValueError("备份清单无效")
        for filename, expected in manifest["files"].items():
            if _file_hash(contents[filename]) != expected:
                raise ValueError("备份文件校验失败")
            if filename.endswith(".sqlite3"):
                with closing(sqlite3.connect(contents[filename])) as db:
                    if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise ValueError("恢复数据库完整性校验失败")
        load_config(contents["sources.yaml"])
        target.mkdir(mode=0o700, exist_ok=True)
        if any(target.iterdir()):
            raise ValueError("恢复目标在操作期间发生变化，拒绝覆盖")
        for filename in manifest["files"]:
            shutil.copyfile(contents[filename], target / filename)
            (target / filename).chmod(0o600)
    return {"restored": True, "home": str(target), "files": len(manifest["files"]),
            "node_id": manifest["node_id"], "credentials_restored": False}
