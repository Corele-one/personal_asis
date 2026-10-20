# PA0 私有 IP PWA

> 2026-10-20：本文归入远程兼容资料；VPS／机器人／远程通信暂缓，当前开发以[本机 Pi 主线](local-agent-focus.md)为准。本文版本与验收均限原日期，不能据此推断当前线上状态。


PA0 已验收，入口为 [https://35.209.202.207/](https://35.209.202.207/)，当前仅检索 Mac。节点状态不再列出已停用 ROG，旧搜索不再等待或显示 ROG 的历史缓存与覆盖缺口。获准正文按需加密阅读，私密内容通过新增独立阅读许可检查；实际范围和验证见[持续授权](private-data-authority.md)。详见 [Mac 单节点运行](pa0-mac-only.md) 与 [文本及恢复](pa0-text.md)。

## 使用流程

登录后提交搜索，查看任务状态和结果；从飞书任务链接进入时，登录后打开对应任务。有阅读资格的结果可请求摘录／正文，按分段继续阅读。Mac 必须在线；私密条目在独立阅读许可有效时可加密打开正文。详细限制见 [加密阅读](pa0-text.md)。

## 登录与部署

用户在本轮明确选择 IP 地址和静态密码登录。`pwa.json` 仅在 VPS 私密运行目录维护，配置 `origin: https://35.209.202.207` 和 `auth_method: password`；不是远程来源配置入口。密码由用户在设置页面输入，至少 14 个字符；服务器只保存随机盐及 scrypt 摘要。初次设置使用服务器生成、有效一小时的一次性令牌；令牌放在 URL fragment，浏览器读取后移除，不进入服务器请求路径或 Referer。没有默认密码，也不把密码写进代码或聊天。

会话 Token 只在 `Secure; HttpOnly; SameSite=Strict; Path=/` 的 `__Host-asis` Cookie 中返回，服务器保存摘要。会话最长 12 小时、30 分钟无活动过期；退出撤销该会话，管理员重设撤销全部会话。登录按客户端限制五次失败／15 分钟，并有 nginx 限流；所有状态变更要求匹配 HTTPS Origin，已登录操作另验证 CSRF。页面使用 CSP、禁止嵌入及 no-store；服务 Worker 只缓存静态外壳，不缓存 API、登录响应或私人搜索结果。

Markdown 索引、协调及 PWA 服务器使用标准库；本机加密阅读依赖见文本说明。VPS 使用 nginx 1.26.3 和隔离虚拟环境内的 Certbot 5.8.0 管理 HTTPS；飞书继续使用现有 AstrBot 的 SDK。服务：

| 单元 | 用途 |
|---|---|
| `personal-asis-coordinator.service` | 节点协议，`127.0.0.1:8765` |
| `personal-asis-pwa.service` | Web 控制台，`127.0.0.1:8766` |
| `nginx.service` | 80 端口 ACME 验证及 443 HTTPS 反向代理 |
| `personal-asis-cert-renew.timer` | 每日两次续期检查，错过的检查在恢复后补执行 |

IP 证书的签发流程依据 [Let's Encrypt 官方 IP 文档](https://letsencrypt.org/2026/03/11/shorter-certs-certbot/)。生产证书的 IP SAN 为 `35.209.202.207`，使用短效证书及自动续期；实际到期时间以服务器当前证书为准，不将首次签发的日期当作长期有效期。本轮测试环境签发与生产证书 `renew --dry-run` 均通过，续期 deploy hook 会重载 nginx。测试证书已移除，生产入口只使用受信任生产证书，未关闭证书校验。

服务器本机管理：

```sh
scripts/asis --home /home/mac/.local/share/personal-asis-coordinator pwa bootstrap
scripts/asis --home /home/mac/.local/share/personal-asis-coordinator pwa serve

# 用户忘记密码时由服务器管理员重设；会撤销所有旧 Web 会话
scripts/asis --home /home/mac/.local/share/personal-asis-coordinator pwa bootstrap --reset
sudo systemctl status personal-asis-pwa.service nginx
sudo systemctl list-timers personal-asis-cert-renew.timer
sudo /opt/personal-asis-certbot/bin/certbot renew --dry-run
```

历史过程见 [PA0 部署历史](archive/pa0-rollout-2026-10.md)，当前结果以 [最终验收](pa0-acceptance.md) 为准。

## 后续 PA1 分析入口

本人控制台已增加「结合资料分析」及可选「按需公开研究」，不改变 PA0 搜索与正文阅读的独立权限。临时解密密钥仅在当前页面，关闭不取消已开始的模型调用；使用与验证见 [PA1](pa1-acceptance.md)。

本人控制台现已新增「按需 Agent」及状态、暂停、恢复、取消，使用与独立验收见 [本人渠道 Agent](agent-channels.md)。原 PA1 分析和 PA0 搜索入口继续保留。
