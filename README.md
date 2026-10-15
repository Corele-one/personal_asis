# Personal Asis

**已部署可按需使用的助手，完整实施计划尚未完成（2026-10-15）。** 当前版本 `assistant-reply-f0ce5caae433405a` 支持本机资料检索／阅读、MiMo 分析与公开研究、总管及研究／申请职业／生活复盘三个专业角色的串行协作，以及本人 PWA／飞书卡片。逐项状态见[项目完成情况](docs/project-status.md)与[实施计划](docs/implementation-plan.md)。

PA0 已按 Mac 单节点范围验收；VPS 负责协调和渠道入口，ROG 停用。2026-10-14 验收时索引 Study 267 篇、Life 181 篇，共 448 篇 Markdown；这不是实时来源数量。独立备份和恢复密钥按用户选择暂缓，整机重启未验。

## 使用入口

- 本人 Miyuki 私聊发送 **`/asis`**：打开交互卡片，选择角色／资料范围、提交问题、查询进度、暂停／恢复／取消。真实卡片和按钮已由用户确认。
- [私有 PWA](https://35.209.202.207/)：搜索、加密阅读、「结合资料分析」／「按需公开研究」及「个人助手」角色选择。
- 原文字命令保留：`/asis search 关键词`、`/asis analyze 问题`、`/asis research 私人问题 | 公开检索词 | 公开HTTPS链接（可选）`。
- 既有工作使用原编号查询或明确恢复；已付费步骤免费复用，结果未知时不自动重做。Mac 必须在线才能读取正文和分析；当前没有自动后台委托。

来源原文保留原位置。Study／Life 按[持续授权](docs/private-data-authority.md)覆盖现有与新增文件，包括日记和健康资料；凭据和显式排除项优先，模型只处理问题相关的最小上下文。正文阅读、模型处理和渠道展示分别检查权限。

外部账户来源接入、持续委托／自动代选、自动长期记忆／规则、正式任务／日历／邮件，以及照片／作息采集尚未实现。已有领域目标／短期工作历史不等于 PA4 长期记忆，委托状态也不等于 PA2 正式行动任务。新版无人值守恢复、完整 PWA 人工操作和真实个人多角色分析质量仍待验收。使用与限制见[综合指南](docs/assistant-usage.md)。

## 文档入口

| 需要了解的内容 | 文档 |
|---|---|
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
