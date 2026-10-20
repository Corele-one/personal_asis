# Personal Asis

个人助手由两个 Agent 协作：Mac 的原生 Pi 管理知识资料；VPS 的 AstrBot 记录生活、健康、作息与时间事项。PWA 展示两个节点的内容与最近同步状态。

```sh
pi                       # 直接打开本地原生 Pi
pi --check               # 无模型／凭据读取的配置检查
pi --plain               # 原生 Pi，不加载个人配置
pi_sync                  # Mac/VPS 同步，预览并询问是否写入日记
scripts/asis status      # 保留的本机索引工具
scripts/asis-library status # 阅读资料库的条数与采集覆盖
```

在 AstrBot 已绑定的本人私聊发送日常记录即可。`/life` 查看状态，`/life list` 查看近期记录。运行 `pi_sync` 时按北京时间归入 Life 的对应日记，显示完整修改；输入“确认写入”后执行，其他输入跳过并保留待同步内容。

Obsidian 写入先确认；WUCAI／小红书写入由 Pi 的 `source_write` 工具展示具体参数并逐次确认。支持的写入范围和限制见[使用指南](docs/assistant-usage.md)。原始笔记留在原库，VPS 只保有本人发送给 AstrBot 的生活记录，Mac 不上传整库。

文档入口：[当前架构](SPECIFICATION.md) · [使用指南](docs/assistant-usage.md) · [运行与回退](docs/operations.md) · [完成状态](docs/project-status.md) · [全部文档](docs/README.md)。

WUCAI与两个小红书账号的已采集资料可在[本机阅读资料库](docs/reading-library.md)统一检索，原文归属、账号关系和覆盖缺口分别保留；正文按需补取，不自动采集整个平台。

本项目仍保留旧本地 Core／检索／付费状态兼容。旧个人助手机器人、远程搜索 PWA、协调／Relay／轮询已退役；历史记录不能视为新架构验收。原生 Pi 和 AstrBot 不受旧 Asis Token 账本约束。

开发：Python 3.11+；原生 Pi 使用仓库固定依赖。运行 `scripts/test-local-agent`；完整回归 `PYTHONPATH=src python3 -m unittest discover -s tests -v`。真实资料、凭据与状态不入 Git。
