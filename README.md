# Personal Asis

**PA0 已完成验收（2026-10-14）**：当前只运行 Mac 检索节点，VPS 提供协调，飞书与 [私有 PWA](https://35.209.202.207/) 提供入口。支持资料搜索、证据定位、按独立阅读许可加密查看普通／私密正文，以及休眠后的搜索任务自动恢复。

Mac 在验收时索引 Study 267 篇、Life 181 篇，共 448 篇 Markdown。ROG 已停用；独立备份和恢复密钥按用户选择暂缓。**PA1 按需分析与研究已部署（2026-10-15）**：本机混合检索、实际离线语义模型、向量缓存、MiMo Flash 与本人网页／飞书分析已交付；真实私密 HTTPS 分析及首次飞书本人请求、分析和平台发送成功回执已验证，见 [PA1 验收](docs/pa1-acceptance.md)。公开搜索遇限流时降级，明确提供原始链接的研究路径已验证；通用 Agent 框架仍待交付。

## 使用入口

2026-10-15 新增[委托状态与 Pi 合成适配](docs/agent-runtime-local.md)，并实现[本机按需 Agent 与恢复](docs/agent-on-demand.md)：复用 PA1 权限与预算，持久重建已完成步骤。实际 MiMo 合成闭环／跨进程恢复已通过，真实 Study 在证据不足时明确拒答。共享冷却、诊断和清理已发布至既有 Mac 服务；历史两笔未知预留保留。本人渠道仍沿用 PA1，尚无渠道 Agent 命令或后台委托。

- 飞书私聊：`/asis search 关键词`，完成摘要附 PWA 任务链接。
- 飞书分析：`/asis analyze 问题`；进度使用 `/asis status 分析编号`。公开研究使用 `/asis research 私人问题 | 公开检索词 | 公开HTTPS链接（可选）`。
- PWA：使用既有静态密码登录，搜索后查看结果；有阅读资格的条目可打开摘录／正文，也可使用「结合资料分析」及「按需公开研究」。
- Mac 休眠或离线时，新搜索等待恢复；正文由在线 Mac 按需读取。
- 首次分析可能需数分钟建立语义缓存；分析中转有效期为 15 分钟，过期或调用结果未知时不自动重复付费。此次飞书首次全来源请求约 445 秒，缓存后另一次本机检索约 1.94 秒，不代表所有请求时延。

来源原文保留原位置。Study／Life 按[持续授权](docs/private-data-authority.md)覆盖现有与新增文件，包括日记和健康资料；凭据和显式排除项优先。模型按需处理最小上下文，私密 PWA 阅读另检查独立许可并加密中转；已绑定本人飞书私聊可接收获准分析与相关摘录。自动长期记忆和远程权限管理尚未实现；PWA 成功报告的人工浏览器阅读、新分析服务的无人值守休眠／整机重启仍未验收。

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
scripts/asis work list
scripts/asis agent validate  # 可选 Pi 依赖安装后，仅使用合成资料
```

仓库入口默认使用 `python3`。生产 Mac 使用私密运行目录中的 Python 环境及发布包；可选依赖和维护方法见 [运行说明](docs/pa0-mac-only.md)，不要用缺少加密依赖的基础解释器覆盖生产服务。

核心要求 Python 3.11+、SQLite 3.34+ 与 FTS5 trigram；PDF／Office 和加密能力按需使用 [可选依赖](pyproject.toml)。本机运行数据位于 `~/Library/Application Support/PersonalAsis/`，配置、索引、日志与凭据均不进入 Git。

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

测试使用合成资料；可选依赖缺失时明确跳过，不把跳过计为通过。历史部署、旧测试来源和停用 ROG 的记录见 [部署归档](docs/archive/pa0-rollout-2026-10.md) 与 [ROG 历史](docs/pa0-rog.md)。
