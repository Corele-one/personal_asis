# Personal Asis

Mac 索引、VPS 协调、飞书私聊与 [IP HTTPS PWA](https://35.209.202.207/) 已部署。已验证真实用户登录／搜索、节点轮询及消息回执。当前仅有 Study／Life 两个来源，索引 446 个 Markdown；仅展示明确获准的元数据，没有正文导出或模型调用。ROG、完整证据传输与加密备份仍待完成，完整 PA0 未验收。见 [PWA 说明](docs/pa0-pwa.md)、[协调](docs/pa0-coordinator.md) 和 [飞书](docs/pa0-feishu.md)。

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

本机运行数据位于 `~/Library/Application Support/PersonalAsis/`；配置、索引和审计不进入代码目录。当前只读索引用户授权的 Study（267 个）及 Life（179 个）Markdown。Study 非私密元数据获准远程展示，Life 保持 private，另以明确的 `private_remote_metadata` 许可显示其私密元数据；正文、摘录和模型处理不因此开放。旧 Note／Daily 测试来源已从配置和索引移除，磁盘原文件保留。

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

更多配置、权限边界、验收结果与待办见 [Mac 实施说明](docs/pa0-mac.md) 和 [协调服务说明](docs/pa0-coordinator.md)。后续开发遵循已确认的 [Agent 架构基线](docs/agent-architecture-review.md)及 [实施计划](docs/implementation-plan.md)。
