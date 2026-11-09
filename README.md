# Personal Asis

个人助手的三个入口独立运行：Mac 使用原生 Pi 管理本地知识，飞书使用 AstrBot 进行日常交流与生活记录，iPhone 使用 Alma 在 VPS 上执行工作。PWA 提供私人 Dashboard／Overview；`pi_sync` 负责获准资料副本交换和需要确认的日记同步。

| 入口 | 主要职责 | 使用入口 |
|---|---|---|
| Mac Pi | 本地 Obsidian Study／Life、五彩与小红书资料，生成成果及经确认写入 | 本机 `pi` |
| 飞书 Chat | 交流、资料查询、主动随记、习惯／学习、提醒与简报 | 已绑定的本人私聊 |
| Alma Work | 在 VPS 处理工作文件、运行命令、编写代码与生成成果 | 已配对的 iPhone Alma |
| 私人 PWA | 总览、生活与学习详情、记录纠正和最近同步状态 | `/overview`、`/dashboard` |

Chat 与 Work 分别管理模型、会话、发布及回退。飞书可以建议切到 Work，由本人主动开始；不自动派单或复制当前聊天。Alma 不连接或控制 Mac，Mac 离线不影响 VPS 基本使用。

## 当前进展

以下为 **2026-11-09** 的实施与验收快照；详细范围和证据见[当前状态](docs/project-status.md)与[计划看板](docs/plans/README.md)。

| 范围 | 已交付 | 仍待完成或验收 |
|---|---|---|
| Chat C0–C1 | 删除催睡、隔离后台执行历史、按入口供应生活写工具；保留 Router 修复 | 真人自然使用和正常定时投递持续验收 |
| Chat C2／C7首批 | 按日期／来源查资料、稳定游标与版本绑定正文分页；独立 Overview，原 Dashboard 保留 | 共享长期记忆、Journal／日历管理及轨迹面板 |
| 2A：Work W0–W1 | 官方 Alma Server 0.4.530 独立部署、手机配对；本人创建并读回 VPS 文件通过，独立启停与重启持久化通过 | 长期常驻、并发／复杂负载、Mac 实际关机场景 |
| Work 模型与易用性 | MiMo／DeepSeek 可选，默认 MiMo；普通需求自动使用默认工作区，工具／技能／子任务开放；两家真实工具任务通过 | W4 的完整模态、思考档、取消及未知结果防重验收 |
| Work 上下文 | 两家原生模型容量已修正为 1,000,000 token；超过旧 32K 的连续上下文四次合成回查通过 | 不是完整 1M 满载质量／性能证明，不自动展开既有压缩历史 |
| 2B：共用记忆 | 独立 Mem0 2.2.1 SDK 合成试点与既有 Google embedding 验证 | M1语义、并发修订／撤回、鉴权与常驻资源；尚未启用正式服务或自动抽取 |

Work 的资料工具、共享记忆、PWA 状态与轨迹接入仍按 W2–W6 逐批实施。两端后续接入同一个 Mem0 权威实例，不各建一套个人记忆。

## 日常使用

```sh
pi                           # 打开本地原生 Pi，不触发同步
pi --check                   # 无模型／凭据读取的配置检查
pi --plain                   # 原生 Pi，不加载个人配置
pi_sync                      # 预览日记；刷新本机来源；交换共享库增量
scripts/alma-work status     # 查看独立 Work 状态
scripts/asis status          # 兼容的本机索引状态
scripts/asis-library status  # 阅读资料库条数与采集覆盖
```

**飞书**：普通聊天保留为对话记忆。只有 `/life` 主动提交的正文可以进入日记；`/life list` 查看近期记录。习惯／学习依据本人明确自述整理，缺记录不等于没发生。催睡已移除，明确事项提醒及低频简报保留。见[使用指南](docs/assistant-usage.md)、[习惯与学习](docs/habits-learning.md)。

**Alma**：配对后直接说需求即可，无须说“在 VPS Work 中”、点名 Bash 或手工选择 Project。Alma 图标入口绑定固定主对话，普通 Chat 可按主题另开；Project 用于组织工作目录、文件和配置。默认工作区已自动配置，普通文件／终端操作直接执行。模型列表提供 **MiMo 2.6 Flash** 与 **DeepSeek V4 Flash**，工具选择模型复用 MiMo。见[Work 使用与运维](docs/alma-work.md)。

**PWA**：Overview 显示各来源的观测时间与状态，Dashboard 保留生活、Habits、学习历史与“纠正这条”。Work／共享记忆未接入时明确标注，不阻塞 Chat 看板；Mac 上次检查不当作实时在线。见[用户纠正](docs/human-feedback.md)。

## 资料、同步与确认

- 原始 Study／Life 笔记保留 Mac。获准笔记文本、五彩划线批注与分账号小红书采集内容，经两端 SQLite 副本和固定 SSH 接口增量交换；原附件、Cookie、凭据与完整会话不进入共享库。来源正文、版本和读取覆盖分别保留。见[共享资料库](docs/shared-library.md)、[阅读资料库](docs/reading-library.md)。
- `pi_sync` 完整预览日记改动，只有精确输入 **“确认写入”** 才保存；回车跳过日记仍可继续资料刷新／共享库同步。主动生活随记按日归入 Freewrite，习惯与学习归原栏目，手写内容保留。确认框可提出编排建议，重新预览后再确认。见[同步指南](docs/daily-sync.md)。
- 个人背景候选另行预览，以 **“确认更新背景”** 发布，不与日记确认混用。五彩／小红书具体写入走 Pi 原生 `source_write` 确认；日历继续逐次展示提案并确认。Work 常规工具自动执行不撤销这些业务写入要求。
- VPS 的[五彩官方 CLI／剪藏全文读取](docs/wucai-cli.md)沿用已批准的窄账号授权，快照、划线和完整保存正文分别报告；尚未读完正文不冒称全文。

原始资料、密钥、会话、数据库、日志和私密回退不进入 Git。合成测试与脱敏验收可提交。旧 Core／检索／付费状态仅保留显式兼容；旧协调、轮询、搜索 PWA 和助手插件已退役。

## 文档与开发

[总规格](SPECIFICATION.md) · [领域词汇](CONTEXT.md) · [当前状态](docs/project-status.md) · [Chat／Work／共用计划](docs/plans/README.md) · [运行与回退](docs/operations.md) · [全部文档](docs/README.md)

近期 Work 证据：[部署／手机验收](docs/validation/alma-work-w01-20261109.json) · [易用性／双模型](docs/validation/alma-usability-models-20261109.json) · [上下文修正](docs/validation/alma-context-20261109.json)。合成、原生 API／SDK、真实模型、服务及本人手机验收分别记录，不能互相替代。

开发使用 Python 3.11+，原生 Pi 使用仓库固定依赖；Work 服务使用官方包内 Node 及 VPS 独立身份，不安装到 AstrBot 环境。项目规则先读 [AGENT.md](AGENT.md)。

```sh
scripts/test-local-agent
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
