# Personal Asis

**PA0 已完成验收（2026-10-14）**：当前只运行 Mac 检索节点，VPS 提供协调，飞书与 [私有 PWA](https://35.209.202.207/) 提供入口。支持资料搜索、证据定位、获准非私密正文的按需加密阅读，以及休眠后的任务自动恢复。

Mac 在验收时索引 Study 267 篇、Life 181 篇，共 448 篇 Markdown。ROG 已停用；独立备份和恢复密钥按用户选择暂缓。PA1 本机 CLI、实际离线语义模型与向量缓存已交付，当前文件（含日记／健康）的 MiMo Flash 最小分析已获独立授权；网页／飞书分析及按需公开研究已实现，见 [PA1 验收](docs/pa1-acceptance.md)；通用 Agent 框架仍待交付。

## 使用入口

- 飞书私聊：`/asis search 关键词`，完成摘要附 PWA 任务链接。
- PWA：使用既有静态密码登录，搜索后查看结果；有阅读资格的条目可打开摘录／正文。
- Mac 休眠或离线时，新搜索等待恢复；正文由在线 Mac 按需读取。

来源原文保留原位置。Study／Life 按[持续授权](docs/private-data-authority.md)覆盖现有与新增文件，包括日记和健康资料；凭据和显式排除项优先。模型按需处理最小上下文，私密 PWA 阅读另检查独立许可并加密中转；本人飞书分析与自动记忆已获授权，但相应能力仍待交付。

## 文档入口

| 需要了解的内容 | 文档 |
|---|---|
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
```

仓库入口默认使用 `python3`。生产 Mac 使用私密运行目录中的 Python 环境及发布包；可选依赖和维护方法见 [运行说明](docs/pa0-mac-only.md)，不要用缺少加密依赖的基础解释器覆盖生产服务。

核心要求 Python 3.11+、SQLite 3.34+ 与 FTS5 trigram；PDF／Office 和加密能力按需使用 [可选依赖](pyproject.toml)。本机运行数据位于 `~/Library/Application Support/PersonalAsis/`，配置、索引、日志与凭据均不进入 Git。

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

测试使用合成资料；可选依赖缺失时明确跳过，不把跳过计为通过。历史部署、旧测试来源和停用 ROG 的记录见 [部署归档](docs/archive/pa0-rollout-2026-10.md) 与 [ROG 历史](docs/pa0-rog.md)。
