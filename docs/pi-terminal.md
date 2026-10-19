# Mac 本机 Pi 终端

2026-10-19，按用户选择提供 Pi 原生终端界面，直接使用现有个人助手宿主。Mac独立包与维护代码发布为 `pi-terminal-f35a3859fc4834d1`；VPS保持 `retrieval-context-3fa59e109dd0af73`。本机交互不经过飞书、AstrBot或VPS；模型仍是现有MiMo Flash，并非离线大模型。来源、私密模型许可、共享日／月预算与既有检索协议继续由Python执行。

## 启动

在项目目录运行：

```sh
./scripts/asis-pi
./scripts/asis-pi --continue
./scripts/asis-pi --source study --mode research
./scripts/asis-pi --source life --mode life
./scripts/asis-pi --mode conversation
./scripts/asis-pi --check
```

仓库入口运行checkout。已安装的固定发布入口不依赖当前目录：

```sh
"$HOME/Library/Application Support/PersonalAsis/launchers/asis-pi"
"$HOME/Library/Application Support/PersonalAsis/launchers/asis-pi" --continue
```

也可在Finder双击 `scripts/Personal Asis.command`，它优先启动已安装版本。固定启动器使用部署时核实的Node真实路径，避免依赖某个临时fnm shell。要求原PA1 Python、Node22.19+和终端TTY；重定向输入时拒绝启动，`--check`不调用模型、不读取钥匙串或正文。没有新常驻UI服务；关闭窗口后不调度后台任务。

默认新聊天选择Study＋Life、auto总管路由；可用 `--source` 缩小来源，`--mode auto|research|career|life|team|conversation` 选择角色。模式及来源绑定当前聊天，恢复时沿用保存值。它们不能授予新的来源或模型权限。auto中的纯问候同样只回应当前消息；conversation沿用现有“只回应本轮消息”规则，不隐式读取笔记或历史；资料问答中的追问才使用获准的聊天背景。

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

## 宿主与存储

固定 `@earendil-works/pi-coding-agent`、Pi agent-core／ai／tui／mcp／codemode为1.2.0，使用[官方SDK](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/sdk.md)的AgentSessionRuntime和InteractiveMode。独立 `runtime/pi-terminal` 的lockfile记录全部依赖，安装禁用生命周期脚本；原 `runtime/pi` 的lock不变。

原生界面通过一个确定性的本机传输工具委托Python已有Agent；界面本身不生成模型请求。真正的模型／search_notes循环仍由原Pi core与AgentHost执行。显示用传输不拥有模型凭据；其价格字段没有真实计费含义，所以页脚显示宿主返回Token与共享预算，不显示虚假的零元费用。回答由宿主原校验后返回，界面不会另调一次模型润色。专业角色仍串行、领域目标和专业历史保持原来的独立选用规则；此入口没有新增自动目标、公开研究、账户抓取或长期记忆。

Node UI使用临时HOME／cwd、空项目资源、显式工具allowlist和无凭据环境；没有默认read／bash／edit／write、MCP、用户插件、技能、项目AGENTS或提示模板发现。禁用UI自动重试、压缩、缓存预热、版本／模型联网刷新；UI进程的socket连接和fetch另外拒绝，Python按原许可联网。`!`、登录、分享、导入、导出、任意模型切换等原生编码器入口关闭。此为应用层约束，不声称是恶意依赖或通用代码执行的操作系统沙箱。

Pi的界面消息树只在内存中，不另存JSONL正文。`terminal.sqlite3`只保存聊天ID、创建时间、来源、模式及工作请求引用，不复制问答正文；文件0600，30天后清理聊天引用。原文／回答／执行步骤仍在原work.sqlite3／计费账本中，沿用30天、撤权清理和防重约束；Mac维护代码也已更新以理解聊天历史依赖。原始资料不修改，真实聊天与数据库不进入Git。聊天追加采用事务及预期引用列表检查，避免两个界面静默覆盖同一聊天。

## 验证与回退

544项Python回归：525通过、19跳过；另两项实际Pi SDK＋模拟宿主测试通过。新12项Python检查覆盖聊天防并发、30天引用、追问引用剥离、撤权／范围、简单倾听不读历史、原角色共享预算、结果恢复、遗忘和未知结果不重试。真实TTY已启动、显示工具步骤、完成MiMo问候并正常退出，161 Token、0笔记检索；这只证明本机传输，不能替代领域回答质量验收。完整证据及后续验收见[本轮记录](validation/pi-terminal-20261019.json)。

独立包包含代码和Node依赖，不含模型、来源、qrels或真实聊天。Mac原两个plist与前一代码包保留在同发布标识的回退目录；恢复原plist后bootstrap、显式kickstart并核查running。启动器回退为备份的 `previous-launcher`；首装没有该文件时可移除启动器。数据／预算库不随代码回退，已完成的付费工作不重做。VPS／飞书服务没有为本机入口切换版本。

完整Retrieval Quality Gate仍未通过，本入口沿用现有生产检索而非默认启用v2.3质量实验。真实个人研究／职业／生活回答、手机UI、新版无人值守重启和持续委托仍按各自门槛验收。
