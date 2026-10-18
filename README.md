# Personal Asis

**已部署可按需使用的助手，完整实施计划尚未完成。** 2026-10-18 只读核对：Mac／VPS 当前发布为 `retrieval-v2-de593bc25486b7cc`，支持本机资料检索／阅读、MiMo 分析与公开研究、串行专业角色及本人 PWA／飞书。WUCAI、Folo、小红书已有真实读取和本机缓存，完整性与许可分别记录。新增 [Retrieval V2](docs/retrieval-v2.md) 独立本机实验接口、39 题评测及 Chunk／预算上下文基础闭环；显式飞书实验命令已部署，**普通 PA1／Agent 检索仍保持原协议**。逐项状态见[项目完成情况](docs/project-status.md)与[实施计划](docs/implementation-plan.md)。

PA0 已按 Mac 单节点范围验收；VPS 负责协调和渠道入口，ROG 停用。2026-10-14 验收时索引 Study 267 篇、Life 181 篇，共 448 篇 Markdown；这不是实时来源数量。独立备份和恢复密钥按用户选择暂缓，整机重启未验。

## 使用入口

V2 只读实验：本人已绑定飞书私聊发送 `/asis retrieve-v2 study | 缓存一致性`。返回候选段落、来源与位置，不调用模型。部署与验证见[续发记录](docs/validation/retrieval-v2-deployment-20261018.json)。

- 本人 Miyuki 私聊发送 **`/asis`**：打开交互卡片，选择角色／资料范围、提交问题、查询进度、暂停／恢复／取消。原卡片入口和按钮已由用户确认，新目标管理排版待真人复核。
- [私有 PWA](https://35.209.202.207/)：搜索、加密阅读、「结合资料分析」／「按需公开研究」及「个人助手」角色选择。
- 原文字命令保留：`/asis search 关键词`、`/asis analyze 问题`、`/asis research 私人问题 | 公开检索词 | 公开HTTPS链接（可选）`。
- 既有工作使用原编号查询或明确恢复；已付费步骤免费复用，结果未知时不自动重做。Mac 必须在线才能读取正文和分析；当前没有自动后台委托。

来源原文保留原位置。Study／Life 按[持续授权](docs/private-data-authority.md)覆盖现有与新增文件，包括日记和健康资料；凭据和显式排除项优先，模型只处理问题相关的最小上下文。正文阅读、模型处理和渠道展示分别检查权限。

外部来源完整历史／关注流、平台删除同步与自动增量尚未完成，现有外部缓存没有模型或远程正文披露许可。持续委托／自动代选、自动长期记忆／规则、正式任务／日历／邮件，以及照片／作息采集尚未实现。已有领域目标／短期工作历史不等于 PA4 长期记忆，委托状态也不等于 PA2 正式行动任务。新版无人值守恢复、完整 PWA 人工操作和真实个人多角色分析质量仍待验收。使用与限制见[综合指南](docs/assistant-usage.md)。

## 文档入口

| 需要了解的内容 | 文档 |
|---|---|
| 检索架构审计、独立 V2 与质量门槛 | [Retrieval V2](docs/retrieval-v2.md) |
| 当前完成情况与缺口 | [项目完成情况](docs/project-status.md) |
| 综合助手／飞书卡片 | [使用指南](docs/assistant-usage.md)、[卡片说明](docs/feishu-cards.md) |
| 完整文档导航 | [文档索引](docs/README.md) |
| 当前日常运行与排障 | [Mac 单节点运行](docs/pa0-mac-only.md) |
| PA0 是否通过及验证依据 | [最终验收](docs/pa0-acceptance.md) |
| PA1 入口、研究与验收 | [按需探索验收](docs/pa1-acceptance.md)；[本机检索与模型分析](docs/pa1-local.md) |
| 配置、权限、协议与阅读 | [Mac](docs/pa0-mac.md)、[协调](docs/pa0-coordinator.md)、[PWA](docs/pa0-pwa.md)、[飞书](docs/pa0-feishu.md)、[文本阅读](docs/pa0-text.md) |
| 后续交付顺序 | [实施计划](docs/implementation-plan.md) |
| 项目规则与规格 | [AGENT.md](AGENT.md)、[SPECIFICATION.md](SPECIFICATION.md)、[CONTEXT.md](CONTEXT.md) |

## 本机命令与开发验证

在仓库根目录执行，输出 JSON：

```sh
scripts/asis doctor
scripts/asis status
scripts/asis search "芯片" --limit 5
scripts/asis reconcile
scripts/asis audit
scripts/asis-pa1 retrieve --source study --query "共享内存副本如何保持一致"
scripts/asis retrieval-v2 search --source study --query "缓存一致性" --mode lexical --diagnostics-only
scripts/asis-pa1 budget
scripts/asis work list
scripts/asis agent validate  # 可选 Pi 依赖安装后，仅使用合成资料
```

仓库入口默认使用 `python3`。生产 Mac 使用私密运行目录中的 Python 环境及发布包；可选依赖和维护方法见 [运行说明](docs/pa0-mac-only.md)，不要用缺少加密依赖的基础解释器覆盖生产服务。

核心要求 Python 3.11+、SQLite 3.34+ 与 FTS5 trigram；PDF／Office 和加密能力按需使用 [可选依赖](pyproject.toml)。本机运行数据位于 `~/Library/Application Support/PersonalAsis/`，配置、索引、日志与凭据均不进入 Git。

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

测试使用合成资料；可选依赖缺失时明确跳过，不把跳过计为通过。历史部署、旧测试来源和停用 ROG 的记录见 [部署归档](docs/archive/pa0-rollout-2026-10.md) 与 [ROG 历史](docs/pa0-rog.md)。
