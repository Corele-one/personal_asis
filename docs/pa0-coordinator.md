# PA0 协调服务与出站节点

PA0 已完成当前范围验收；当前仅启用 Mac 节点，ROG 已按用户选择停用。新搜索只派发 Mac，旧搜索也不等待或显示已停用 ROG 的缓存。停用保留节点长期凭据摘要及本机状态，撤销会话和远程结果；恢复需管理员显式启用。PWA／飞书正常使用，历史双节点验收见 [文本记录](pa0-text.md)，当前维护见 [Mac 单节点运行](pa0-mac-only.md)。

## 协调协议

协调库与索引库分开。每次搜索保存用户提交的查询、渠道、结果上限、幂等键和创建时间，并为配置的节点分别创建工作。查询由已认证 PWA、已绑定飞书私聊或服务器本机 CLI 提交；公网不开放节点注册管理或来源权限修改 API。节点凭据、配对码、会话 Token 只保存 SHA-256 摘要，不保存来源正文或摘录。普通任务、元数据结果和计数审计保留 180 天；每次打开协调库时清理到期记录。审计不含查询明文、标题或路径。

| API | 认证与行为 |
|---|---|
| `POST /v1/enroll` | 一次性配对码，有效 10 分钟，绑定预配置的节点；节点先在系统凭据库保存随机凭据，再注册 |
| `POST /v1/session` | 节点长期凭据换取 5 分钟会话；换发会话或重新配对使旧会话失效 |
| `POST /v1/poll` | Bearer 会话；更新心跳、同步本机政策摘要、原子领取一项工作 |
| `POST /v1/complete` | Bearer 会话；验证节点身份、任务租约及元数据字段后完成或等待来源恢复 |
| `POST /v1/evidence/poll` | Bearer 会话；领取仅在内存中的限时阅读请求 |
| `POST /v1/evidence/complete` | Bearer 会话；只接受严格密文封装或拒绝／过期状态，不持久化内容 |

HTTP 服务固定监听 `127.0.0.1`，无跨源许可，不记录请求日志。正文上限 512 KiB；禁止 chunked 输入。节点不跟随重定向、不使用环境 HTTP 代理。HTTPS 使用系统证书验证；不提供跳过证书验证选项。没有公网节点管理或来源配置写入端点。另有受限加密阅读领取／完成接口，无法按任意文件路径读原文。

每项工作有随机租约，默认 120 秒。同节点的有效租约只能由一次领取产生；过期结果不接受，下一次轮询重新领取。成功结果重传时仅接受同一租约、相同结果，避免丢失回执导致重复完成事件。本机完成 outbox 在发送前持久化；进程重启后重传，重传前重新检查来源政策及文档当前版本。过期租约 outbox 丢弃，由任务重新领取。

90 秒无心跳视为离线。已完成的元数据结果保留为搜索快照，同时展示节点当前离线状态。未完成的节点明确列在 `waiting_nodes`，返回 `partial: true`，包括已完成但零命中的节点；不将零命中与尚未搜索混淆。来源离线时保留其他来源的部分结果，60 秒后重试；节点恢复后无需重新提交任务。恢复产生计数审计事件；飞书通过受限通知路由补充结果，PWA 轮询任务状态。

来源配置变更、索引核对发现的版本／分类／可用性变化会改变节点政策摘要。下一次成功轮询清空该节点历史任务中的缓存元数据和旧租约，然后重新检索。离线时 VPS 不能立即获知本机政策变更。文档 frontmatter 分类变更需要显式／定期核对后同步；发送新的搜索和重传结果前仍检查原文，阻止未核对的新私密分类被发送。

搜索结果严格限定 UUID、版本、标题、节点、来源、相对路径及可选阅读资格等元数据；拒绝正文、摘录、文件 URI、绝对路径或未知字段。private 默认禁止远程，只有单独精确授权的源级 `private_remote_metadata` 许可可展示私密元数据，仍不改分类／正文权限。排除规则及 `remote_metadata: false` 始终生效。现有来源为 Study／Life，旧 Note／Daily 已移除。

## 当前部署与 SSH 节点通信

用户当前 VPS 为 `mac@35.209.202.207:22`。节点经既有 SSH 入口建立出站隧道；用户 PWA 另使用公网 HTTPS 443。手动隧道命令如下（常驻隧道运行时不重复占用同一端口）：

```sh
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 \
  -o ServerAliveCountMax=3 -L 127.0.0.1:18765:127.0.0.1:8765 \
  mac@35.209.202.207 -p 22
```

在本机私密运行目录加入 `coordinator.json`，参见 [样例](../config/coordinator.example.json)。它只有服务地址及传输类型，没有密钥。仅允许显式标记 `ssh_tunnel` 的 `http://127.0.0.1:端口`；公网 HTTP 被拒绝。隧道由单独 launchd 服务维持，断开后节点保留工作并重试。手机 PWA、独立登录和公网 HTTPS 已另行部署，见 [PWA 说明](pa0-pwa.md)。

服务器独立 systemd 单元见 [部署配置](../deploy/personal-asis-coordinator.service)，以 `mac` 运行，源码为 `/home/mac/personal-asis`，运行库为 `/home/mac/.local/share/personal-asis-coordinator`。当前启用节点仅为 `mac`；ROG 注册保留但 `enabled=0`，服务声明使用 `--nodes mac`。原 `rog.conf` drop-in 已改为 Mac 单节点，Mac 配对保留。协调服务独立运行，飞书使用现有 AstrBot 的受限插件，不复用其模型管线。

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

Mac 已有 launchd daemon 读取 `coordinator.json` 后每 30 秒轮询。删除该文件停止新的轮询；卸载服务保留本机状态。系统凭据库未解锁或不可用时明确失败，不退回明文凭据文件。普通 Linux 节点支持 `secret-tool` 和 Secret Service；WSL 使用 Windows 凭据管理器和 systemd 用户服务，已现场配置验证，见 [ROG 说明](pa0-rog.md)。

Mac 常驻隧道已安装为 `local.personal-asis.tunnel`，随登录启动，断线后由 launchd 有界间隔重启。维护命令：

```sh
scripts/asis tunnel install --host mac@35.209.202.207
scripts/asis tunnel uninstall
```

隧道只监听 `127.0.0.1:18765`；SSH 仍使用本机原有凭据和服务器主机身份核验。它与索引服务分别管理，卸载隧道不删除节点凭据或索引。

仓库提供 `python3 scripts/deploy-coordinator` 部署入口：仅打包源码、合成测试和单元配置；SSH 有 45 秒单次超时及三次上限；服务器先通过合成测试再安装／重启协调服务，任何远程测试或安装失败都会停止。不修改已有 AstrBot 单元。

配对操作可轮换已注册节点的长期凭据。`coordinator revoke --node-id mac` 禁用节点，删除会话、配对码及缓存结果；`coordinator enable --node-id mac` 可由服务器管理员本机显式启用，但被 revoke 的长期凭据仍需重新配对；节点不能自行恢复权限。`disable` 保留 enrollment，`enable`／`disable` 不提供公网管理入口。

历史过程见 [PA0 部署历史](archive/pa0-rollout-2026-10.md)，当前结果以 [最终验收](pa0-acceptance.md) 为准。
