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
    parser = argparse.ArgumentParser(description="本机证据检索、节点协调与受控 PA1 分析")
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
    p = commands.add_parser("pa1", help="本机最小上下文、MiMo 与预算；默认仅合成联调")
    p.add_argument("action", choices=["init", "configure", "authorize", "revoke", "clean", "key", "models", "retrieve", "bundle", "analyze", "research", "channel-worker", "channel-install", "budget", "self-test", "semantic-test"])
    p.add_argument('--public-query',help='明确公开的检索词，仅此外发给搜索服务')
    p.add_argument('--url',action='append',default=[],help='公开HTTPS原始证据链接，最多三条')
    p.add_argument("--query")
    p.add_argument("--model")
    p.add_argument("--enable", action="store_true")
    p.add_argument("--disable", action="store_true")
    p.add_argument("--semantic-model-dir", type=Path, help="预先准备好的本机模型目录；检索不下载")
    p.add_argument("--semantic-query-prefix")
    p.add_argument("--semantic-document-prefix")
    p.add_argument("--disable-semantic", action="store_true")
    p.add_argument("--source", action="append", help="筛选或授权的已有来源 ID，可重复")
    p.add_argument("--all-current-files", action="store_true", help="仅许可当前已索引且版本有效的文件")
    p.add_argument("--all-source-files", action="store_true", help="许可指定已有来源下的全部文件，含后续新增路径；排除规则仍优先")
    p.add_argument("--include-private", action="store_true", help="单独许可指定来源中的私密资料进入当前提供商")
    p.add_argument("--allow-real-sources", action="store_true", help="解除合成限制，逐文件许可仍生效")
    p.add_argument("--synthetic-only", action="store_true", help="恢复仅合成资料限制")
    p.add_argument("--live", action="store_true", help="合成资料真实 API 联调；需显式请求编号")
    p.add_argument("--request-id")
    p = commands.add_parser('agent', help='本机按需 Pi/MiMo、持久恢复与合成验证；不启用后台委托')
    p.add_argument('action', choices=['validate','run','resume','status','self-test','provider-status'])
    p.add_argument('--probe',action='store_true',help='仅读取 /models 验证连接和模型列表，不调用生成接口')
    p.add_argument('--query')
    p.add_argument('--source', action='append')
    p.add_argument('--request-id')
    p.add_argument('--steps',type=int,help='本次最多新完成的步骤数；便于分步检查和恢复')
    p.add_argument('--domain',choices=['supervisor','research','career','life'],help='显式采用已确认且获准模型使用的领域目标；resume 沿用原领域')
    p.add_argument('--with-history',action='store_true',help='新领域工作检索最多两条相关委托历史；恢复沿用原快照')
    p.add_argument('--mode',choices=['auto','research','career','life','team','conversation'],help='总管按需组织专业角色；team 核对三个领域，恢复沿用原计划')
    p = commands.add_parser('domain', help='本人明确配置的领域目标／约束；不自动推断、调度或授权资料')
    p.add_argument('action',choices=['set','show','list','forget','history'])
    p.add_argument('--domain',choices=['supervisor','research','career','life'])
    p.add_argument('--goal')
    p.add_argument('--query',help='本机历史检索词；history 必填，不调用模型')
    p.add_argument('--constraints',default='')
    p.add_argument('--source',action='append')
    p.add_argument('--request-id')
    p.add_argument('--allow-model',action='store_true',help='明确许可本条目标／约束供既有 MiMo 使用；默认仅本机保存')
    p = commands.add_parser('work', help='仅本机委托状态管理；不自动调度或授予来源权限')
    p.add_argument('action', choices=['create', 'list', 'show', 'enqueue', 'pause', 'resume', 'cancel',
                                     'stop-run', 'executions', 'resolve', 'clear-results'])
    p.add_argument('--delegation-id')
    p.add_argument('--run-id')
    p.add_argument('--request-id')
    p.add_argument('--goal')
    p.add_argument('--source', action='append')
    p.add_argument('--role', choices=['supervisor', 'research', 'career', 'life'], default='supervisor')
    p.add_argument('--parent-run')
    p.add_argument('--priority', choices=['foreground', 'background'], default='foreground')
    p.add_argument('--execution-key')
    p.add_argument('--outcome', choices=['done', 'rejected'])
    args = parser.parse_args(argv)
    home = args.home.expanduser().absolute()
    try:
        if args.command == "doctor":
            result = doctor()
        elif args.command == 'agent':
            if args.action=='validate':
                from .runtime_validation import validate
                result = validate()
                emit(result)
                return 0 if result['passed'] and all(result['checks'].values()) else 1
            from .agent import execute, inspect, live_self_test, provider_status
            if args.action=='provider-status':
                result=provider_status(home,args.probe)
                emit(result)
                return 0
            if not args.request_id:
                raise ValueError('agent_request_id_required_max_96')
            if args.action=='status':
                result=inspect(home,args.request_id)
            elif args.action=='self-test':
                result=live_self_test(home,args.request_id,args.steps)
            else:
                result=execute(home,args.query,args.request_id,args.source,
                               resume=args.action=='resume',step_limit=args.steps,domain=args.domain,with_history=args.with_history,mode=args.mode)
        elif args.command=='domain':
            from .domain_context import DomainContexts
            if args.action!='list' and not args.domain:
                raise ValueError('domain_context_domain_required')
            with DomainContexts(home) as contexts:
                if args.action=='set':
                    result=contexts.set(args.domain,args.goal,args.constraints,args.source,args.request_id,allow_model=args.allow_model)
                elif args.action=='forget':
                    result=contexts.forget(args.domain,args.request_id)
                elif args.action=='show':
                    result=contexts.show(args.domain)
                elif args.action=='history':
                    from .work_history import retrieve_history
                    result={'records':retrieve_history(home,args.domain,args.query,args.source),
                            'coverage':'up_to_two_matches_from_latest_200_completed_runs',
                            'model_called':False}
                else:
                    result={'contexts':contexts.list(),'automatic_execution':False}
        elif args.command == 'work':
            from .work import WorkStore
            if args.action == 'create':
                if not args.goal or not args.request_id or not args.source:
                    raise ValueError('work_create_requires_goal_sources_and_request_id')
                config = load_config(home/'sources.yaml')
                if set(args.source) - {source.id for source in config.sources}:
                    raise ValueError('work_source_not_configured')
            elif args.action not in ('list', 'stop-run', 'executions', 'resolve') and not args.delegation_id:
                raise ValueError('work_delegation_id_required')
            if args.action in ('stop-run', 'executions', 'resolve') and not args.run_id:
                raise ValueError('work_run_id_required')
            with WorkStore(home/'work.sqlite3') as work:
                if args.action == 'create':
                    did = work.create(args.request_id, config.node_id, args.goal, args.source)
                    result = {'delegation_id': did, 'automatic_execution': False}
                elif args.action == 'list':
                    result = {'delegations': work.list(), 'automatic_execution': False}
                elif args.action == 'show':
                    from .agent import clean_sessions
                    clean_sessions(home)
                    result = work.view(args.delegation_id)
                elif args.action == 'enqueue':
                    result = {'run_id': work.enqueue(args.delegation_id, args.request_id, args.role,
                                                    args.parent_run, args.priority), 'automatic_execution': False}
                elif args.action == 'executions':
                    result = {'executions': work.executions(args.run_id)}
                else:
                    if args.action == 'stop-run':
                        work.stop_run(args.run_id)
                    elif args.action == 'resolve':
                        work.resolve(args.run_id, args.execution_key, args.outcome)
                    elif args.action == 'clear-results':
                        work.clean(args.delegation_id)
                    else:
                        work.control(args.delegation_id, args.action)
                    result = {'updated': True, 'action': args.action, 'automatic_execution': False}
        elif args.command == "pa1":
            from . import pa1
            from .config import load_pa1_config
            from .model_provider import MiMo
            from .credentials import CredentialStore
            from .retrieval import retrieve, build_bundle
            if args.action in {"init", "configure"}:
                if args.enable and args.disable:
                    raise ValueError("enable_disable_are_mutually_exclusive")
                if args.allow_real_sources and args.synthetic_only:
                    raise ValueError('real_synthetic_are_mutually_exclusive')
                result = pa1.configure(home, args.model, True if args.enable else False if args.disable else None,
                                       args.semantic_model_dir, args.semantic_query_prefix,
                                       args.semantic_document_prefix, args.disable_semantic,
                                       False if args.allow_real_sources else True if args.synthetic_only else None)
            else:
                data = pa1.settings(home)
                config = load_pa1_config(home)
                if args.action == 'authorize':
                    if not args.source or args.all_current_files==args.all_source_files:
                        raise ValueError('authorization_requires_sources_and_all_current_files')
                    result=pa1.authorize_current_files(home,args.source,args.include_private,args.all_source_files)
                elif args.action == 'revoke':
                    result=pa1.revoke_sources(home,args.source)
                elif args.action == 'clean':
                    from .pa1_maintenance import clean
                    result=clean(home)
                elif args.action == "key":
                    if not sys.stdin.isatty():
                        raise ValueError("model_key_requires_local_interactive_terminal")
                    secret = getpass.getpass("MiMo API Key（隐藏输入，不保存到配置）: ")
                    if not secret or not secret.isascii() or any(ord(c)<33 or ord(c)>126 for c in secret):
                        raise ValueError("invalid_mimo_credential")
                    CredentialStore(config.node_id+":mimo", service="local.personal-asis.model").set(secret)
                    result = {"credential_saved": True, "store": "system_credential_store"}
                elif args.action == "models":
                    result = {"models": MiMo(config.node_id, data["model"] or "unconfigured").models()}
                elif args.action == "budget":
                    ledger = pa1.budget(home, config.node_id, data)
                    try:
                        result = ledger.status()
                    finally:
                        ledger.close()
                elif args.action == "self-test":
                    result = pa1.self_test(home, args.live, args.request_id)
                elif args.action == 'semantic-test':
                    from .semantic_acceptance import run
                    encoder,degradation=pa1.encoder_for(data)
                    if encoder is None:
                        raise ValueError(degradation)
                    result=run(encoder)
                    emit(result)
                    return 0 if result['passed'] else 1
                elif args.action=='channel-install':
                    from .service import install_analysis
                    result=install_analysis(home)
                elif args.action == 'channel-worker':
                    from .analysis_channel import serve_worker
                    serve_worker(home,emit)
                    return 0
                elif args.action in ('analyze','research'):
                    if not args.query or not args.request_id:
                        raise ValueError("analysis_requires_query_and_request_id")
                    if args.action=='research' and not args.public_query:
                        raise ValueError('research_requires_explicit_public_query')
                    research={'public_query':args.public_query,'urls':args.url} if args.action=='research' else None
                    result = pa1.analyze(home, args.query, args.request_id, source_ids=args.source,research=research)
                elif args.action == "bundle":
                    if not args.query:
                        raise ValueError("bundle_requires_query")
                    encoder, degradation = pa1.encoder_for(data)
                    bundle = build_bundle(home, args.query, data["provider"], encoder, args.source)
                    result = {"provider": bundle.provider, "retrieval_mode": bundle.retrieval_mode,
                              "degradation": degradation or bundle.degradation, "cloud_input": bundle.cloud_input(),
                              "local_evidence": bundle.evidence}
                else:
                    if not args.query:
                        raise ValueError("retrieval_requires_query")
                    encoder, degradation = pa1.encoder_for(data)
                    with Index(home / "index.sqlite3", config) as index:
                        result = retrieve(index, args.query, encoder=encoder, source_ids=args.source)
                        result['degradation'] = degradation or result['degradation']
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
