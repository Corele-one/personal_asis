# PA0 Mac 单节点运行

> 2026-10-20：本文归入远程兼容资料；VPS／机器人／远程通信暂缓，当前开发以[本机 Pi 主线](local-agent-focus.md)为准。本文版本与验收均限原日期，不能据此推断当前线上状态。


2026-10-19周复盘修复：Mac更新为 `pi-week-review-6e7dc2f9d55e4e11`，VPS保留 `retrieval-context-3fa59e109dd0af73`。修复“过去的一周”的本机时间识别／Life路由、纯文本JSON模式和失败状态空结果处理；日期复盘在原8192字节提示／512生成Token上限内最多选七段。553项回归＝534通过＋19跳过，实际Pi SDK另2项通过；真实Life只读检查覆盖七天，一次MiMo虚构周记生成849 Token并离线复用，人工检查仍发现一处日期归属错误，不能报告为领域质量通过。原失败调用保留且未重试。见[修复说明](pi-weekly-review-fix.md)与[验收记录](validation/pi-weekly-review-20261019.json)。以下为之前发布快照。

2026-10-19本机Pi入口：Mac已发布 `pi-terminal-f35a3859fc4834d1` 的[原生终端界面](pi-terminal.md)，可直接聊天、查看工具过程、保存／恢复本机会话；VPS仍为 `retrieval-context-3fa59e109dd0af73`。新入口复用原MiMo、来源许可、角色与预算，不依赖飞书／VPS，不自动启用v2.3。544项回归＝525通过＋19跳过，另2项实际Pi SDK合成测试通过；真实TTY问候161 Token、无笔记读取，领域质量与完整Retrieval Gate仍待验收。固定启动器及回退材料见[本轮记录](validation/pi-terminal-20261019.json)。以下为前一切片及更早快照。

## 2026-10-19 当前运行

质量续作后当前Mac PA0／PA1与VPS代码为 `retrieval-context-3fa59e109dd0af73`，原解释器、配置及前一发布保留；隧道／独立MCP仍运行。仅新增[本机显式质量实验](retrieval-context-quality.md)，完整生产替换Gate未通过。Mac／VPS回退标识同发布名，按[回退步骤](retrieval-context-quality.md#发布回退与下一门槛)恢复代码／plist，不回滚预算／索引库。部署和只读链路见[本轮记录](validation/retrieval-context-20261019.json)；下文为前一切片快照。

Mac PA0／PA1与VPS现使用 `retrieval-quality-e6d8bd41f7ea44a3`，原解释器和旧发布保留；默认检索、角色、来源／渠道权限与历史付费协议不变。隧道和Life索引已恢复，当前Study267／Life187、外部24／9／8，共495活动条目。新增的是[显式本机质量工具](retrieval-quality.md)，合成检索Gate通过，真实探针／完整生产替换未通过，不能开启后台或替换普通检索。

本次发布发现`launchctl bootstrap`成功后服务仍未启动，已自动回滚，随后在bootstrap后显式`launchctl kickstart gui/$(id -u)/LABEL`并等待`state = running`再继续。首次登记成功不等于运行成功；完整回滚与验收见[本轮记录](validation/retrieval-quality-20261019.json)。人工恢复不代替无人值守休眠／重启验收。以下10月18日及更早记录保留历史范围。

## 2026-10-18 Retrieval V2 续发

当前发布 `retrieval-v2-de593bc25486b7cc` 已部署Mac／VPS；原解释器、来源／模型许可与普通搜索／Agent协议保持原值。本人飞书私聊测试：`/asis retrieve-v2 study | 缓存一致性`。这是显式词法候选阅读，返回段落与位置，0模型调用；完整质量Gate未过，普通检索未切换。实际协议／测试与回滚见[部署验收](validation/retrieval-v2-deployment-20261018.json)。真实飞书消息和界面由用户自行验证，下列较早发布编号与数量保留历史范围。


2026-10-16最新接入：小红书已切换到独立MCP，使用系统钥匙串保存会话与服务鉴权；首页2条、收藏2条、单篇正文、本机搜索和服务重启后会话复用均通过真实验证，缓存共8条（精选2条）。Folo已按用户选择新增arXiv cs.AR＋cs.DC、SIGARCH博客、LLVM发布三条普通订阅，均归“研究与工程”，订阅总数38→41，各读取2条元数据并入本机索引，Folo缓存共9条。Mac发布 `reading-mcp-e181642291535fcc`，395项回归379通过、16跳过；PA0、PA1、独立MCP和隧道运行正常。没有新增模型／远程许可或助手后台抓取；完整历史、完整关注流及平台删除同步未完成。知乎官方CLI停止推进，公众号不接。见[小红书说明](xiaohongshu-setup.md)、[研究信源](source-recommendations.md)和[本轮验收](validation/xhs-mcp-feeds-20261016.json)。

当前最新发布为 `reading-mcp-e181642291535fcc`（2026-10-16），Mac PA0／PA1／独立MCP及隧道running、各自原解释器和回退材料保留。新增Folo安全浏览器登录（钥匙串凭据、回环回调），真实只读验证通过，来源配置和模型政策保留；见[Folo现场验收](validation/folo-live-20261016.json)。下文发布为各自历史快照。

最新续发（2026-10-16）：Mac PA0／PA1现均使用 `reading-connectors-181945e7fb11c8d1`，原解释器保留，VPS未更新。Folo／知乎／小红书工具安装与公众号分享入口已准备，账户访问为暂缓；没有登录或启动小红书服务。见[当前信源配置](external-reading-setup.md)与[验收](validation/reading-connectors-20261016.json)。后续段落中的版本为历史快照。

当前代码续发（2026-10-15）：Mac PA0／PA1现均使用 `reading-sources-311c9f3870b96a0f`，各自原解释器和旧包／plist回退材料保留。新增WUCAI中国区／Folo本机只读配置，均无凭据、条目0、无模型或远程展示许可；未启用后台或更新VPS。见[使用及边界](external-reading.md)与[验收](validation/reading-sources-20261015.json)。下文各发布编号保留为其日期的历史记录。

PA0 已于 2026-10-14 完成当前范围验收，见 [最终记录](pa0-acceptance.md)。日常只维护 Mac 资料；VPS 负责协调，飞书与 [PWA](https://35.209.202.207/) 提供入口。

## 当前范围

| 项目 | 状态 |
|---|---|
| 检索节点 | 仅 `mac`；ROG 停用，新旧任务均排除其结果和等待 |
| 来源快照 | Study 267、Life 181，共 448 个 Markdown（2026-10-14） |
| 正文阅读 | 获准条目按 `remote_evidence` 加密中转；私密内容另需 `private_remote_evidence`，范围及实测见[持续授权](private-data-authority.md) |
| 离线恢复 | 服务重启及真实休眠后，同一任务自动继续完成，已验证 |
| 备份 | 已有本机加密状态归档；独立副本／恢复密钥按用户选择暂缓 |
| 后续能力 | PA1 本机 CLI／语义模型已交付，见 [PA1 记录](pa1-local.md)；本人渠道分析与按需研究见 [PA1 验收](pa1-acceptance.md)；通用 Agent 框架与持续委托未上线 |

Mac 休眠／关机时新搜索等待恢复，正文需要 Mac 在线。来源保持原位置，权限权威在 Mac。本人私聊／PWA 表达授权已获准，但远程管理入口尚未实现；当前实际修改仍通过本机执行。

## 日常维护

在原来源目录保存资料即可；节点启动／唤醒后核对索引，在线每六小时核对。主动核对可运行 `scripts/asis reconcile`，本机查询返回原文 URI 与位置。配置字段见 [Mac 本地节点](pa0-mac.md)。

生产数据目录为 `~/Library/Application Support/PersonalAsis/`。生产 Python 在其 `pa0-text-env/bin/python`，代码在 `code-releases/`，实际发布由 launchd 的 `PYTHONPATH` 指定；当前验收发布编号见最终记录。

仓库入口默认 Python 不一定安装了加密依赖。核查生产能力或从 checkout 维护时显式选择既有环境：

```sh
ASIS_PYTHON="$HOME/Library/Application Support/PersonalAsis/pa0-text-env/bin/python" scripts/asis doctor
ASIS_PYTHON="$HOME/Library/Application Support/PersonalAsis/pa0-text-env/bin/python" scripts/asis status
```

重新执行 `service install` 会将服务切换至执行命令时的 Python／代码路径；仅在维护或发布时使用，并在安装后验证 running 与心跳。卸载保留配置、索引和凭据。

2026-10-15 维护发布：Mac 索引与 PA1 服务现使用 `agent-local-51e8faaa94990dbb`，原 pa0-text-env／pa1-env 解释器保留；代码和旧 plist 的回退材料留在私密运行目录。更新包含共享模型冷却、诊断及现有核对周期中的会话清理，没有启用新的后台委托。实际闭环与发布证据见 [按需 Agent 验收](agent-on-demand.md)。

## 排障顺序

```sh
launchctl print gui/$(id -u)/local.personal-asis.mac
launchctl print gui/$(id -u)/local.personal-asis.tunnel
```

1. 本机无结果：检查来源可用性、排除规则、分类与索引状态，再显式核对。
2. PWA 持续等待 Mac：检查索引进程及 SSH 隧道；服务正常后应恢复心跳，原任务无需重新提交。
3. 只有元数据而没有正文按钮：检查当前元数据路径许可、`remote_evidence`、私密内容的 `private_remote_evidence`、排除项及原文版本；元数据许可本身不开放正文。
4. PWA 登录或 HTTPS 故障：检查 [PWA 管理](pa0-pwa.md) 与 VPS 服务／续期状态。

必要时可显式重新启动既有服务：

```sh
launchctl kickstart -k gui/$(id -u)/local.personal-asis.tunnel
launchctl kickstart -k gui/$(id -u)/local.personal-asis.mac
```

节点协议和配对见 [协调文档](pa0-coordinator.md)，飞书命令见 [飞书文档](pa0-feishu.md)。ROG 的原文件、索引和旧备份保留，恢复只在用户明确要求时进行，见 [ROG 历史](pa0-rog.md)；当前无需维护 ROG，也不继续 F 盘备份传输。

## 验证记录

七项功能验收、93 项 Mac 应用检查、实际 SDK 的 3 项检查及真实休眠／自动恢复见 [最终验收](pa0-acceptance.md)。99 项应用套件在不同环境有不同可选依赖跳过数，不能把跳过计入通过。

整机重启未执行；独立备份／恢复密钥暂缓。先前切换与故障过程见 [部署历史](archive/pa0-rollout-2026-10.md)，不作为当前未完成待办。

2026-10-15 后续发布：PA1 独立服务现使用 `agent-channels-8ae9212d723ecc7f`，PA0 仍使用前述发布及解释器。本人 PWA／飞书按需 Agent、首次检索、跨渠道恢复与真实 HTTPS 拒答／零新增 Token 恢复见 [续验](agent-channels.md)。未启用持续委托。

2026-10-15 综合助手发布：PA1 切换至 `assistant-cards-4acc99f9db7cdd3e`，原解释器及 PA0 plist 保持不变，旧包／plist／VPS 插件和代码保留。协调、PWA、AstrBot、nginx active；发现既有 SSH 隧道退出后已重启，并核验回环监听和实际心跳。本轮未复测无人值守休眠／整机重启。本人 `/asis` 卡片及按钮已现场确认，服务器显示查询／取消均已提交并完成平台原卡片更新，额外模型 Token 0。见[综合使用](assistant-usage.md)及[验收](validation/agent-roles-20261015.json)。

2026-10-15 回应修复续发：PA1 使用 `assistant-reply-f0ce5caae433405a`，原解释器、PA0 plist、既有隧道及来源政策保留。简单倾听不读笔记、相对日期过滤及卡片回答／原文分区见[修复说明](agent-response-routing.md)和[验证](validation/agent-response-20261015.json)。旧工作仍使用原付费协议，不自动重新分析。

2026-10-15 领域连续性续发：PA1 发布 `assistant-context-74c67f212641aa55`，原解释器和 PA0 配置保留；飞书目标管理复用既有长连接和加密结果回传。卡片页面另存元数据表，原卡片表形状保持兼容，旧版回退不要求删除或迁移个人工作数据。见[连续性](agent-role-continuity.md)及[验收](validation/agent-continuity-20261015.json)。
