# 独立 Alma Work

2026-11-09，阶段2A／W0–W1。手机配对已由本人确认，服务端观测到iOS 1.69连接及端到端加密。本人已确认在本机设置连接关闭时，iPhone新会话成功创建并读回`hello`，VPS合成文件内容核对一致，手机自有文件任务验收通过。首批仅面向自己的VPS工作文件与终端；共用资料、Mem0、PWA Work状态、Journal／日历／平台工具均未接入。

2026-11-10 W2已接入共用资料只读工具，支持共享副本和五彩保存原文；不复制凭据或直接开放源库，不接Mem0。工程验收和手机本人使用分别记录，见[共用资料说明](work-knowledge.md)及[验收](validation/work-knowledge-20261110.json)。前述“首批未接入”是11月9日W0–W1的范围。


2026-11-10按本人希望增加Work余量的要求，本轮将swap上限从128MiB提高到192MiB；RAM高水位320MiB／硬上限384MiB、Node堆256MiB保持。已修改持久单元并在线应用，不重启Work／Chat，不改变任务、模型、配对或权限。7次健康检查均成功，PID保持，3项部署回归通过；这只是缓冲及配置验收，不是新任务性能或并发容量验收。当前建议一次一个普通任务；“少量”不表示每天限几次，也不新增硬性单任务开关。一个任务若加载大量上下文、运行重程序或分出多个子任务，仍可能吃紧。swap用量高不单独证明泄漏或仍有任务运行，空闲冷页也不会在任务结束后必然立即移回RAM。见[本批核对](validation/alma-work-resources-20261110.json)。

## 部署与权限

官方固定版 **0.4.530 Linux x64**，SHA256为`05ca4bccddf1c96cd528ae6bd0a20495c73346eeb1b2208646750918069eee49`。已核对官方发布元数据和现有归档；0.4.538的更新内容是herdr终端复制，不作为本批升级前置。[官方发布](https://github.com/yetone/alma-releases/releases/tag/v0.4.530)

| 项目 | 当前配置 |
|---|---|
| 服务与身份 | `alma-work.service`／`alma-work`，无登录shell／sudo权限 |
| 官方程序 | `/opt/alma-work/releases/alma-server-0.4.530-linux-x64`，root所有，`current`固定指向 |
| 私密数据 | `/var/lib/alma-work/data`；HOME `/var/lib/alma-work`，0700／umask0077 |
| 工作成果 | `/srv/alma-work`，0700 |
| 接入 | 仅127.0.0.1:23001；iPhone走官方加密relay；没有nginx公开代理 |
| 模型 | VPS已有MiMo／DeepSeek账号；可选MiMo 2.6 Flash及DeepSeek V4 Flash，默认MiMo；两者上下文按官方1M设置为1,000,000 token，单次输出4096 |
| 原生执行能力 | 自动选工具／技能，已启用Agents及按需子任务；工具选择模型复用现有MiMo |
| 记忆 | 原生自动记忆／自动检索关闭，无embedding服务，无真人历史导入 |
| 后台 | 原生个人代理proactive／自动渠道路由关闭，heartbeat关闭；不保留默认Check in排期 |
| 执行策略 | 本人选择常规Bash不逐条批准：`ALMA_TOOL_APPROVAL=auto`；UI的autoApprove开关保持false，但headless环境策略优先 |
| 重试 | `network.retryAttempts=0`；服务退出不自动重启，不自动重放未知任务 |
| 资源 | Node堆256MiB，cgroup高水位320MiB、最大384MiB、swap最大192MiB，CPU70%，96任务 |

2026-11-09上下文修正：初始化器此前将两个模型的`capabilityOverrides.contextWindow`都写成32768；这不是上游模型限制。原生自动压缩阈值80%，使约26K的请求就可能触发压缩，而当前固定提示／工具等开销估计约20K。已通过原生提供商模型API在线修正为1,000,000，保留80%阈值、最近消息策略、输出4096和全部用户设置；无需重启服务。初始化器同样修正，避免后续补配置重新降回32K。模型容量与每轮实际发送量分别看待，配置1M不会自动填满请求；本次不恢复或重新展开既有压缩归档，不重放任何旧任务。

官方依据：[MiMo V2.6 Flash](https://mimo.mi.com/models/en-US/mimo-v2.6-flash)列明1M上下文；[DeepSeek当前API说明](https://api-docs.deepseek.com/quick_start/pricing/)列明1M，既有`deepseek-v4-flash`名称仍被接受、由当前Flash模型服务。本次保留原模型ID，不混入模型更名、模态或输出上限变更。

原生REST／WebSocket真实合成验收：两家各两轮，首轮输入4500行随机测试数据，第二轮不重贴文档、回查首尾标记。MiMo实际输入109,385／110,530 token，耗时27.224／14.376秒；DeepSeek实际输入74,902／76,001 token，耗时8.590／4.429秒。四次均正确回查且零压缩，原生上下文事件均报告1,000,000容量。这验证超过旧32K的连续上下文，不代表完整1M满载质量／性能、普通工具链或手机端体验已经验收。共4次真实模型调用，无平台测试消息；私密回退只保存原模型描述，不覆盖会话。详见[本轮验收](validation/alma-context-20261109.json)。

systemd将系统目录只读挂载，隐藏`/home`、`/root`及用户运行时目录；仅Work数据、工作区和私有临时目录可写。真实服务挂载环境中，以Work身份读取Chat配置／Life目录和写系统目录均被拒绝，自己的测试文件可读写。这是已检查的OS限制，不是能执行任意不可信代码的完整安全隔离。Work持有自己的提供商配置和高权限本地API；不能向公网开放管理端口，不能把配对权交给Dashboard。

本人在手机验收后明确要求常规Bash不逐条批准，因此改为原生auto，让Work自有文件／终端直接执行。auto适用于该Work运行时的原生审批，不是按shell命令精细分级的策略；路径保护与资源限制由systemd落实。真实日记、日历和外部平台写工具未接入，其独立确认规则不因此撤销。本人进一步要求减少人为限制，现恢复自动技能、Agents及按需子任务，取消“只能单任务／前台”的工作说明；容量验收仍仅覆盖顺序轻任务，后台取消与未知结果的完整防重仍属W4范围。

此前ask合成允许／拒绝、离线拒绝和取消测试是历史结果。真人iPhone 1.69测试中，Bash连续4次以`No active window available for approval`拒绝，未能完成手机任务；这是原生审批通道缺口。固定包与另行校验、只作静态检查的0.4.547均仅向桌面窗口／handoff监听者通知审批。改auto是本人改变执行偏好，不是修复手机审批。取消后的旧审批残留及合成迟到批准未执行，同样不证明全部后台工具取消语义。

## 使用

本人已经在Alma“远程访问”登录并完成iPhone扫码。连接后直接说需求即可，不需要说“在VPS Work中”、指定Project或点名Bash；普通对话会自动使用配置好的默认工作目录。旧名称`VPS Work`已改为“默认工作区”。飞书Chat不会自动派单或复制当前对话；仅Mac原库才有的文件，目前Work无法取得。

### 主对话、普通Chat与Projects

| 界面概念 | 关系与用法 |
|---|---|
| Alma图标入口／主对话 | 固定绑定的常用对话，反复打开继续同一条历史；服务器标题已改为“个人助手 · 主对话”，绑定和原消息保留。图标与移动端顶栏样式由原生客户端控制 |
| 普通Chat | 可按主题另开会话，每条分别保存消息和模型选择；主对话与普通会话都能调用工具完成工作 |
| Project | 关联工作目录、文件与项目配置，可包含多条会话；用于组织材料，不是启用助手的必选步骤 |

默认情况下，普通会话与主对话自动关联默认工作区；无需每次手工建Project。共用同一目录意味着可以按需访问相同工作文件，不代表自动带入所有其他会话消息。当前没有接入共享Mem0，不声称另一条会话自动拥有完整历史。

模型选择器现在提供**MiMo 2.6 Flash**和**DeepSeek V4 Flash**，默认继续使用MiMo，主对话与普通会话均可手动选择。工具／技能选择模型也已绑定现有MiMo，修复此前`No tool model configured`导致的自动工具发现缺项；增加DeepSeek没有改动Chat Router或其他会话的默认提供商。

已用不含“VPS Work”“Project”“Bash”的自然语言请求，通过默认会话设置创建并读回合成文件；原生MiMo任务22.39秒成功。DeepSeek另完成一次真实流式文件工具任务，14.57秒成功。这些是有界合成检查，不是任意任务／并发性能的保证。

本机查看、启停与临时设置连接：

```sh
scripts/alma-work status
scripts/alma-work stop
scripts/alma-work start
scripts/alma-work tunnel
```

`start`后首次初始化需等待本地健康接口就绪。`tunnel`保持该终端打开，在浏览器访问`http://127.0.0.1:23001`，关闭连接不影响iPhone经relay使用VPS。登录和配对令牌仅在原生安全输入中处理，不放聊天／命令参数／Git；不要将配对链接发布或截图入库。

合成成果`/srv/alma-work/w1-result.txt`正文为`W1_OK`，不是个人资料或真实工作经历。带`W1 synthetic:`标题的会话用于验收，不进入个人记忆。

工作区`AGENTS.md`保留简短工作说明；默认目录、工具／技能与子任务开关通过原生设置实际生效。该Markdown说明不冒称在所有会话中必然自动注入，OS权限边界由systemd落实。

## 维护与回退

部署资产为`deploy/install-alma-work.py`、`alma-work.service`、`run-alma-work.py`及`alma-work-AGENTS.md`。安装器在任何用户／目录改动前核对官方SHA256，官方归档按安全过滤解压到临时目录后原子安装；运行中拒绝换版本，已有工作区指令不覆盖。把这些文件与归档放在同一VPS管理员控制的准备目录，以管理员运行安装器，安装后不会自动启动或启用服务。

首次模型配置使用`deploy/configure-alma-work.py`，在VPS管理员会话按固定来源读取已批准的xiaomi／deepseek账号，经原生回环API写入Work；不会复制整个Chat配置、打印密钥、导入其他账号或改动AstrBot。完整初始化会设置默认模型与开关，不应用它覆盖之后用户的新选择；`--providers-only`仅补齐／启用这两家并保留已有提供商身份、其他已选模型和会话默认配置。凭据从未经Mac中转。

`run-alma-work.py`不修改官方bundle；只转发进程生命周期，吞弃原生stdout／stderr原文，journal仅写固定故障类别和退出码。禁止core dump，避免崩溃转储携带私密内容。Alma自己数据目录的应用文件仍属于其私密数据，不能把系统日志过滤冒称为上游应用内部完全无日志。

停用仅`systemctl disable --now alma-work`；保留全部数据、配对与成果。升级前先停Work，备份Work自己的私密数据并核对上游兼容性，安装已校验固定版再切`current`。代码回退只换官方程序／服务／启动器，不以旧数据库覆盖新会话；迁移兼容性未核实时保持停止。Chat、Dashboard、Router和Calendar服务不参与此流程。

## 验收边界

最初128MiB堆、256MiB进程内存上限下，进程在较长观察间隔后以SIGABRT退出；峰值225.3MiB、swap128MiB，系统未报告cgroup OOM。由于当时原始stderr丢弃，不能确定是V8堆不足或其他native故障。后续增加有上限的堆／内存配置和固定分类诊断，不能把一次短测当成长驻稳定性证明。

还发现Alma的个人代理独立于memory开关，默认proactive=true；在本次配对／初始化过程中创建了`Check in`例行任务，已有一次运行。现已通过官方`/api/personal/settings`关闭proactive与自动渠道路由，原生cron为空、heartbeat关闭，保留已有结果及用量。初始化脚本现在先关闭此默认行为再配置模型，不能把关闭自动记忆当作全部后台生成已关闭。

实际SDK／API合成、真实MiMo、服务资源、Chat保留、手机本人验收分别记录于[验收回执](validation/alma-work-w01-20261109.json)。配对成功不替代手机独立完成任务、Mac关机场景及复杂任务资源验收。
