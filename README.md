# Personal Asis

当前方向：**先把本机 Pi Agent 做好**。Mac 保有会话、资料、权限、工具与共享预算，Pi 提供持续对话界面。VPS 连接、机器人交互与远程通信已归档隔离，作为下一阶段；本机开发和验收不依赖远程联调。见[当前主线与下一步](docs/local-agent-focus.md)。

```sh
scripts/asis-pi --check
scripts/asis-pi
scripts/asis-pi --continue
scripts/asis chat
scripts/asis web-chat
```

已安装的 `pi` 启动器也可使用。原生 Pi、文本 CLI 与仅绑定回环的 Web Chat 复用 Conversation Core；普通聊天直接回答，按需使用获准笔记、阅读缓存、受控公开研究或确认后的一次专业工作。当前模型返回完整响应，SSE 只提供步骤状态；长会话摘要、旧历史召回和真实个人回答质量仍待完善。

本机执行沿用已授权 MiMo Flash，允许直接调用模型及经确认的公开搜索；不要求全离线推理。Study／Life 来源原文保留原处，凭据与排除项优先，只提交问题相关的最小上下文。未知调用不自动重试，旧付费协议与共享预算保留；持续策略记录不会自行启动后台。

## 文档

- [使用指南](docs/assistant-usage.md)：Pi 会话、工具确认、恢复和清理。
- [当前本机主线](docs/local-agent-focus.md)、[完成情况](docs/project-status.md)、[实施计划](docs/implementation-plan.md)。
- [P1 受控工具](docs/conversation-tools-p1.md)、[Core API／本机 Web](docs/conversation-core-api.md)、[检索质量](docs/retrieval-quality.md)。
- [远程归档清单](docs/archive/remote-communications-20261020.md)、[下一阶段远程计划](docs/remote-communications-plan.md)、[调整前发布及渠道快照](docs/archive/project-readme-20261020.md)。
- [文档索引](docs/README.md)、[总规格](SPECIFICATION.md)、[领域术语](CONTEXT.md)、[持续授权](docs/private-data-authority.md)。

## 本机开发验证

```sh
scripts/test-local-agent
```

该套件强制阻断 VPS／机器人／Relay 模块导入，使用合成资料与模拟 Provider；不连接平台或消耗真实模型预算。完整旧兼容回归仍可单独运行：

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

仓库脚本默认 `python3`；原生 Pi 启动器默认复用既有私密 PA1 环境，可用 `ASIS_PYTHON` 指定解释器。Python 3.11+、SQLite FTS5 和固定 Pi 依赖为本机基础，可选依赖缺失须报告跳过。运行数据、配置、索引、日志与凭据不进入 Git。

本轮只修改 checkout，没有部署、停服、重启或验证当前线上状态；旧远程实现与配置保留兼容，已有未提交会话功能保留。
