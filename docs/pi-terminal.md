# Mac 本机 Pi 终端

## P1：保持默认对话，新增受控工具

打开`pi`即可持续聊天，模型按需选择本机资料、已授权阅读缓存或公开工具。联网先展示具体公开词，回复“同意”或`/approve`才执行；“不同意”或`/deny`拒绝。新公开词另行确认。需要专业能力时可提议一次工作，不默认多角色、不启用后台。工具进度与确认在原生界面显示，重复查看／确认不会重复付费；费用以`/budget`的共享账本为准。说明见[P1工具](conversation-tools-p1.md)，历史P0验收仍保持原日期范围。

## 当前默认：持续对话（checkout，2026-10-19）

在终端直接运行，无需先选择角色、资料范围或输入请求码：

```sh
pi
pi --continue
pi --session 会话ID
pi --check
```

本机`~/.local/bin/pi`是指向当前checkout的轻量启动器，不是独立的Pi编码助手；`./scripts/asis-pi`同样默认打开Pi原生界面并连接`conversation-v1`核心。界面启动显示“持续对话 · 直接输入你的问题”。直接输入自然语言，后续继续追问；模型按需选择获准本机工具，普通对话不先检索或建立专业工作。简单文本客户端`scripts/asis chat`保留为另一客户端，二者共享会话。

`/new`新会话，`/chats`与`/open ID`恢复新会话，`/scope`查看当前能力，`/status`查看本轮，`/resume`显式恢复中断，`/budget`查看共享预算，`/cancel`终止未完成轮次，`/forget`清除此会话内容，`/quit`退出。Esc可中断；未知结果不重新付费。内部请求ID自动生成，常规展示只显示处理进度，不要求用户输入编号。UI保留本次会话近期16轮展示；模型上下文、权限、预算和失效规则仍由Core执行。

原生界面只显示与转发，不负责模型规划。用量显示Core实际总Token，不把缺失的输入／输出分项伪造成实测值；当前仍是完整回答＋工具步骤事件，没有真实文本增量。新核心的上下文／检索边界见[本地路线](local-first-agent-roadmap.md)，P1公开搜索与专业工作见[工具说明](conversation-tools-p1.md)。

旧工作会话不自动导入：`pi --engine legacy --continue`或`pi --engine legacy --chat 旧ID`沿用旧语义，显式`--source/--mode`也选择旧工作引擎。普通使用无需这些选项。原固定发布启动器／Finder入口本轮未更新，仍可能启动下述旧发布；新`pi`入口运行checkout。没有重启本机／VPS服务，也没有增加模型预算。

本轮4项新Python适配检查和3项实际Pi SDK合成界面检查通过；真实TTY已验证默认界面、`/scope`与退出（模型禁用合成配置，0次新增模型调用）。已有Core真实MiMo与付费恢复记录保留，见[前一轮P0验收](validation/local-chat-p0-20261019.json)；当前接线见[本轮记录](validation/pi-conversation-default-20261019.json)。

## 旧工作引擎与此前发布快照

以下描述此前已发布的Work／角色模式，启动时需按上文显式选择legacy；历史验收不改写。

2026-10-19，按用户选择提供 Pi 原生终端界面，直接使用现有个人助手宿主。Mac独立包与维护代码现为 `pi-week-review-6e7dc2f9d55e4e11`（替代首版 `pi-terminal-f35a3859fc4834d1`）；VPS保持 `retrieval-context-3fa59e109dd0af73`。本机交互不经过飞书、AstrBot或VPS；模型仍是现有MiMo Flash，并非离线大模型。来源、私密模型许可、共享日／月预算与既有检索协议继续由Python执行。

## 启动

在项目目录运行：

```sh
./scripts/asis-pi --engine legacy
./scripts/asis-pi --engine legacy --continue
./scripts/asis-pi --source study --mode research
./scripts/asis-pi --source life --mode life
./scripts/asis-pi --engine legacy --mode conversation
./scripts/asis-pi --check
```

仓库入口运行checkout。已安装的固定发布入口不依赖当前目录：

```sh
"$HOME/Library/Application Support/PersonalAsis/launchers/asis-pi"
"$HOME/Library/Application Support/PersonalAsis/launchers/asis-pi" --continue
```

也可在Finder双击 `scripts/Personal Asis.command`，它优先启动已安装版本。固定启动器使用部署时核实的Node真实路径，避免依赖某个临时fnm shell。要求原PA1 Python、Node22.19+和终端TTY；重定向输入时拒绝启动，`--check`不调用模型、不读取钥匙串或正文。没有新常驻UI服务；关闭窗口后不调度后台任务。

下述旧工作引擎（`--engine legacy`）新聊天选择Study＋Life、auto总管路由；可用 `--source` 缩小来源，`--mode auto|research|career|life|team|conversation` 选择角色。模式及来源绑定当前聊天，恢复时沿用保存值。它们不能授予新的来源或模型权限。auto中的纯问候同样只回应当前消息；conversation沿用现有“只回应本轮消息”规则，不隐式读取笔记或历史；资料问答中的追问才使用获准的聊天背景。

## 交互命令

| 命令 | 行为 |
|---|---|
| 普通文字 | 提交当前问题，显示宿主工具与模型步骤、回答及用量 |
| `/new` | 新聊天，当前未完成请求不自动重做 |
| `/chats`、`/open ID` | 查看本机聊天ID列表、恢复一个聊天；恢复前重新核查原工作与证据 |
| `/scope` | 查看当前聊天的来源及角色 |
| `/status` | 查看当前聊天最后一项工作，不调用模型 |
| `/resume-work` | 明确恢复最后一项工作；复用已提交步骤，未知结果仍禁止重试 |
| `/pause`、`/cancel` | 暂停／取消最后一项工作 |
| `/forget` | 取消并清除当前聊天的工作成果／上下文及聊天引用；保留必要计费与防重标记 |
| `/quit` | 退出界面 |

Esc／关闭窗口可能打断在途工作；之后先用 `/status` 查状态。结果未知时保留预算预留，界面不会自动重发。当前执行中也可以从另一终端使用既有 `scripts/asis-agent status` 或work管理入口检查；普通排队消息不是后台调度。

新聊天最多32次提交；追问最多纳入本聊天最近两项已完成工作的限定摘录，每项问题180字、回答450字、局限150字，总体最多6000 UTF-8字节，仍受原8192字节完整提示限制。历史不是个人事实或本轮证据，旧E编号被移除，必须重新检索后引用。来源范围不得扩大；历史依赖递归核查并设深度／循环限制。过期、撤权、原文变化或未完成工作会停止继续使用，需本人查看状态或新建聊天。

## 日期复盘与失败状态

本机auto／life模式支持“总结一下我过去的一周”“复盘我的上周”。过去一周按北京时间含今天的七天，上周按上一完整周；已有Life授权时仅取Life，不因问题扩大来源。按日期选当前获准记录，避免依赖“总结”等词与日记正文的相似度；未知日期、冲突日期和时间窗外记录排除，缺记录不回退旧记录。最多七段短摘录并标明覆盖；原普通角色仍最多六段，完整提示与费用上限不变。片段不是完整活动清单，笔记日期也不保证是活动日期。

新本机纯文本专业角色／最后回答和日期复盘使用JSON模式，旧付费输入不改。`/status`可解释原格式错误，不再因result为空崩溃；`/resume-work`遇已知格式失败只返回诊断，不重新付费。安装版需退出旧终端后重启。完整原因、验证与语义质量缺口见[周复盘修复](pi-weekly-review-fix.md)。

## 宿主与存储

固定 `@earendil-works/pi-coding-agent`、Pi agent-core／ai／tui／mcp／codemode为1.2.0，使用[官方SDK](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/sdk.md)的AgentSessionRuntime和InteractiveMode。独立 `runtime/pi-terminal` 的lockfile记录全部依赖，安装禁用生命周期脚本；原 `runtime/pi` 的lock不变。

原生界面通过一个确定性的本机传输工具委托Python已有Agent；界面本身不生成模型请求。真正的模型／search_notes循环仍由原Pi core与AgentHost执行。显示用传输不拥有模型凭据；其价格字段没有真实计费含义，所以页脚显示宿主返回Token与共享预算，不显示虚假的零元费用。回答由宿主原校验后返回，界面不会另调一次模型润色。专业角色仍串行、领域目标和专业历史保持原来的独立选用规则；此入口没有新增自动目标、公开研究、账户抓取或长期记忆。

Node UI使用临时HOME／cwd、空项目资源、显式工具allowlist和无凭据环境；没有默认read／bash／edit／write、MCP、用户插件、技能、项目AGENTS或提示模板发现。禁用UI自动重试、压缩、缓存预热、版本／模型联网刷新；UI进程的socket连接和fetch另外拒绝，Python按原许可联网。`!`、登录、分享、导入、导出、任意模型切换等原生编码器入口关闭。此为应用层约束，不声称是恶意依赖或通用代码执行的操作系统沙箱。

Pi的界面消息树只在内存中，不另存JSONL正文。`terminal.sqlite3`只保存聊天ID、创建时间、来源、模式及工作请求引用，不复制问答正文；文件0600，30天后清理聊天引用。原文／回答／执行步骤仍在原work.sqlite3／计费账本中，沿用30天、撤权清理和防重约束；Mac维护代码也已更新以理解聊天历史依赖。原始资料不修改，真实聊天与数据库不进入Git。聊天追加采用事务及预期引用列表检查，避免两个界面静默覆盖同一聊天。

## 验证与回退

首版544项Python回归：525通过、19跳过；另两项实际Pi SDK＋模拟宿主测试通过。新12项Python检查覆盖聊天防并发、30天引用、追问引用剥离、撤权／范围、简单倾听不读历史、原角色共享预算、结果恢复、遗忘和未知结果不重试。真实TTY已启动、显示工具步骤、完成MiMo问候并正常退出，161 Token、0笔记检索；这只证明本机传输，不能替代领域回答质量验收。完整证据及后续验收见[本轮记录](validation/pi-terminal-20261019.json)。

独立包包含代码和Node依赖，不含模型、来源、qrels或真实聊天。Mac原两个plist与前一代码包保留在同发布标识的回退目录；恢复原plist后bootstrap、显式kickstart并核查running。启动器回退为备份的 `previous-launcher`；首装没有该文件时可移除启动器。数据／预算库不随代码回退，已完成的付费工作不重做。VPS／飞书服务没有为本机入口切换版本。

当前修复版工作区／独立包553项回归：534通过、19跳过，实际SDK另2项通过。真实来源只读预检已覆盖七天；849 Token的真实MiMo虚构周记通过结构与引用校验，人工仍发现日期归属错误。完整Retrieval Quality Gate仍未通过，本入口沿用现有生产检索而非默认启用v2.3质量实验。真实个人研究／职业／生活回答、手机UI、新版无人值守重启和持续委托仍按各自门槛验收。
