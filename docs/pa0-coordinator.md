# PA0 协调服务与出站节点

协调服务、节点配对／短期凭据、Mac 轮询、飞书和 [IP PWA](pa0-pwa.md) 已部署，真实用户登录与搜索均验证通过。当前仅显示授权元数据；正文证据传输、加密备份和真实 ROG 联调未完成，完整 PA0 未验收。

## 协调协议

协调库与索引库分开。每次搜索保存用户提交的查询、渠道、结果上限、幂等键和创建时间，并为配置的节点分别创建工作。查询是用户输入，需由已认证入口提交；此版本仅允许服务器本机 CLI 提交，不提供公网管理 API。节点凭据、配对码、会话 Token 只保存 SHA-256 摘要，不保存来源正文或摘录。普通任务、元数据结果和计数审计保留 180 天；每次打开协调库时清理到期记录。审计不含查询明文、标题或路径。

| API | 认证与行为 |
|---|---|
| `POST /v1/enroll` | 一次性配对码，有效 10 分钟，绑定预配置的节点；节点先在系统凭据库保存随机凭据，再注册 |
| `POST /v1/session` | 节点长期凭据换取 5 分钟会话；换发会话或重新配对使旧会话失效 |
| `POST /v1/poll` | Bearer 会话；更新心跳、同步本机政策摘要、原子领取一项工作 |
| `POST /v1/complete` | Bearer 会话；验证节点身份、任务租约及元数据字段后完成或等待来源恢复 |

HTTP 服务固定监听 `127.0.0.1`，无跨源许可，不记录请求日志。正文上限 512 KiB；禁止 chunked 输入。节点不跟随重定向、不使用环境 HTTP 代理。HTTPS 使用系统证书验证；不提供跳过证书验证选项。没有公网节点管理端点、来源配置写入端点或完整原文传输端点。

每项工作有随机租约，默认 120 秒。同节点的有效租约只能由一次领取产生；过期结果不接受，下一次轮询重新领取。成功结果重传时仅接受同一租约、相同结果，避免丢失回执导致重复完成事件。本机完成 outbox 在发送前持久化；进程重启后重传，重传前重新检查来源政策及文档当前版本。过期租约 outbox 丢弃，由任务重新领取。

90 秒无心跳视为离线。已完成的元数据结果保留为搜索快照，同时展示节点当前离线状态。未完成的节点明确列在 `waiting_nodes`，返回 `partial: true`，包括已完成但零命中的节点；不将零命中与尚未搜索混淆。来源离线时保留其他来源的部分结果，60 秒后重试；节点恢复后无需重新提交任务。恢复产生计数审计事件；向手机推送仍待飞书／PWA 通知接入。

来源配置变更、索引核对发现的版本／分类／可用性变化会改变节点政策摘要。下一次成功轮询清空该节点历史任务中的缓存元数据和旧租约，然后重新检索。离线时 VPS 不能立即获知本机政策变更。文档 frontmatter 分类变更需要显式／定期核对后同步；发送新的搜索和重传结果前仍检查原文，阻止未核对的新私密分类被发送。

结果严格限定 UUID、版本、标题、节点、来源及相对路径等元数据；拒绝正文、摘录、文件 URI、绝对路径或未知字段。private 默认禁止远程，只有单独精确授权的源级 `private_remote_metadata` 许可可展示私密元数据，仍不改分类／正文权限。排除规则及 `remote_metadata: false` 始终生效。现有来源为 Study／Life，旧 Note／Daily 已移除。

## 无域名的验证方式

用户当前 VPS 为 `mac@35.209.202.207:22`。可通过 SSH 隧道完成节点通信，公网只使用已有 SSH 入口：

```sh
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 \
  -o ServerAliveCountMax=3 -L 127.0.0.1:18765:127.0.0.1:8765 \
  mac@35.209.202.207 -p 22
```

在本机私密运行目录加入 `coordinator.json`，参见 [样例](../config/coordinator.example.json)。它只有服务地址及传输类型，没有密钥。仅允许显式标记 `ssh_tunnel` 的 `http://127.0.0.1:端口`；公网 HTTP 被拒绝。隧道需要单独维持，断开后节点保留工作并重试。它不提供手机 PWA、独立用户 Web 认证或公网 HTTPS；这些仍属于后续部署。

服务器独立 systemd 单元见 [部署配置](../deploy/personal-asis-coordinator.service)，以 `mac` 运行，源码为 `/home/mac/personal-asis`，运行库为 `/home/mac/.local/share/personal-asis-coordinator`。当前仅配置生产 `mac`；接入 ROG 时在服务及管理命令中加入 `--nodes mac rog`。协调服务独立运行，飞书使用现有 AstrBot 的受限插件，不复用其模型管线。

```sh
# 以下在 VPS 执行；首次配对的输出是敏感短效码，不进入日志或聊天
scripts/asis --home /home/mac/.local/share/personal-asis-coordinator \
  coordinator pair --nodes mac --node-id mac

# 以下在 Mac 执行；配对码从终端隐藏输入，节点凭据存入 Keychain
scripts/asis node enroll
scripts/asis node poll

# 以下在 VPS 执行；幂等键由调用方保留，重试必须使用同一键
scripts/asis --home /home/mac/.local/share/personal-asis-coordinator \
  coordinator submit --nodes mac --query "芯片" --request-id unique-request-1
scripts/asis --home /home/mac/.local/share/personal-asis-coordinator \
  coordinator task --nodes mac --task-id TASK_UUID
scripts/asis --home /home/mac/.local/share/personal-asis-coordinator \
  coordinator audit --nodes mac
```

Mac 已有 launchd daemon 读取 `coordinator.json` 后每 30 秒轮询。删除该文件停止新的轮询；卸载服务保留本机状态。系统凭据库未解锁或不可用时明确失败，不退回明文凭据文件。Linux 节点支持 `secret-tool` 和 Secret Service；WSL 的实际凭据库及用户服务仍需现场配置验证。

Mac 常驻隧道已安装为 `local.personal-asis.tunnel`，随登录启动，断线后由 launchd 有界间隔重启。维护命令：

```sh
scripts/asis tunnel install --host mac@35.209.202.207
scripts/asis tunnel uninstall
```

隧道只监听 `127.0.0.1:18765`；SSH 仍使用本机原有凭据和服务器主机身份核验。它与索引服务分别管理，卸载隧道不删除节点凭据或索引。

仓库提供 `python3 scripts/deploy-coordinator` 部署入口：仅打包源码、合成测试和单元配置；SSH 有 45 秒单次超时及三次上限；服务器先通过合成测试再安装／重启协调服务，任何远程测试或安装失败都会停止。不修改已有 AstrBot 单元。

配对操作可轮换已注册节点的长期凭据。`coordinator revoke --node-id mac` 禁用节点，删除会话、配对码及缓存结果；重新启用目前需由服务器管理员本机调整节点注册状态，不允许节点自己恢复权限。

## 验证边界

新增合成测试覆盖单次配对、配对／会话过期、会话轮换、领取串行化、租约过期、完成幂等、协调库／节点 outbox 重启恢复、双节点副本聚合、来源离线重试、政策撤销以及严格披露过滤。真实 HTTP 测试仅监听临时回环端口，需要运行环境允许本机 socket。

### 本次记录（2026-10-13）

- Mac Python 3.14.5、SQLite 3.53.1。全套 **44 项合成测试通过**，含真实回环 HTTP、双节点合成聚合、并发领取、重启恢复、分类变更撤销及 launchd 轮询接入。文档相对链接与 `git diff --check` 通过。
- Mac 的真实索引状态仍为 `Note` 152 个、`Daily` 26 个 Markdown，均 ready；已重装／重载 `local.personal-asis.mac`，现场 `launchctl` 显示 running。服务使用本次代码，原有读取／远程权限保持不变。
- VPS 只读登录成功过，Python 3.13.5、SQLite 3.46.1，FTS5 trigram 可用；现有 `astrbot.service` 为 active/running，`8765` 未监听。已具备无交互 sudo，用户服务管理器为 running。
- 后续 SSH/SCP 反复在 banner／密钥交换前超时或被服务端关闭；三次有界部署尝试均返回 255。**未确认代码上传、systemd 单元安装或服务启动，不能报告 VPS 协调服务已上线**。SSH 故障发生在认证前，尚无证据表明登录密钥有误。
- 未创建真实来源的 `coordinator.json`、未对 VPS 发送真实资料元数据、未修改原有来源权限。Mac↔VPS 配对、Keychain 实机操作、生产 HTTPS、飞书和 ROG 均未验证。源码已有实现不能替代这些现场结果。
- 用户称已有飞书机器人部署在 VPS；当前仅确认 AstrBot 进程，尚未读取到飞书适配器配置。需核对托管关系和独立适配／沿用既有入口的选择，再接入事件校验、授权用户白名单和受限结果通知。

### 代理恢复后的部署记录（2026-10-13）

- 用户说明前述连接失败源于代理，并确认飞书由 AstrBot 承载。随后 SSH 恢复；部署脚本在 VPS 完成合成测试并安装 `personal-asis-coordinator.service`。服务为 active，现场仅监听 `127.0.0.1:8765`。
- Mac 已创建私密 `coordinator.json`，配对凭据存入 Keychain；`node poll` 实际返回成功，常驻 SSH 隧道和 Mac 节点均已重载为 running。真实来源的读取与远程元数据权限没有扩大。
- 使用 Mac 上隔离合成索引和临时验证节点完成真正的 Mac↔VPS 搜索：VPS 先展示离线等待，节点恢复后自动领取并完成；生产 Mac 也自动完成自己的任务。仅合成标题／路径／UUID／哈希进入结果，私密标题、正文、文件 URI 和绝对路径没有输出。验证结束后已撤销临时节点，生产只注册 Mac。
- 最终标准库应用套件 50 项通过；另外 3 项 AstrBot 专用测试在基础解释器中跳过，已用 VPS 实际 AstrBot 4.27.3／Python 3.12 解释器单独运行并全部通过。共 53 项验证，不能把专用测试的跳过算成通过。
- 已将 PA0 飞书插件安装到现有 AstrBot 并重启服务；现场日志确认插件加载及 `on_astrbot_loaded` 钩子启动，两个 VPS 服务均 active，无 PA0 错误记录。私聊绑定和真实飞书收发仍需用户操作验证。
- 用户随后完成真实飞书私聊绑定并发起搜索。服务器核验绑定有效、任务 completed、partial 为 false、无等待节点；该任务两项投递均为 sent，表示飞书 API 成功接收状态及完成消息。真实 Note 远程元数据未获明确授权、仍关闭，本次获准远程命中为零；这不等于本机 Note 没有相关资料。未在仓库保存实际 open_id、查询、任务 ID 或结果内容。
- PWA、真实 ROG 协作、实际长时间休眠／唤醒及加密备份未完成，完整 PA0 尚未验收。

### 无域名 PWA 的后续入口

已核查 [Let's Encrypt 2026-03-11 官方说明](https://letsencrypt.org/2026/03/11/shorter-certs-certbot/)：IP 地址可申请短效证书，Certbot 5.4+ 支持 IP `webroot` 验证，使用 `--ip-address` 与 `shortlived` profile；证书约六天，必须自动续期并在更新后重载 Web 服务。因此 PWA 不必等购买域名。

当前 VPS 尚未安装 Certbot／nginx，80／443 无监听。这里只核查了依赖及端口占用，未开放防火墙、签发证书或部署 PWA。下一切片需落实独立强用户认证、IP HTTPS／自动续期、控制台与满足原文不在 VPS 持久化要求的证据传输；现有 SSH 隧道继续只服务节点通信。

### 新来源与 PWA 切片现场记录

用户本轮授权新的 Study／Life 本机只读目录，以及 Study 非私密元数据和 Life 包括私密日记／健康条目在内的标题、来源、相对路径提示远程展示。Life 保持 private，许可不扩展到正文、摘录、云模型或其他根目录。本机索引新增 446 个 Markdown；索引前后所有 1803 个来源文件的大小、mtime、ctime 不变。按随后指令清除旧 Note／Daily 的配置和索引记录，保留原文件，目前只留两项新来源。真实配置和精确许可审计只保存在本机私密运行目录。

IP PWA 已完成 nginx／受信任 IP 证书／自动续期部署，测试签发和生产 dry-run 续期均通过。公网 443 初始被阻断；VM 服务账号缺 Compute scope，用户通过 Cloud Shell 放行专用 VM 标签的 TCP 443 后，公网正常证书验证通过。用户设置静态密码并完成实际 PWA 搜索，返回 Study／Life 的 20 项获准元数据，匿名数据请求仍 401。完整状态、服务管理与限制见 [PWA 说明](pa0-pwa.md)。
