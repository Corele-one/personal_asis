# PA0 Mac 单节点运行

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
