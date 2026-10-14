# PA0 私有 IP PWA

当前仅检索 Mac。节点状态不再列出已停用 ROG，旧搜索不再等待或显示 ROG 的历史缓存与覆盖缺口。非私密摘录／正文的按需加密阅读、既有登录和飞书仍正常使用；Life 只按独立许可展示私密元数据。详见 [Mac 单节点运行](pa0-mac-only.md) 与 [文本及恢复](pa0-text.md)。

## 登录与部署

用户在本轮明确选择 IP 地址和静态密码登录。`pwa.json` 仅在 VPS 私密运行目录维护，配置 `origin: https://35.209.202.207` 和 `auth_method: password`；不是远程来源配置入口。密码由用户在设置页面输入，至少 14 个字符；服务器只保存随机盐及 scrypt 摘要。初次设置使用服务器生成、有效一小时的一次性令牌；令牌放在 URL fragment，浏览器读取后移除，不进入服务器请求路径或 Referer。没有默认密码，也不把密码写进代码或聊天。

会话 Token 只在 `Secure; HttpOnly; SameSite=Strict; Path=/` 的 `__Host-asis` Cookie 中返回，服务器保存摘要。会话最长 12 小时、30 分钟无活动过期；退出撤销该会话，管理员重设撤销全部会话。登录按客户端限制五次失败／15 分钟，并有 nginx 限流；所有状态变更要求匹配 HTTPS Origin，已登录操作另验证 CSRF。页面使用 CSP、禁止嵌入及 no-store；服务 Worker 只缓存静态外壳，不缓存 API、登录响应或私人搜索结果。

Core 与 PWA 仍无第三方 Python 运行依赖。VPS 使用 nginx 1.26.3 和隔离虚拟环境内的 Certbot 5.8.0 管理 HTTPS；飞书继续使用现有 AstrBot 的 SDK。服务：

| 单元 | 用途 |
|---|---|
| `personal-asis-coordinator.service` | 节点协议，`127.0.0.1:8765` |
| `personal-asis-pwa.service` | Web 控制台，`127.0.0.1:8766` |
| `nginx.service` | 80 端口 ACME 验证及 443 HTTPS 反向代理 |
| `personal-asis-cert-renew.timer` | 每日两次续期检查，错过的检查在恢复后补执行 |

IP 证书的签发流程依据 [Let's Encrypt 官方 IP 文档](https://letsencrypt.org/2026/03/11/shorter-certs-certbot/)。生产证书已经签发，IP SAN 为 `35.209.202.207`，本次有效期至 2026-10-20；短效证书必须自动续期，不能以一次签发代替持续维护。本轮测试环境签发与生产证书 `renew --dry-run` 均通过，续期 deploy hook 会重载 nginx。测试证书已移除，生产入口只使用受信任生产证书，未关闭证书校验。

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

## 首次部署与网络阻断记录（2026-10-13）

- 59 项标准库应用测试通过，另 3 项 AstrBot 专用测试在实际 SDK 解释器中通过，共 62 项。覆盖源级私密元数据许可、静态密码、初始化令牌、失败限流、会话撤销与过期、Origin／CSRF、未登录阻断、任务幂等及离线等待。动态验证码作为可选模块测试，实际部署按用户选择使用静态密码。
- 服务器本机使用正常证书验证访问 `https://35.209.202.207`、连接至本机 443，得到静态密码模式响应；nginx 和两个助手服务均运行。无 Cookie 的数据 API 由应用拒绝，回环 HTTP 测试中已验证 401。
- 公网 80 与 ACME 首先成功；首次调试时，Mac 命令行、Python、Chrome 和已配置代理访问公网 443 均失败，Chrome 为 `ERR_CONNECTION_CLOSED`。当时没有将本机 TLS 成功报告成公网可用；后续结果见下节。
- VM 属于 `virtual1-505703`／`remote-asst`／`us-central1-f`，当前网络标签为空；VM 服务账号的 OAuth scopes 不含 Compute 权限。`gcloud compute firewall-rules list` 实际返回 scope 不足，无法读改云防火墙。云层 443 入站规则是首要待核项，尚不能仅据客户端失败确认某条具体规则。
- 具备项目权限的 Cloud Shell 可运行 [专用规则脚本](../deploy/open-pwa-firewall.sh)，只给这台 VM 加标签并开放 TCP 443。命令依据 [官方防火墙 CLI](https://docs.cloud.google.com/sdk/gcloud/reference/compute/firewall-rules/create) 和 [实例标签 CLI](https://docs.cloud.google.com/sdk/gcloud/reference/compute/instances/add-tags)。用户随后完成了云层修改。
- 初始化和实际搜索当时待验证，后续由用户自己的操作及后台状态验证，未用 API 合成测试代替。

### 云防火墙放行后的现场结果

用户在具备项目权限的 Cloud Shell 执行专用标签及 TCP 443 放行命令后，Mac 公网 HTTPS 正常证书校验立即成功；此前的连接阻断定位至云端入站配置。未修改用户的代理规则。用户已用一次性设置链接设置静态密码并实际发起 PWA 搜索：账号初始化完成，任务 completed、无等待节点，返回 20 组／20 个来自 Study 与 Life 的元数据命中，均无正文、摘录或文件 URI。账号设置后再次从匿名公网客户端访问数据 API，仍返回 401。

以上初始化令牌、真实密码、会话、任务 ID、查询及实际结果不进入仓库。已登录浏览器可通过 `/#task=任务编号` 查看飞书深链接；链接本身不带登录凭据，未登录仍需认证。

最终补丁已通过标准库 59 项应用检查及 VPS 实际 AstrBot 环境的 3 项接口检查。原生浏览器界面检查期间用户正在操作 Chrome，自动操作因状态变化中止；未改浏览器／代理设置或输入用户密码。用户自己的真实设置和搜索及后台完成记录构成当前现场证据，桌面／手机视觉布局验收不以模拟截图冒充。
