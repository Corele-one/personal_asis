# 委托状态与 Pi 适配验证

状态（2026-10-15）：本页记录第一切片：本机委托状态 CLI、事务性领取／恢复接口及可选 Pi 1.2.0 子进程适配器，真实 Pi＋模拟提供商验证通过。后续已实现真实协议客户端、PA1 政策复用与步骤重建，见 [本机按需 Agent](agent-on-demand.md)；本机实际 MiMo 闭环／跨进程恢复现已续验，维护逻辑已发布现有 Mac 服务。PWA／飞书保持原 PA1 路径，未启用后台委托。

## 已实现的边界

- `work.sqlite3` 在所选 `--home` 下保存 Work Delegation、Delegation Run、角色、独立会话身份、检查点和执行标记。来源 ID 只缩小工作范围，不授予来源／提供商权限，也不创建 PA2 正式任务。
- 专业角色只能关联同一委托的总管运行；专业角色不能直接创建另一个专业角色的运行。角色上下文的长期检索与完整领域协作仍待接入。
- `pause` 暂停整项委托及所有未结束运行；`resume` 明确恢复；`stop-run` 仅停止该运行及其子运行，保留下次运行的可能；`cancel` 不可自动恢复。
- 领取使用 SQLite 事务、到期租约与递增代次。暂停或恢复后，旧进程不能提交结果；原节点过期运行可以从持久检查点继续，其他节点不能接管。第一切片仅验证状态接口；后续已完成实际 Pi 步骤的跨进程重建，见 [续验](agent-on-demand.md)，仍不自动重试未知调用。
- 执行前持久化动作身份及输入指纹。同一动作无论成功、拒绝或未知都不自动重做。进程中断／暂停时已开始的动作标为未知；恢复领取前需由本人核对，不能换代次消除未知标记。
- 同账号资源通过数据库唯一约束互斥；未知动作继续持锁。当前没有浏览器账号接入，验证只使用合成资源身份。领取优先选择主动请求，并为其预留容量；容量必须由调用方显式配置，未安装调度服务。
- 检查点／成果正文 30 天后清除，普通无正文事件 180 天后清除；最小执行防重标记保留。清理发生在状态库打开或查看时，没有新增定时作业。后续按需工具已接入来源撤权与成果清理，既有 Mac 核对服务也已发布该清理逻辑；`clear-results` 可显式清理委托成果；它不删除目标／来源原文或动作标记。

## 运行合成验证

要求 Python 3.11+、Node.js 22.19+。Pi 为可选依赖，不加入现有 PA0／PA1 Python 生产环境。仓库根目录运行：

```sh
npm ci --prefix runtime/pi --ignore-scripts --no-audit --no-fund
scripts/asis agent validate
```

固定 `@earendil-works/pi-agent-core`／`pi-ai` 为 `1.2.0`、`typebox` 为 `1.3.27`，传递依赖见 `runtime/pi/package-lock.json`。缺少 Node 或包时返回 `optional_pi_not_installed`；核心应用测试仍可运行，真实 Pi 集成项明确跳过。本轮实测 Node v24.14.1。

验证在临时私密目录创建状态库、模拟预算账本、合成正文及成果，结束后删除；不读取 Study／Life、生产模型账本、Keychain 或浏览器登录态，不连接真实模型／平台，不发送消息。CLI 输出可复查摘要见 [合成记录](validation/agent-runtime-20261015.json)。

Pi 只负责工具循环与事件。Python 主程序经 JSONL 接收模型／工具请求，逐次检查运行租约、工具声明指纹、合成来源／角色／提供商政策及共享预算，再返回获准内容。未获准条目的正文、标题、路径均过滤；撤权或暂停后不返回在途结果。子进程使用临时 HOME，环境不继承模型密钥、代理凭据或 `NODE_OPTIONS`。

合成验证只提供 `lookup` 和 `artifact`：后者只能独占创建固定的 `result.txt`，拒绝自选路径／覆盖／符号链接。没有注册 shell、网络、外部发送、MCP、插件或通用文件工具。**工具白名单和工作目录不等于操作系统沙箱**；当前不允许模型生成脚本执行，也不声称已经隔离恶意依赖或通用浏览器。

## 本机状态操作

以下创建操作仅保存委托，不触发运行。实际来源 ID 必须已在所选 home 配置；重复使用同一请求编号返回同一身份，改变内容会冲突。`D`、`R`、`K` 为返回的委托／运行／动作编号占位符。

```sh
scripts/asis work create --goal "研究已有材料中的一个问题" --source study --request-id local-work-001
scripts/asis work list
scripts/asis work show --delegation-id D
scripts/asis work enqueue --delegation-id D --request-id run-001
scripts/asis work pause --delegation-id D
scripts/asis work resume --delegation-id D
scripts/asis work stop-run --run-id R
scripts/asis work cancel --delegation-id D
scripts/asis work executions --run-id R
scripts/asis work clear-results --delegation-id D
```

专业运行使用 `enqueue --role research|career|life --parent-run R`，其中 `R` 必须为同委托的未结束总管。`--priority background` 仅记录优先级，不启用后台工作。尚无 PWA／飞书委托管理命令。

核实未知动作确切结果后，可由本人本机执行 `work resolve --run-id R --execution-key K --outcome done`（确定未成功则 `rejected`）。它解除该动作的不确定状态与资源锁，原动作编号仍不可重试；不能撤回外部效果，也不更改独立模型计费账本。无法确定结果时保持未知，不执行 resolve。

## 组件比较与后续门槛

| 候选 | 核验依据与本轮结论 |
|---|---|
| Pi agent-core 1.2.0 | [官方核心接口](https://github.com/earendil-works/pi/blob/main/packages/agent/README.md)支持注入模型流和工具；本轮实际跑通模型→查询→产物→最终响应及工具失败反馈。保留为后续生产适配的优先候选 |
| coding-agent SDK／CLI RPC | [官方 SDK](https://pi.dev/docs/latest/sdk)提供会话和资源机制；默认资源／配置发现比当前验证所需更多。本轮未安装或执行，不据文档声称其安全隔离通过 |
| pi-durable | [官方说明](https://github.com/earendil-works/pi/blob/main/packages/durable/README.md)仍标为实验性；本轮未引入其存储体系。先保留本项目已有 SQLite 状态权威，后续按需要单独评估 |

官方资料于 2026-10-15 核查。通用安全边界仍由宿主落实，见 [Pi 安全说明](https://pi.dev/docs/latest/security)。上述组件比较不等于所有候选均已运行，也不选择未经验证的生产权限设置。

本轮新增 22 项测试；完整应用回归 197 项，189 通过、8 项因既有可选依赖／平台条件跳过，Pi 集成项实际执行。完整回归使用已有 `pa1-env` 解释器及本机回环端口，仅处理合成资料。基础解释器在受限沙箱内另一次运行缺少可选依赖，14 项绑定回环端口失败；不将它报告为代码通过依据。

后续客户端与持久对话重建的实现及真实失败证据见 [按需 Agent 续建](agent-on-demand.md)。实际本机闭环已单独续验；不能用第一切片三轮模拟回答声明四个领域角色已经上线。后台频率、订阅、通知、精选规则、用户能力注册及通用脚本／浏览器隔离仍按独立门槛交付。
