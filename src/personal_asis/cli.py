import argparse
import getpass
import importlib.util
import json
import os
from pathlib import Path
import platform
import sqlite3
import shutil
import subprocess
import sys

from .config import DEFAULT_HOME, load_config
from .index import Index
from .service import daemon, install, uninstall, install_tunnel, uninstall_tunnel
from .coordinator import Coordinator
from .node import Client, Poller, connection_config
from .transport import server
from .feishu import FeishuBridge
from .pwa import server as pwa_server, settings as pwa_settings
from .web_auth import WebAuth
from .extractors import FORMATS


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
            "platform": platform.system(), "network": "outbound polling when coordinator.json is configured",
            "text_formats": list(FORMATS),
            "pdf_text_backend": "pdftotext" if shutil.which("pdftotext") else "pypdf" if importlib.util.find_spec("pypdf") else None,
            "legacy_office_converter": bool(shutil.which("libreoffice") and shutil.which("unshare") and Path("/usr/lib/python3/dist-packages/uno.py").exists()),
            "encrypted_backup": bool(importlib.util.find_spec("cryptography")),
            "encrypted_reader": bool(importlib.util.find_spec("cryptography"))}


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
    parser = argparse.ArgumentParser(description="PA0 纯文本证据检索与节点协调")
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
    p = commands.add_parser("backup", help="加密备份／恢复本机状态；不含原文和系统凭据")
    p.add_argument("action", choices=["create", "restore", "recovery-key"])
    p.add_argument("--target", type=Path)
    p.add_argument("--archive", type=Path)
    p.add_argument("--node-id", help="使用本机凭据库中指定节点的备份密钥")
    p.add_argument("--use-recovery-key", action="store_true", help="隐藏输入离线恢复密钥，不放在命令参数中")
    p = commands.add_parser("service")
    p.add_argument("action", choices=["install", "uninstall"])
    p = commands.add_parser("tunnel", help="Mac／WSL 常驻 SSH 回环隧道")
    p.add_argument("action", choices=["install", "uninstall"])
    p.add_argument("--host")
    p.add_argument("--ssh-port", type=int, default=22)
    p.add_argument("--local-port", type=int, default=18765)
    p.add_argument("--remote-port", type=int, default=8765)
    p = commands.add_parser("node")
    p.add_argument("action", choices=["enroll", "poll"])
    p = commands.add_parser("coordinator", help="协调服务本机管理；不提供公网管理接口")
    p.add_argument("action", choices=["serve", "pair", "submit", "task", "audit", "revoke", "enable", "disable"])
    p.add_argument("--nodes", nargs="+", default=["mac"])
    p.add_argument("--node-id")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--query")
    p.add_argument("--channel", choices=["pwa", "feishu"], default="pwa")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--request-id", help="调用方保存的幂等键")
    p.add_argument("--task-id")
    p = commands.add_parser("feishu", help="服务器本机飞书绑定与通知状态管理")
    p.add_argument("action", choices=["pair", "audit"])
    p.add_argument("--platform-id")
    p = commands.add_parser("pwa", help="私有 PWA 服务和一次性用户设置")
    p.add_argument("action", choices=["serve", "bootstrap"])
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--reset", action="store_true", help="重设 Web 用户并撤销全部 Web 会话")
    args = parser.parse_args(argv)
    home = args.home.expanduser().absolute()
    try:
        if args.command == "doctor":
            result = doctor()
        elif args.command == "backup":
            from .backup import create as create_backup, restore as restore_backup, key_store
            if args.action == "create":
                if args.target is None:
                    raise ValueError("需要 --target 指定用户控制的备份目录")
                result = create_backup(home, args.target.expanduser().absolute())
            else:
                node_id = args.node_id
                if not node_id and not args.use_recovery_key:
                    node_id = load_config(home / "sources.yaml").node_id
                if args.action == "recovery-key":
                    if not sys.stdout.isatty():
                        raise ValueError("恢复密钥只允许在本机交互终端查看，请离线妥善保存")
                    result = {"recovery_key": key_store(node_id).get()}
                else:
                    if args.target is None or args.archive is None:
                        raise ValueError("需要 --archive 和空目录 --target")
                    result = restore_backup(args.archive.expanduser().absolute(), args.target.expanduser().absolute(),
                        store=key_store(node_id) if node_id else None,
                        recovery_key=getpass.getpass("离线恢复密钥（不回显）: ") if args.use_recovery_key else None)
        elif args.command == "init":
            result = init(home, args.test_root, args.node_id)
        elif args.command == "service":
            result = install(home) if args.action == "install" else uninstall()
        elif args.command == "tunnel":
            if args.action == "install":
                if not args.host:
                    raise ValueError("需要 --host user@hostname")
                result = install_tunnel(home, args.host, args.ssh_port, args.local_port, args.remote_port)
            else:
                result = uninstall_tunnel()
        elif args.command == "daemon":
            daemon(home, emit)
            return 0
        elif args.command == "node":
            if args.action == "enroll":
                config = load_config(home / "sources.yaml")
                client = Client(connection_config(home), config.node_id)
                result = client.enroll(getpass.getpass("一次性配对码（不回显）: "))
            else:
                poller = Poller(home)
                try:
                    result = poller.once()
                finally:
                    poller.close()
        elif args.command == "pwa":
            config = pwa_settings(home)
            if args.action == "serve":
                with pwa_server(home, args.port) as http:
                    emit({"event": "pwa_listening", "host": "127.0.0.1", "port": http.server_port})
                    try:
                        http.serve_forever()
                    except KeyboardInterrupt:
                        pass
                return 0
            with WebAuth(home, otp_required=config["auth_method"] == "password_totp") as auth:
                setup = auth.bootstrap(args.reset)
            result = {"setup_url": config["origin"] + "/#setup=" + setup["setup_token"], "expires_in": setup["expires_in"]}
        elif args.command == "feishu":
            bridge = FeishuBridge(home)
            try:
                if args.action == "pair":
                    if not args.platform_id:
                        raise ValueError("需要 --platform-id")
                    result = bridge.pairing(args.platform_id)
                else:
                    result = {"bound": bool(bridge.db.execute("SELECT open_id FROM binding WHERE singleton=1").fetchone()[0]),
                              "deliveries": [dict(r) for r in bridge.db.execute("SELECT * FROM deliveries ORDER BY created DESC LIMIT 50")]}
            finally:
                bridge.close()
        elif args.command == "coordinator":
            path = home / "coordinator.sqlite3"
            if args.action == "serve":
                with server(path, args.port, tuple(args.nodes)) as http:
                    emit({"event": "listening", "host": "127.0.0.1", "port": http.server_port,
                          "node_api_only": True})
                    try:
                        http.serve_forever()
                    except KeyboardInterrupt:
                        pass
                return 0
            with Coordinator(path, tuple(args.nodes)) as coordinator:
                if args.action in {"pair", "revoke", "enable", "disable"}:
                    if not args.node_id:
                        raise ValueError("需要 --node-id")
                    if args.action in {"enable", "disable"}:
                        result = coordinator.set_enabled(args.node_id, args.action == "enable")
                    else:
                        result = (coordinator.pair(args.node_id) if args.action == "pair"
                                  else coordinator.revoke(args.node_id))
                elif args.action == "submit":
                    if not args.query or not args.request_id:
                        raise ValueError("需要 --query 和持久化的 --request-id")
                    result = coordinator.submit(args.query, args.channel, args.limit, args.request_id)
                elif args.action == "task":
                    result = coordinator.view(args.task_id)
                else:
                    result = coordinator.audit()
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
