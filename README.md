# Personal Asis

2026-10-14 用户明确选择只用 Mac 检索、停用 ROG。生产检索节点仅为 `mac`，索引 Study 267 个及 Life 181 个 Markdown；VPS 协调、飞书和 IP HTTPS PWA 继续使用。ROG 的后台索引、SSH 隧道及 Windows 开机任务停用，服务器停用其节点并撤出新旧搜索范围，保留原文件、3,309 个本机文档索引及 F 盘加密备份。非私密 PWA 摘录／正文按用户授权加密中转，VPS 不保存明文；私密正文和模型处理继续关闭。先前双设备副本、离线恢复和两端阅读验证保留为历史能力记录，不再把维护 ROG 作为当前 PA0 交付条件。Mac 本机备份恢复已验证，复制到 F 盘的操作未完成并已停止。详见 [Mac 单节点运行](docs/pa0-mac-only.md)、[文本与恢复](docs/pa0-text.md)及 [历史 ROG 记录](docs/pa0-rog.md)。

## 当前入口

日常使用 [PWA](https://35.209.202.207/) 或飞书，仅检索 Mac。Mac 休眠／关机时新搜索等待其恢复，正文阅读需要 Mac 在线。ROG 的以下 CLI 能力仅作为保留配置，后台已停用；恢复步骤见 [单节点记录](docs/pa0-mac-only.md)。

## 本机使用

PA0 已按 Mac 单节点范围完成七项功能验收和真实手动休眠／自动恢复。独立备份副本和恢复密钥按用户选择暂缓；PA1 尚未启用。见 [PA0 单节点验收](docs/pa0-acceptance.md)。

在项目根目录执行；基础 Markdown／协调使用标准库，PDF／Office 和加密能力的可选依赖见 [文本说明](docs/pa0-text.md)：

```sh
scripts/asis doctor
scripts/asis status
scripts/asis search "芯片"
scripts/asis search "inference engine" --limit 5
scripts/asis reconcile
scripts/asis audit
```

输出为 JSON。每个 Replica Group 含独立副本的 UUID、内容哈希、节点、来源与路径。本地副本另含当前原文 URI、行号或页／段落／幻灯片／单元格定位、最小摘录和索引／读取时间。查询中的空白分隔词按 AND 组合，FTS 运算符按普通文本处理。

Mac 运行数据位于 `~/Library/Application Support/PersonalAsis/`；Linux／WSL 默认位于 `~/.local/share/personal-asis/`（支持 `XDG_DATA_HOME`）。配置、索引和审计不进入代码目录。Mac 只读索引 Study（267 个）及 Life（181 个）Markdown；ROG 配置和命令见 [ROG 说明](docs/pa0-rog.md)。Study 非私密元数据获准远程展示，Life 保持 private，另以明确的 `private_remote_metadata` 许可显示其私密元数据；私密正文和模型处理不因此开放。非私密条目另按 `remote_evidence` 及元数据许可提供 PWA 按需加密阅读。旧 Note／Daily 测试来源已从配置和索引移除，磁盘原文件保留。

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

需要 Python 3.11+，以及支持 FTS5 trigram 的 SQLite 3.34+。`doctor` 检查实际能力。基础开发入口无需 pip；扩展格式及加密阅读／备份按需安装可选依赖；`pyproject.toml` 另提供可选的包安装入口。

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

更多配置、权限边界、验收结果与待办见 [Mac 实施说明](docs/pa0-mac.md) 和 [协调服务说明](docs/pa0-coordinator.md)。后续开发遵循已确认的 [Agent 架构基线](docs/agent-architecture-review.md)及 [实施计划](docs/implementation-plan.md)。
