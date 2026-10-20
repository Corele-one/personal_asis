# Mac 平台读写

Mac 原生 Pi 保留原有读取方式；写入使用 `source_write`，不直接开放未知平台写工具。扩展在 Pi 的原生确认 UI 中显示完整平台、操作、目标和参数；没有交互 UI 时拒绝执行。确认计划五分钟有效、绑定内容哈希，开始外部请求前持久占位；一次计划不重复执行，网络失败／崩溃按未知处理，先核对平台。

| 平台 | 当前写入操作 | 参数 |
|---|---|---|
| WUCAI 中国区 | `append_diary` | `content`，追加今天 |
| WUCAI 中国区 | `update_article_note` | `note_idx`, `note` |
| WUCAI 中国区 | `set_article_status` | `note_idx`, `status`，仅 inbox/later/archive |
| 小红书 | `like_feed` | `feed_id`, `xsec_token`, `unlike` |
| 小红书 | `favorite_feed` | `feed_id`, `xsec_token`, `unfavorite` |
| 小红书 | `post_comment_to_feed` | `feed_id`, `xsec_token`, `content` |
| 私人 Dashboard | `publish_summary` | `title`, `content`，只分享这次本人确认的Mac摘要 |

小红书使用固定 v2.5.5 MCP 加入上述三个写工具的本机构建，仍使用 Keychain 会话与独立 loopback 鉴权，原生 MCP 配置只直接暴露已知读工具；写工具由确认适配器调用。禁止自动登录、读取浏览器 Cookie 或绕过验证码。点赞／收藏是明确开关而非自动切换；失败不连续点击重试。

多账号时，小红书请求须在顶层提供 `account` 标识（例如 `default`、`second`）。原生 UI 显示配置的账号名和标识，内容哈希绑定该标识；执行使用对应端口及钥匙串鉴权。未明确账号的旧计划在多账号启用后停止执行。账号不明确时先询问用户，不能凭收藏或旧缓存替用户选择身份。账号配置见[小红书接入](xiaohongshu-setup.md)。

WUCAI 操作来自[官方接入](https://doc.wucai.site/tools/openclaw.html)、[官方接口列表](https://github.com/makediff/wucai-openclaw/blob/main/SKILL.md)与[官方请求示例](https://github.com/makediff/wucai-openclaw/blob/main/scripts/wucai_api.py)。小红书工具参数按[固定版本实现](https://github.com/xpzouying/xiaohongshu-mcp/blob/v2.5.5/mcp_server.go)核对。已有读取适配器仍拒绝写操作；写入许可不从缓存自动继承。

当前没有发布图文／视频、修改社交身份、删除平台内容、任意图片下载或通用浏览器写入。Obsidian 的普通编辑由 Pi 原生工具在显示目标／改动并获确认后完成；日记同步由独立 `pi_sync` 命令的终端确认流程执行。

这些检查不把原生 Pi 变成 OS 沙箱，也不覆盖手动绕过接口的 shell 操作。真实平台写入未作为部署测试执行。原生 UI 扩展／模拟防重与平台账户真实验收分别记录在[状态](project-status.md)。

看板发布使用 `source=dashboard`，固定SSH接口发送确切标题／正文。只有确认后上传，不读整库，不从本机文件参数自动读正文；看板保留最近一份摘要，与自动同步的状态元数据分开。
