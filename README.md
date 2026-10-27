# Personal Asis

2026-10-26新增[习惯、具体学习与持续跟进](docs/habits-learning.md)：飞书记录、VPS保存、Dashboard按日查看，`pi_sync`确认后写入Life当日日记Habits／Learning；支持低频早间简报和周一周报。

个人助手由两个 Agent 协作：Mac 的原生 Pi 管理知识资料；VPS 的 AstrBot 记录生活、健康、作息与时间事项。PWA 展示两个节点的内容与最近同步状态。

```sh
pi                       # 直接打开本地原生 Pi
pi --check               # 无模型／凭据读取的配置检查
pi --plain               # 原生 Pi，不加载个人配置
pi_sync                  # VPS记录 → Mac；刷新本机来源；双向交换共享库增量
scripts/asis status      # 保留的本机索引工具
scripts/asis-library status # 阅读资料库的条数与采集覆盖
```

在 AstrBot 已绑定的本人私聊发送日常记录即可。`/life` 查看状态，`/life list` 查看近期记录。普通聊天继续保存为助手记忆；只有 `/life` 主动提交的内容可以进入日记。`pi_sync` 将主动记录的生活自述放入当日日记Freewrite的 `---` 上方，结合当天文字衔接相关段落、沿用已有主题，独立话题才补具体H4，按自然段落保留原话，分节符前空一行，不进入卡片，也不在日记保留 `astrbot:…` 同步标记；问候、命令、日期碎片、提醒与作息回执略过，习惯与学习归各自栏目。按日期预览完整段落，输入“确认写入”后执行，回车暂不写入，`d` 查看原始 diff。旧副本清理与Freewrite迁移也会先预览确认。

`pi_sync` 同时检查VPS已批准的本人背景与已引用来源变化。有新背景候选时显示完整预览，输入“确认更新背景”才发布，与日记确认分别生效；不自动生成或改写记忆。精选背景和共享资料库分别管理。见[同步指南](docs/daily-sync.md)。

2026-10-26本人进一步选择[共享资料库](docs/shared-library.md)：`pi_sync`刷新Life／Study笔记索引、五彩和分账号小红书已采集资料，通过SSH在两份SQLite间交换获准文本及生活记录增量。VPS可按问题检索，补充单独保存；原始附件、凭据、会话和绝对路径不传，原笔记写入仍须预览确认。该选择替代此前仅上传背景摘要的限制。

Obsidian 写入先确认；WUCAI／小红书写入由 Pi 的 `source_write` 工具展示具体参数并逐次确认。支持的写入范围和限制见[使用指南](docs/assistant-usage.md)。原库保留，VPS保有生活记录、已批准背景及获准共享文本副本，来源凭据仍只在Mac。

文档入口：[当前架构](SPECIFICATION.md) · [使用指南](docs/assistant-usage.md) · [运行与回退](docs/operations.md) · [完成状态](docs/project-status.md) · [全部文档](docs/README.md)。

WUCAI与两个小红书账号的已采集资料可在[本机阅读资料库](docs/reading-library.md)统一检索，原文归属、账号关系和覆盖缺口分别保留；正文按需补取，不自动采集整个平台。

本项目仍保留旧本地 Core／检索／付费状态兼容。旧个人助手机器人、远程搜索 PWA、协调／Relay／轮询已退役；历史记录不能视为新架构验收。原生 Pi 和 AstrBot 不受旧 Asis Token 账本约束。

开发：Python 3.11+；原生 Pi 使用仓库固定依赖。运行 `scripts/test-local-agent`；完整回归 `PYTHONPATH=src python3 -m unittest discover -s tests -v`。真实资料、凭据与状态不入 Git。

PWA支持“纠正这条”进入AstrBot对话，修改误判的生活／习惯／学习整理并查看前后结果，原始消息保留；见[用户纠正](docs/human-feedback.md)。
