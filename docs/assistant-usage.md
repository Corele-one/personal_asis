# 综合个人助手：使用与运行

2026-10-20 起优先使用本机 Pi；VPS／机器人相关用法已[归档](archive/remote-usage-20261020.md)，远程通信暂缓至[下一阶段](remote-communications-plan.md)。本机对话不要求隧道或 VPS 在线，当前范围见[本机主线](local-agent-focus.md)。

## 本机对话与持续工作状态

除`pi`和`scripts/asis chat`外，也可使用`scripts/asis web-chat`启动本机网页聊天。页面仅绑定`127.0.0.1`，可切换和恢复会话、清除所选会话内容；SSE显示步骤状态，答案仍整段返回。远程PWA目前仍是原有搜索／分析／Agent入口。

持续委托可用`proactive preview`保存具体的范围、间隔、到期、Token预算、最大轮数及本机通知条件，再通过一次性值明确授权。当前只保存策略及暂停／恢复／取消状态，不启动调度器或后台执行。完整范围见[Core API与P2–P4状态](conversation-core-api.md)。

## P1：直接对话，按需工具

`pi`用法保持不变。普通问题可直接答；“从我的笔记找依据”可检索获准资料，“从Folo缓存找作者观点”只使用获准缓存。需要公开资料时，Agent提出具体公开查询，界面显示提供商、查询、结果数、时限及资源上限；回复“同意”继续，或“不同意”取消。每个新公开词单独确认，不将私人问题直接作为外发查询。

确认后仍继续同一轮，已有模型步骤不重新付费。`/approve`、`/deny`也是可选控制；`/status`查看待确认／结果，`/budget`查看原共享预算。专业角色仅在需要时提出一次工作，确认后执行；不启动长期后台任务。当前账户来源只使用已有模型许可的本机缓存，不实时访问账户。完整[工具与恢复说明](conversation-tools-p1.md)、[本轮验收](validation/conversation-tools-p1-20261019.json)。

## 新默认：Pi原生界面持续聊天（checkout）

在仓库根目录打开终端：

```sh
pi
pi --continue
pi --session 会话ID
pi --check
```

`pi`（或仓库脚本`./scripts/asis-pi`）直接打开原生Pi对话界面，默认连接新Conversation Core；`scripts/asis chat`保留为简单文本客户端，共享相同会话。新Chat使用当前checkout和既有本机PA1配置／MiMo钥匙串／共享Token预算；要求Node及已安装的`runtime/pi`依赖。它不依赖VPS或AstrBot，不必每次指定来源、角色和request_id。`--check`只检查配置与依赖，不读取凭据或调用模型。无需改动生产服务。

```text
You > 我们先讨论缓存一致性这个研究方向。
Asis > ...
You > 它和缓存失效有什么区别？
Asis > ...
You > 从我的笔记里找相关内容。
Asis > ... [E1]
```

主Agent按需选择已授权的本机`search_notes`；普通解释可直接回答，不默认专业分工。P1公开搜索已接入新Chat，先确认具体公开词；旧显式研究入口保留，详见[联网使用](web-search-live-deployment.md)；Chat不会把私人消息直接外发为搜索词。

原生Pi用`/chats`、`/open ID`切换会话；简单文本入口用`/sessions`、`/history`查看，`/new`新建；`/status`不调用模型，`/budget`显示共享预算（包含未知调用预留）；Ctrl-C中断后用`/resume`显式继续已提交步骤，`/cancel`终止未完成轮次，`/forget`清空本会话内容但保留计费及防重标记；`/quit`退出并打印恢复命令。正在执行时可先Ctrl-C，另一进程控制同一会话会返回busy。失败或未知付费调用不自动重试。

最多选择近期4轮／2800字节历史，完整提示仍受原8192字节上限约束，长会话会提示裁剪；没有自动摘要或跨会话长期记忆。工具步骤与最终引用分别保存，来源变更／撤权会清除相关回答及依赖追问。显示的是模型／工具进度与完整回答，目前没有真实文本增量。每轮最多4次模型／2次检索。详细限制见[路线与恢复语义](local-first-agent-roadmap.md)。

新Chat不导入旧`asis-pi`工作聊天或旧付费工作；`pi --engine legacy --continue`恢复旧会话，现有PWA／飞书命令继续使用原协议。下面保留旧渠道的用法，本轮没有生产发布或手机UI改版。

本机入口已补齐：`./scripts/asis-pi` 打开Pi原生终端，`--continue` 恢复本机聊天，无需飞书／VPS；来源、角色、工具和预算继续由原宿主管理。命令与限制见[Mac本机Pi](pi-terminal.md)。周复盘时间／路由、JSON模式与失败状态已[修复](pi-weekly-review-fix.md)，安装版需退出后重新启动；原失败请求不自动重做。

## 远程部分已归档

VPS／机器人／远程PWA的旧用法移至[远程使用归档](archive/remote-usage-20261020.md)，代码边界见[归档清单](archive/remote-communications-20261020.md)。当前本机使用不要求隧道或VPS在线；开发范围见[本机 Pi 主线](local-agent-focus.md)。本轮没有停服或改动线上配置。
