# Personal Asis

PA0 的 Mac 本地节点已实现：SQLite FTS5 Markdown 搜索、文档 UUID／版本、索引核对、来源权限和用户级 launchd 服务。没有模型调用或网络监听。VPS 调度、节点注册／出站轮询、ROG、PWA 与飞书接入尚未实现，整个 PA0 尚未验收。

## 本机使用

在项目根目录执行，无第三方运行依赖：

```sh
scripts/asis doctor
scripts/asis status
scripts/asis search "芯片"
scripts/asis search "inference engine" --limit 5
scripts/asis reconcile
scripts/asis audit
```

输出为 JSON。每个 Replica Group 含独立副本的 UUID、内容哈希、节点、来源与路径。本地副本另含当前原文 URI、行号、最小摘录和索引／读取时间。查询中的空白分隔词按 AND 组合，FTS 运算符按普通文本处理。

本机运行数据位于 `~/Library/Application Support/PersonalAsis/`；来源配置为其中的 `sources.yaml`，SQLite 索引和日志不进入代码目录。当前配置只读索引规格指定的 `test_for_asis/Note` 和 `test_for_asis/Daily`，两个来源的远程元数据权限都关闭。

```sh
# 在另一份本机私密运行目录中初始化；不覆盖已有配置
scripts/asis --home /ABSOLUTE/PRIVATE/RUNTIME init --test-root /ABSOLUTE/TEST/ROOT --node-id mac

# 本机服务管理
scripts/asis service install
launchctl print gui/$(id -u)/local.personal-asis.mac
scripts/asis service uninstall
```

卸载服务保留本机索引与配置。服务使用安装时的 Python 绝对路径和当前 checkout 的 `src/`；移动 checkout 或更新 Python 路径后需重新安装服务。launchd 在用户登录时启动；电脑关机、休眠或用户退出时不能提供检索。

## 依赖与验证

需要 Python 3.11+，以及支持 FTS5 trigram 的 SQLite 3.34+。`doctor` 检查实际能力。开发入口无需 pip；`pyproject.toml` 另提供可选的包安装入口。

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

更多配置、权限边界、验收结果与待办见 [Mac 实施说明](docs/pa0-mac.md)。后续开发遵循已确认的 [Agent 架构基线](docs/agent-architecture-review.md)及 [实施计划](docs/implementation-plan.md)。
