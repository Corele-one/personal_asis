# PA0 飞书接入

状态：已完成真实私聊绑定、搜索收发及实际 SDK 接口验证，PA0 已验收。本文维护使用命令和渠道边界；结果见 [最终验收](pa0-acceptance.md)。

用户后续确认的[持续授权](private-data-authority.md)允许本人私聊接收私密分析／相关摘录，以及已启用工作的私密主动通知；PA0 搜索维持下述元数据能力；本人 PA1 分析／研究命令已另行交付，见本文末尾和 [验收](pa1-acceptance.md)。远程权限管理入口尚未交付。

用户已确认 VPS 上的飞书机器人由 AstrBot 承载。本切片复用现有飞书传输，助手的任务权威、索引、来源政策及状态仍属于 Personal Asis；AstrBot 不负责 PA0 推理或资料存储。它不增加 QQ 入口，也不接入 AstrBot 的模型、对话记忆或其他业务插件。

## 接入边界

插件位于 [integrations/astrbot_plugin_personal_asis](../integrations/astrbot_plugin_personal_asis/main.py)。参考 [官方插件文档](https://docs.astrbot.app/dev/star/plugin-new.html) 与 [事件传播文档](https://docs.astrbot.app/dev/star/guides/listen-message-event.html)，并以 VPS 实际安装的接口测试为准。

当前现有飞书适配器为 `lark` 的 `socket` 模式：应用凭据由 AstrBot 原有配置管理，通过飞书 SDK 的 TLS WebSocket 接收平台事件；PA0 不复制应用密钥，也不开放新的 webhook。插件只接受这个已认证长连接上的纯文本私聊。Webhook 模式、群聊、引用消息、其他平台和未绑定用户均拒绝。

`/asis` 前缀由优先级 10000 的正则过滤器匹配，进入插件后立即停止事件传播并关闭默认模型请求；包括拒绝的请求也不回落到模型。普通聊天不匹配这个过滤器，保持既有行为。生产部署前用实际 AstrBot 解释器验证这些接口；既有框架在过滤器执行前可能记录收到的查询。PA0 本身只记录错误类型，不记录查询、标题、路径或正文。

插件与现有其他插件共享进程，并非隔离沙箱。此处权限边界由节点本机来源政策、严格元数据结果协议、单用户私聊绑定及事件拦截共同执行。饮食、作息、journal 和附件采集不在本切片范围内，不应通过 `/asis` 提交。

部署沿用 VPS 现有 AstrBot 4.27.3／Python 3.12 和 lark-oapi SDK，不给本机索引核心增加第三方依赖。先更新协调代码，再使用 AstrBot 的解释器运行专用测试并复制插件代码，最后重启现有服务：

```sh
# 在项目根目录更新 VPS 源码／协调服务
python3 scripts/deploy-coordinator

# 以下在 VPS 项目目录执行
PYTHONPATH=src /home/mac/.local/share/uv/tools/astrbot/bin/python \
  -m unittest discover -s tests -p test_astrbot_plugin.py -v
cp -R integrations/astrbot_plugin_personal_asis/. \
  /home/mac/astrbot/data/plugins/astrbot_plugin_personal_asis/
sudo systemctl restart astrbot.service
systemctl is-active astrbot.service personal-asis-coordinator.service
```

代码目录只放插件文件；绑定、任务路由和投递状态位于协调服务私密运行目录。更新插件不复制运行数据库或飞书应用密钥。

## 用户绑定与命令

服务器本机管理命令生成 10 分钟一次性绑定码，并绑定已配置的飞书平台 ID：

```sh
scripts/asis --home /home/mac/.local/share/personal-asis-coordinator \
  feishu pair --platform-id ACTUAL_LARK_PLATFORM_ID
```

用户在现有飞书机器人私聊发送：

```text
/asis bind 一次性绑定码
/asis search 芯片
/asis status 搜索任务编号
```

只有持有短效码的私聊发送者会成为授权 `open_id`。重复使用、过期、错误平台或群聊不能绑定；重新绑定后旧账号的任务通知路由失效。没有绑定时不开放搜索或状态读取。绑定码和实际 `open_id` 不进入仓库。

搜索使用飞书消息 ID 的摘要作为幂等键，重复事件不会新建任务。收到后返回状态，节点完成或恢复后补充获准元数据。当前 Study 非私密元数据与明确授权的 Life 私密元数据可显示；不显示正文、摘录、绝对路径、文件 URI 或完整证据卡片。私密许可只限授权来源，未授权私密条目及排除规则仍优先。旧 Note／Daily 测试来源已移除。

VPS 当前仅启用生产 Mac，ROG 的停用注册不会参与结果或等待。部分结果与等待节点明确展示。PWA 已启用，摘要包含登录控制台的任务深链接；未登录不能读取任务元数据。

## 通知可靠性

任务路由与发送状态单独存入 `feishu.sqlite3`，不保存查询或消息正文。通知从当前获准协调元数据构建，先持久化发送状态再调用飞书 API，每次通知使用确定的 UUID。完成回执丢失、进程重启或 API 超时时，状态保留为 `unknown`／`sending`，不会盲目重复外部发送；明确失败保留为 `failed`。节点后续产生新的结果可以形成新的通知。

用户用 `/asis status 任务编号` 主动查看当前状态，并可见此前通知失败或结果未知的提示。服务器通过以下命令检查投递状态，不回显查询或正文：

```sh
scripts/asis --home /home/mac/.local/share/personal-asis-coordinator feishu audit
```

普通任务路由和投递状态保留 180 天；绑定身份持续保留到本机重新绑定或管理员撤销。自动重试结果未知的外部发送、健康采集和模型分析均不属于此实现。

## 实际验收

核心合成测试覆盖一次性绑定、有效期、平台绑定、单用户白名单、消息幂等、任务权限、摘要字段白名单、完成通知与发送结果未知时防重。另使用 VPS 原有 AstrBot 解释器测试真实插件装饰器、SDK 导入、模型回落阻断、群聊／其他平台拒绝、普通消息不变和重复请求防重，发送器全部为合成替身，不对飞书发测试消息。

真实飞书绑定和用户搜索已通过；本轮专用 3 项检查也在实际 SDK 解释器中通过。自动化发送器使用合成替身；实际收发证据与整体 PA0 结论见最终验收，不把接口模拟当作平台收发。

历史过程见 [PA0 部署历史](archive/pa0-rollout-2026-10.md)，当前结果以 [最终验收](pa0-acceptance.md) 为准。

## 后续 PA1 命令

现有 PA0 搜索仍为元数据固定输出；本人私聊另提供 `/asis analyze`、`/asis research` 和分析状态，参数、权限与实际验收见 [PA1](pa1-acceptance.md)。分析不经过 AstrBot 默认模型流；模型和来源检查在 Mac 执行，VPS 不持久化回答或摘录。

## 按需 Agent

本人私聊现已增加 `/asis agent 来源ID | 问题`、`agent-status`、`pause|stop|resume|cancel`。执行、来源许可与模型预算仍在 Mac，飞书收件／最终回执分别防重，具体使用和实际验证见 [本人渠道 Agent](agent-channels.md)。

## 交互卡片入口

本人私聊发送 `/asis` 可打开[助手卡片](feishu-cards.md)，选择角色、资料范围并提交问题，结果及状态／暂停／恢复／取消在原卡片更新。原文字搜索与分析命令继续保留。
