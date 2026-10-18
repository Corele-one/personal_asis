# 小红书接入方式与使用范围

2026-10-16：当前后端为用户选择的独立MCP。本人手动导入会话后，首页2条、收藏2条、单篇 `note_text`、本机特定条目搜索和服务重启后会话复用均已实测。缓存共8条（含此前OpenCLI条目），精选2条。当前发布 `reading-mcp-e181642291535fcc`，见[验收记录](validation/xhs-mcp-feeds-20261016.json)。

## 当前运行方式

基于第三方 `xpzouying/xiaohongshu-mcp v2.5.5` 构建本地变体 `v2.5.5-asis-keychain-readonly`，不是小红书官方开放API。[构建脚本](../scripts/build-xhs-keychain.py)校验被修改的上游文件摘要；补丁涉及钥匙串存储、只读工具面、REST路由和专用浏览器缓存目录。本地二进制SHA-256为 `3e14e17dc61d2be337316a389605831d1c58eb1386b38a27012bcf7cf85ad352`，用于识别本地构建，不冒充上游签名。

服务 `local.personal-asis.xiaohongshu` 仅监听 `127.0.0.1:18060`。`/mcp` 有独立鉴权，未鉴权请求实测返回401；仅另保留健康检查，无REST平台操作路由。实际MCP握手为 `2024-11-05`。服务端只注册 `check_login_status`、`list_feeds`、`search_feeds`、`get_feed_detail`、`get_my_profile`，阅读适配器仅开放后四种内容读取。登录状态检查用于显式配置验收。通知、发布、评论、点赞、收藏修改及删除会话工具均不暴露。

独立Chromium和工具位于仓库外私密运行目录。平台会话及浏览器seed经匿名管道存入系统钥匙串，不写Cookie JSON；服务鉴权仅注入子进程环境，不进入plist、命令参数或日志。原始平台输出不写服务日志。详情访问参数也仅存钥匙串，证据链接与缓存排除 `xsec_token`。

OpenCLI1.8.6及Chrome扩展保留，当前未使用、不会自动回退。此前[OpenCLI实测](validation/xiaohongshu-live-20261016.json)为历史记录；Chrome登录不会自动更新独立MCP会话。

## 手动更新会话

登录失效时，本人在自己的浏览器中完成登录，用Cookie-Editor导出单行Header String，然后在自己的交互终端执行：

```sh
scripts/asis reading import-session --source xiaohongshu
```

隐藏输入后直接存入Mac钥匙串，不在聊天中发送Cookie。代理不读取浏览器凭据库或代替本人提交验证码。导入会保留既有浏览器seed，随后需重新验证登录状态和读取。

```sh
scripts/asis reading status --source xiaohongshu
scripts/asis reading sync --source xiaohongshu --stream subscriptions --max-pages 1 --page-size 2
scripts/asis reading sync --source xiaohongshu --stream selections --max-pages 1 --page-size 2
scripts/asis reading discover --source xiaohongshu --query '计算机系统' --page-size 2
scripts/asis reading fetch --source xiaohongshu --item-id NOTE_ID
```

`subscriptions`表示首页推荐，**不是完整关注动态流**；`selections`表示本人可见收藏。MCP适配支持显式 `--followed-only` 关键词筛选，其合成检查通过，本轮未做真实筛选验收。仅报告网页可见结果，历史分页为未知／部分覆盖，未回溯全量。正文标为 `note_text`，未做OCR、图片识别、视频下载或转写。遇到验证码、会话失效或风险提示即停止。

## 维护和权限

服务随本人登录启动，不定时抓取。受控重启先bootout，再bootstrap原plist并kickstart，让监督进程转发SIGTERM并等待子进程退出；不要强杀监督进程。安装入口 `reading mcp-install --source xiaohongshu --xhs-binary ABSOLUTE_BINARY_PATH` 应从正式发布环境运行。服务重启已实测；最新版整机重启／无人值守休眠未验收。

本机缓存默认未分类并按私密处理，普通缓存30天，个人精选单独保留。平台删除／移出收藏差异同步未实现。没有新增模型、远程元数据／正文许可或后台调度；账户接通不等于可自动交给模型。新增研究信源见[Folo信源说明](source-recommendations.md)。
