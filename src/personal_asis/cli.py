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
            "platform": platform.system(), "network": "local commands do not start VPS polling; legacy node/daemon commands opt in",
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
    parser = argparse.ArgumentParser(description="本机 Pi Agent、证据检索与受控分析；远程命令保留兼容")
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME, help="本机私密运行数据目录")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    p = commands.add_parser('chat', help='本机持续聊天、有限上下文及按需工具；独立于VPS和AstrBot')
    p.add_argument('--session', help='恢复已保存的conversation-v1会话')
    p.add_argument('--continue', dest='continued', action='store_true', help='恢复最近会话')
    p.add_argument('--check', action='store_true', help='检查配置和Pi依赖，不调用模型')
    p.add_argument('--list', dest='list_sessions', action='store_true', help='列出最近会话ID')
    p = commands.add_parser('web-chat', help='启动仅本机可访问的持续聊天网页')
    p.add_argument('--port', type=int, default=0, help='回环端口，默认由系统分配')
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
    p = commands.add_parser('reading', help='外部阅读来源：只读拉取、本机索引与30天缓存；不启用后台工作')
    p.add_argument('action', choices=['configure', 'activate', 'login', 'import-session', 'mcp-install', 'key', 'status', 'sync', 'fetch', 'retrieve', 'share', 'discover', 'classify', 'clean', 'forget', 'revoke'])
    p.add_argument('--fetch-body',action='store_true',help='retrieve 前通过账户只读连接器按需读取该条目；不自动分类或增加披露许可')
    p.add_argument('--for-model',action='store_true',help='retrieve 额外核对既有 MiMo 许可；不调用模型、不授予权限')
    p.add_argument('--channel',choices=['local','pwa','feishu'],default='local',help='retrieve 按目标渠道核对既有阅读许可')
    p.add_argument('--source', required=True, choices=['wucai', 'folo', 'zhihu', 'xiaohongshu', 'wechat'])
    p.add_argument('--region', choices=['cn', 'eu', 'us'], default='cn')
    p.add_argument('--folo-cli', type=Path, help='已安装的官方 folo 可执行文件的绝对路径')
    p.add_argument('--zhihu-cli', type=Path)
    p.add_argument('--xhs-binary', type=Path)
    p.add_argument('--xhs-opencli', type=Path, help='复用本人现有Chrome会话的OpenCLI入口')
    p.add_argument('--xhs-node', type=Path)
    p.add_argument('--xhs-backend', choices=['mcp','opencli'])
    p.add_argument('--xhs-endpoint', help='仅允许本机127.0.0.1的MCP地址；默认不启动服务')
    p.add_argument('--collection-id', help='知乎已确认的收藏夹URL Token')
    p.add_argument('--defer-auth', action='store_true', help='暂缓凭据及平台访问，状态检查也不读取凭据')
    p.add_argument('--url', help='用户明确提供的公众号公开分享链接')
    p.add_argument('--query', help='用户明确提供的小红书搜索词')
    p.add_argument('--followed-only', action='store_true')
    p.add_argument('--stream', choices=['subscriptions', 'selections'])
    p.add_argument('--since', help='WUCAI 起始日期 YYYY-MM-DD，自动分成最多14天的窗口')
    p.add_argument('--until', help='WUCAI 结束日期 YYYY-MM-DD；默认最近七天')
    p.add_argument('--max-pages', type=int, default=3)
    p.add_argument('--page-size', type=int, default=20)
    p.add_argument('--resume', action='store_true', help='沿用相同日期窗口／流的分页检查点')
    p.add_argument('--item-id')
    p.add_argument('--classification', choices=['normal', 'private'])
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
    p = commands.add_parser('web',help='公开Reader凭据，仅在本机终端隐藏输入')
    p.add_argument('action',choices=['key'])
    p.add_argument('--provider',choices=['jina','deepseek'],default='jina')
    p = commands.add_parser('agent', help='本机按需 Pi/MiMo、持久恢复与合成验证；不启用后台委托')
    p.add_argument('--web',action='store_true',help='新建独立 web-v1 工具会话；恢复自动沿用保存协议')
    p.add_argument('--public-query',action='append',help='单独批准的公开查询；可重复最多三条，禁止私密片段')
    p.add_argument('--web-backend',choices=['exa','deepseek'],help='仅新建 --web 会话选择检索Provider，MiMo生成模型不变')
    p.add_argument('action', choices=['validate','run','resume','status','self-test','provider-status'])
    p.add_argument('--probe',action='store_true',help='仅读取 /models 验证连接和模型列表，不调用生成接口')
    p.add_argument('--query')
    p.add_argument('--source', action='append')
    p.add_argument('--request-id')
    p.add_argument('--steps',type=int,help='本次最多新完成的步骤数；便于分步检查和恢复')
    p.add_argument('--domain',choices=['supervisor','research','career','life'],help='显式采用已确认且获准模型使用的领域目标；resume 沿用原领域')
    p.add_argument('--with-history',action='store_true',help='新领域工作检索最多两条相关委托历史；恢复沿用原快照')
    p.add_argument('--mode',choices=['auto','research','career','life','team','conversation'],help='总管按需组织专业角色；team 核对三个领域，恢复沿用原计划')
    p.add_argument('--use-context',action='store_true',help='仅专业角色使用各自已保存且获准的目标')
    p.add_argument('--role-history',action='store_true',help='配合 --use-context，每个角色检索自己的相关工作历史')
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
    p = commands.add_parser('proactive', help='为既有委托保存明确的持续工作范围；不启动后台执行器')
    p.add_argument('action',choices=['preview','authorize','status','pause','resume','cancel'])
    p.add_argument('--delegation-id',required=True)
    p.add_argument('--request-id')
    p.add_argument('--interval-hours',type=int)
    p.add_argument('--expires-days',type=int)
    p.add_argument('--token-budget',type=int)
    p.add_argument('--max-runs',type=int)
    p.add_argument('--notify-when',choices=['completion','attention','expiry','none'])
    p = commands.add_parser('retrieval-v2', help='独立本机实验协议；不切换 PA1/Agent 或调用模型')
    p.add_argument('action', choices=['rebuild', 'search', 'bundle', 'expand'])
    p.add_argument('--query')
    p.add_argument('--source', action='append')
    p.add_argument('--mode', choices=['lexical', 'semantic', 'hybrid'], default='lexical')
    p.add_argument('--provider', choices=['mimo'], help='仅过滤已有模型许可，不授予权限或调用模型')
    p.add_argument('--limit', type=int, default=20)
    p.add_argument('--max-bytes', type=int, default=6144)
    p.add_argument('--chunk-id')
    p.add_argument('--document-id')
    p.add_argument('--content-hash')
    p.add_argument('--neighbors', type=int, default=1)
    p.add_argument('--reranker-dir', type=Path, help='显式加载现有本机 Safetensors 重排模型；不下载')
    p.add_argument('--rerank-min-score', type=float, help='显式模型原始 logit 门槛；不是正确概率')
    p.add_argument('--rerank-candidates', type=int, default=40)
    p.add_argument('--quality-profile', choices=['strict-lexical-v1'])
    p.add_argument('--literal-time', action='store_true', help='仅使用显式时间范围，不把检索原文中的相对时间词解释为筛选条件')
    p.add_argument('--diagnostics-only', action='store_true', help='只输出计数、模式及降级原因，不输出问题、身份或正文')
    p = commands.add_parser('quality-answer', help='显式本机摘录质量实验；不切换普通PA1或旧付费工作')
    p.add_argument('action', choices=['inspect', 'analyze'])
    p.add_argument('--query', required=True)
    p.add_argument('--source', action='append', required=True)
    p.add_argument('--reranker-dir', type=Path, required=True)
    p.add_argument('--min-score', type=float, required=True)
    p.add_argument('--request-id')
    p.add_argument('--live', action='store_true', help='显式请求一次原MiMo模型调用，沿用共享预算；未知或失败不重做')
    args = parser.parse_args(argv)
    home = args.home.expanduser().absolute()
    try:
        if args.command == "doctor":
            result = doctor()
        elif args.command == 'chat':
            from .chat_cli import main as chat_main
            return chat_main(home, session=args.session, continued=args.continued,
                             check=args.check, list_sessions=args.list_sessions)
        elif args.command == 'web-chat':
            from .conversation_web import server as chat_server
            from .conversation import ConversationStore
            from urllib.parse import quote
            with chat_server(home, args.port) as http:
                with ConversationStore(home) as store:
                    sessions = store.sessions()
                    sid = sessions[0]['id'] if sessions else store.create()
                url=f'http://127.0.0.1:{http.server_port}/chat#session={quote(sid)}'
                print('Personal Asis 本机聊天：'+url, flush=True)
                try:
                    import webbrowser
                    webbrowser.open(url)
                except Exception:
                    pass
                try:
                    http.serve_forever()
                except KeyboardInterrupt:
                    pass
            return 0
        elif args.command == 'quality-answer':
            from .reranking import LocalCrossEncoder
            from .quality_answer import analyze, prepare
            if args.action == 'analyze' and (not args.live or not args.request_id):
                raise ValueError('quality_explicit_live_and_request_id_required')
            reranker = LocalCrossEncoder(args.reranker_dir)
            if args.action == 'inspect':
                _, _, diagnostics = prepare(home, args.query, args.source, reranker=reranker, min_score=args.min_score)
                result = {**diagnostics, 'model_generation_calls':0}
            else:
                result = analyze(home, args.query, args.source, args.request_id, reranker=reranker, min_score=args.min_score)
        elif args.command == 'retrieval-v2':
            from .config import load_pa1_config
            from .retrieval_v2 import RetrievalV2, build_bundle_v2
            encoder = None
            reranker = None
            if args.reranker_dir is not None:
                if args.action not in ('search', 'bundle') or args.rerank_min_score is None:
                    raise ValueError('reranking_requires_search_or_bundle_and_explicit_threshold')
                from .reranking import LocalCrossEncoder
                reranker = LocalCrossEncoder(args.reranker_dir)
            elif args.rerank_min_score is not None:
                raise ValueError('reranking_requires_local_model')
            quality_options = dict(reranker=reranker, min_score=args.rerank_min_score,
                                   max_rerank_candidates=args.rerank_candidates,
                                   quality_profile=args.quality_profile, infer_time_window=not args.literal_time)
            if args.mode != 'lexical' and args.action in ('search', 'bundle'):
                from .pa1 import settings, encoder_for
                encoder, _ = encoder_for(settings(home))
            if args.action == 'bundle':
                if not args.query:
                    raise ValueError('v2_query_required')
                bundle = build_bundle_v2(home, args.query, provider=args.provider or 'mimo',
                    encoder=encoder, source_ids=args.source, mode=args.mode, max_bytes=args.max_bytes,
                    **quality_options)
                result = ({'protocol': bundle.protocol, 'mode': bundle.retrieval_mode, 'coverage': bundle.coverage}
                          if args.diagnostics_only else {'cloud_input': bundle.cloud_input(home),
                              'local_evidence': bundle.evidence, 'coverage': bundle.coverage,
                              'fingerprint': bundle.fingerprint()})
            else:
                with Index(home / 'index.sqlite3', load_pa1_config(home)) as index, RetrievalV2(index) as v2:
                    if args.action == 'rebuild':
                        result = v2.sync()
                    elif args.action == 'search':
                        result = v2.search(args.query, mode=args.mode, limit=args.limit, provider=args.provider,
                                           encoder=encoder, source_ids=args.source, **quality_options)
                        if args.diagnostics_only:
                            quality = result.get('reranking')
                            retrieval_policy = result.get('retrieval_policy')
                            result = {k: result[k] for k in ('protocol', 'mode', 'requested_mode', 'degradation', 'diagnostics')}
                            # Reranking contains only a model fingerprint, policy and counts.
                            if quality is not None:
                                result['reranking'] = quality
                            if retrieval_policy is not None:
                                result['retrieval_policy'] = retrieval_policy
                    else:
                        if not all((args.chunk_id, args.document_id, args.content_hash)):
                            raise ValueError('v2_expansion_requires_versioned_identity')
                        evidence = v2.expand(args.chunk_id, args.document_id, args.content_hash,
                            neighbors=args.neighbors, max_bytes=args.max_bytes,
                            provider=args.provider, source_ids=args.source)
                        result = {'segments': len(evidence)} if args.diagnostics_only else {'evidence': evidence}
        elif args.command == 'reading':
            from . import reading
            home = home.resolve()
            if args.action == 'configure':
                result = reading.configure(home, args.source, args.region, args.folo_cli,
                    zhihu_cli=args.zhihu_cli, xhs_binary=args.xhs_binary, xhs_endpoint=args.xhs_endpoint,
                    xhs_opencli=args.xhs_opencli, xhs_node=args.xhs_node, xhs_backend=args.xhs_backend,
                    collection_id=args.collection_id, defer_auth=args.defer_auth)
            elif args.action == 'activate':
                result = reading.activate(home, args.source)
            elif args.action == 'status':
                result = reading.status(home, args.source)
            elif args.action == 'import-session':
                if args.source != 'xiaohongshu' or not sys.stdin.isatty():
                    raise ValueError('reading_session_requires_owner_terminal')
                from .xhs_credentials import import_export
                raw = getpass.getpass('小红书 Cookie-Editor Header String（不回显，仅存系统钥匙串）: ')
                result = import_export(raw)
            elif args.action == 'mcp-install':
                if args.source != 'xiaohongshu' or args.xhs_binary is None:
                    raise ValueError('reading_xhs_mcp_binary_required')
                from .xhs_service import install
                result = install(home, args.xhs_binary)
            elif args.action == 'login':
                if args.source != 'folo':
                    raise ValueError('reading_browser_login_folo_only')
                with reading.ReadingCache(home, args.source) as cache:
                    if not cache.enabled():
                        raise ValueError('reading_configure_before_login')
                from .folo_login import login
                result = login(notify=lambda message: print(message, file=sys.stderr, flush=True))
                result['access'] = reading.activate(home, args.source)
            elif args.action == 'key':
                from .credentials import CredentialStore
                if args.source == 'wechat':
                    raise ValueError('reading_wechat_no_account_credentials')
                if not sys.stdin.isatty():
                    raise ValueError('reading_key_requires_interactive_terminal')
                with reading.ReadingCache(home, args.source) as cache:
                    if not cache.enabled():
                        raise ValueError('reading_configure_before_key')
                    row = cache.db.execute("SELECT value FROM meta WHERE key='region'").fetchone()
                    account = 'wucai:' + row[0] if args.source == 'wucai' else 'xiaohongshu-mcp' if args.source == 'xiaohongshu' else args.source
                    secret = getpass.getpass('来源专用 Token（不回显，仅存系统凭据库）: ').strip()
                    if not secret or any(c.isspace() for c in secret) or (args.source == 'wucai' and not secret.startswith('wct-')):
                        raise ValueError('reading_invalid_token')
                    CredentialStore(account, 'local.personal-asis.reading').set(secret)
                result = {'credential_stored': True, 'source': args.source}
            elif args.action == 'sync':
                result = reading.sync(home, args.source, args.stream, args.since, args.until,
                                      args.max_pages, args.page_size, args.resume)
            elif args.action == 'retrieve':
                from .reading_retrieval import snapshot
                if not args.item_id or not args.query:
                    raise ValueError('reading_item_and_query_required')
                result = snapshot(home,args.source,args.item_id,args.query,fetch_body=args.fetch_body,
                                  provider='mimo' if args.for_model else None,channel=args.channel)
            elif args.action == 'fetch':
                if not args.item_id:
                    raise ValueError('reading_item_id_required')
                result = reading.fetch(home, args.source, args.item_id)
            elif args.action == 'share':
                if not args.url:
                    raise ValueError('reading_share_url_required')
                result = reading.share(home, args.source, args.url)
            elif args.action == 'discover':
                if not args.query:
                    raise ValueError('reading_discovery_query_required')
                result = reading.discover(home, args.source, args.query, args.followed_only, args.page_size)
            elif args.action == 'classify':
                if not args.item_id or not args.classification:
                    raise ValueError('reading_item_and_classification_required')
                result = reading.classify(home, args.source, args.item_id, args.classification)
            else:
                if args.action == 'forget' and not args.item_id:
                    raise ValueError('reading_item_id_required')
                result = reading.clean(home, args.source, args.action == 'revoke',
                                       args.item_id if args.action == 'forget' else None)
            emit(result)
            return 1 if result.get('status') == 'failed' else 0
        elif args.command == 'web':
            if not sys.stdin.isatty():
                raise ValueError('web_key_requires_owner_terminal')
            from .credentials import CredentialStore
            secret=getpass.getpass(args.provider+' API Key（隐藏输入，仅存Mac系统钥匙串）: ').strip()
            if not secret or not secret.isascii() or any(ord(c)<33 or ord(c)>126 for c in secret):
                raise ValueError('web_invalid_key')
            CredentialStore(args.provider,'local.personal-asis.web').set(secret)
            result={'provider':args.provider,'key_stored':True,'credential_location':'os_keychain'}
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
                               resume=args.action=='resume',step_limit=args.steps,domain=args.domain,with_history=args.with_history,mode=args.mode,use_context=args.use_context,role_history=args.role_history,
                               web=args.web,public_queries=args.public_query,web_backend=args.web_backend)
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
        elif args.command == 'proactive':
            from .work import WorkStore
            with WorkStore(home/'work.sqlite3') as work:
                if args.action=='preview':
                    if not all((args.request_id,args.interval_hours,args.expires_days,
                                args.token_budget,args.max_runs,args.notify_when)):
                        raise ValueError('proactive_preview_requires_scope_frequency_expiry_budget_runs_and_notice')
                    import time
                    result=work.prepare_proactive(args.delegation_id,request_id=args.request_id,
                        interval_seconds=args.interval_hours*3600,expires=time.time()+args.expires_days*86400,
                        token_budget=args.token_budget,max_runs=args.max_runs,notify_when=args.notify_when)
                elif args.action=='status':
                    result={'policy':work.proactive(args.delegation_id),'scheduler_started':False}
                elif args.action=='authorize':
                    print('将启用此精确范围的持续工作授权；执行器仍需单独启动。',flush=True)
                    confirmation=getpass.getpass('输入 preview 命令返回的一次性确认值：')
                    result=work.control_proactive(args.delegation_id,'authorize',confirmation_token=confirmation)
                else:
                    result=work.control_proactive(args.delegation_id,args.action)
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
            from .service import install, uninstall
            result = install(home) if args.action == "install" else uninstall()
        elif args.command == "tunnel":
            from .service import install_tunnel, uninstall_tunnel
            if args.action == "install":
                if not args.host:
                    raise ValueError("需要 --host user@hostname")
                result = install_tunnel(home, args.host, args.ssh_port, args.local_port, args.remote_port)
            else:
                result = uninstall_tunnel()
        elif args.command == "daemon":
            from .service import daemon
            daemon(home, emit)
            return 0
        elif args.command == "node":
            from .node import Client, Poller, connection_config
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
            from .pwa import server as pwa_server, settings as pwa_settings
            from .web_auth import WebAuth
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
            from .feishu import FeishuBridge
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
            from .coordinator import Coordinator
            path = home / "coordinator.sqlite3"
            if args.action == "serve":
                from .transport import server
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
