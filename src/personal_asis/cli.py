import argparse
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys

from .config import DEFAULT_HOME, load_config
from .index import Index
from .service import daemon, install, uninstall


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2), flush=True)


def doctor():
    db = sqlite3.connect(":memory:")
    try:
        db.execute("CREATE VIRTUAL TABLE f USING fts5(text, tokenize='trigram')")
        fts5 = True
    except sqlite3.OperationalError:
        fts5 = False
    finally:
        db.close()
    return {"python": platform.python_version(), "executable": sys.executable,
            "sqlite": sqlite3.sqlite_version, "fts5_trigram": fts5,
            "platform": platform.system(), "network_enabled": False}


def init(home, root, node_id):
    root = root.expanduser().absolute()
    if not all((root / name).is_dir() for name in ("Note", "Daily")):
        raise ValueError("测试根目录必须有 Note/ 和 Daily/ 子目录")
    path = home / "sources.yaml"
    if path.exists():
        raise ValueError("已有 sources.yaml，拒绝覆盖；请在本机编辑")
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(home, 0o700)
    data = {"node_id": node_id, "sources": [
        {"id": name.lower(), "root": str(root / name),
         "policy": "private" if name == "Daily" else "normal", "index": True,
         "remote_metadata": False,
         "exclude": [] if name == "Daily" else ["Health", "health", "健康", "**/Health", "**/health", "**/健康"]}
        for name in ("Note", "Daily")
    ]}
    with path.open("x", encoding="utf-8") as handle:
        os.chmod(path, 0o600)
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    load_config(path)
    return {"initialized": True, "home": str(home), "remote_metadata": False}


def main(argv=None):
    # Also restrict SQLite WAL/SHM sidecars and temporary output.
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="PA0 本地 Markdown 证据检索")
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME, help="本机私密运行数据目录")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    p = commands.add_parser("init")
    p.add_argument("--test-root", required=True, type=Path)
    p.add_argument("--node-id", default="mac")
    p = commands.add_parser("reconcile")
    p.add_argument("--force", action="store_true", help="强制计算全部内容哈希")
    p = commands.add_parser("search")
    p.add_argument("query")
    p.add_argument("--channel", choices=["local", "pwa", "feishu"], default="local")
    p.add_argument("--limit", type=int, default=20)
    commands.add_parser("status")
    commands.add_parser("catalog")
    commands.add_parser("audit")
    commands.add_parser("daemon")
    p = commands.add_parser("service")
    p.add_argument("action", choices=["install", "uninstall"])
    args = parser.parse_args(argv)
    home = args.home.expanduser().absolute()
    try:
        if args.command == "doctor":
            result = doctor()
        elif args.command == "init":
            result = init(home, args.test_root, args.node_id)
        elif args.command == "service":
            result = install(home) if args.action == "install" else uninstall()
        elif args.command == "daemon":
            daemon(home, emit)
            return 0
        else:
            config = load_config(home / "sources.yaml")
            with Index(home / "index.sqlite3", config) as index:
                if args.command == "reconcile":
                    result = index.reconcile(args.force)
                elif args.command == "search":
                    result = index.search(args.query, args.channel, args.limit)
                elif args.command == "catalog":
                    result = index.catalog()
                elif args.command == "audit":
                    result = {"operations": [dict(r) for r in index.db.execute(
                        "SELECT * FROM operations ORDER BY at DESC LIMIT 50")]}
                else:
                    result = index.status()
        emit(result)
        return 0
    except (OSError, ValueError, KeyError, sqlite3.Error, subprocess.SubprocessError) as exc:
        # Keep raw errors/paths/content out of persistent daemon logs.
        emit({"error": type(exc).__name__, "message": str(exc) if isinstance(exc, ValueError)
              else "本机操作失败，请检查配置、文件权限和服务状态"})
        return 1
