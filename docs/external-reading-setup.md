# 外部信源配置与接入记录

2026-10-16最新接入：小红书已切换到独立MCP，使用系统钥匙串保存会话与服务鉴权；首页2条、收藏2条、单篇正文、本机搜索和服务重启后会话复用均通过真实验证，缓存共8条（精选2条）。Folo已按用户选择新增arXiv cs.AR＋cs.DC、SIGARCH博客、LLVM发布三条普通订阅，均归“研究与工程”，订阅总数38→41，各读取2条元数据并入本机索引，Folo缓存共9条。Mac发布 `reading-mcp-e181642291535fcc`，395项回归379通过、16跳过；PA0、PA1、独立MCP和隧道运行正常。没有新增模型／远程许可或助手后台抓取；完整历史、完整关注流及平台删除同步未完成。知乎官方CLI停止推进，公众号不接。见[小红书说明](xiaohongshu-setup.md)、[研究信源](source-recommendations.md)和[本轮验收](validation/xhs-mcp-feeds-20261016.json)。

2026-10-16知乎官方CLI配置按用户反馈停止推进：用户很少收藏，核心需求是关注作者近期更新；不再申请／录入Secret或为收藏接通账户。作者RSS→Folo仅为待验证候选，见[需求与接口范围](zhihu-setup.md)。

前一Folo接入快照（2026-10-16，以下数量与等待状态仅属当时）：Folo已完成本人浏览器登录，会话验证成功并仅存Mac钥匙串；订阅列表返回38项，当前时间线3条已入本机索引，收藏接口本次返回0条；单篇feed_content、实际游标续页和特定条目搜索通过。完整历史及有内容的收藏分页仍未验收。未新增模型／远程展示许可或后台工作，知乎／小红书仍待后续登录，公众号不再推进。Mac发布 `reading-folo-5450f19d0ed1dc1c`，380项回归364通过、16跳过，见[现场验收](validation/folo-live-20261016.json)。

最初准备阶段（2026-10-16）：用户要求继续配置其他信源，授权／登录验证留到后续。已完成 Folo 官方 CLI 补装、知乎官方 CLI、小红书指定 MCP 的安装和只读适配，以及公众号分享链接入口；本轮不执行登录、扫码、凭据读取／验证或真实平台数据请求。部署与合成验收见[本轮记录](validation/reading-connectors-20261016.json)。此前 WUCAI 中国区配置保留。

## 最初准备阶段快照（后续接通以文首与专项说明为准）

| 来源 | 已准备 | 本轮暂缓 |
|---|---|---|
| Folo（安装阶段快照，真实接通见上） | 官方 npm `folocli@0.0.5` 已安装，禁用安装脚本；包完整性与官方注册表匹配，离线帮助可运行；已配置实际绝对路径 | 登录、Token 录入、时间线／收藏真实分页；`account_access=deferred` |
| 知乎 | 官方 CLI `0.6.1`，按官方发布清单校验大小、SHA-256、归档和版本；离线 version／capabilities／help 通过；收藏只读协议已适配 | Access Secret、账户验证及真实内容读取；`account_access=deferred` |
| 小红书 | 指定 `xpzouying/xiaohongshu-mcp` 的 `v2.5.5` 主程序及配套登录工具已安装；主程序仅运行 `-h`；MCP 端点配置为 `http://127.0.0.1:18060/mcp` | 登录工具、浏览器、Cookie、服务启动、登录状态检查和真实 MCP 平台调用全部暂缓；`account_access=deferred` |
| 公众号 | `wechat` 本机来源及显式分享链接解析已准备；继续支持文章经 WUCAI／Folo 到达 | 未提供真实文章链接，未请求公众号网页；不读取个人微信关注列表，不建立任意公众号更新抓取 |

工具在 Mac 私密运行目录的 `reading-tools/` 下，不加入 Git、不修改全局 PATH。小红书从指定项目的官方 HTTPS 固定版本资产下载并记录本机 SHA-256；发布页未提供独立校验清单，因此不把本机摘要描述为独立上游签名／校验。没有运行其登录二进制，也没有启动服务或浏览器。

## 暂缓状态的执行方式（历史准备阶段）

本机 `sources.yaml` 中新增 `reading_zhihu`、`reading_xiaohongshu`、`reading_wechat`，各自连接仓库外的缓存目录。Folo 继续使用既有 `reading_folo`。所有新来源默认未分类、仅本机使用；模型和远程元数据／正文权限没有扩大。当前飞书／PWA 的来源选择没有新增这些选项。

```sh
scripts/asis reading status --source folo
scripts/asis reading status --source zhihu
scripts/asis reading status --source xiaohongshu
scripts/asis reading status --source wechat
```

Folo／知乎／小红书显示 `account_access: deferred` 和 `credential: not_checked`。此时同步、详情和发现操作在读取凭据、执行 CLI 或发送网络请求之前停止，错误为 `reading_authorization_deferred`。状态命令只检查本机配置及工具文件，不判断“是否已登录”。公众号状态为公开分享无需账户凭据；没有明确文章链接不会发起请求。

`reading activate --source ...` 是后续本人明确启用账户读取的本机操作，**本轮未执行**。它不会录入凭据、验证账号、启动服务或授予模型许可，也不会启动自动同步。

## 各来源的真实能力边界

### 知乎

首版默认读取当前账号的近期收藏；指定收藏夹可使用服务返回的 `Paging.NextOffset` 严格续页，不按返回数量推算偏移。`favorites recent` 没有分页，不能冒充完整历史。收藏内容保留 `Summary` 并标为 `summary_only`；官方本人全文接口不能用于任意收藏内容，因此现有 `reading fetch` 会明确提示需要单独的本人原文 URL 路径，不假装取得全文。

官方 CLI 的 `me followees` 是关注用户列表，不是关注动态流；适配器保留只读命令，但没有将关注关系当作文章或已掌握知识入库。完整关注动态流尚未确认，当前不提供该能力。没有开放直答、知识库上传、升级、凭据修改等命令给阅读适配器。

后续授权时，使用[官方开放平台](https://developer.zhihu.com/profile)生成 Access Secret，在交互终端通过 `scripts/asis reading key --source zhihu` 录入项目系统凭据库，再按本人明确选择启用读取。项目将 Secret 仅注入官方 CLI 子进程的 `ZHIHU_ACCESS_SECRET`，不通过 argv、文件、模型或日志传递。当前没有执行这些步骤。

### 小红书

适配器仅允许 `list_feeds`、`search_feeds`、`get_feed_detail`、`get_my_profile(tab="fav")`。搜索可显式选择 `已关注`；首页推荐和已关注关键词搜索均不是完整关注时间线。当前网页实现只报告可见结果，分页状态为未知，不承诺全量收藏历史。

`list_notifications` 会清除未读标记，已排除；点赞、收藏修改、发帖、评论、登录二维码、登录检查及删除 Cookie 也不在适配器允许工具中。MCP 工具的 `ReadOnlyHint` 不作为放行依据。详情关闭额外评论滚动；正文、公共媒体链接分开记录，不进行 OCR、图片识别、视频下载或转写。带签名的媒体访问 URL 不持久保存。

以下为原准备方案，已由[钥匙串会话导入与独立MCP](xiaohongshu-setup.md)替代，不运行旧登录工具。原方案：服务只能显式绑定 `127.0.0.1:18060`，设置独立的 MCP 访问鉴权并存入系统凭据库；不要使用默认 `:18060` 公网监听。服务鉴权和平台登录是两件事。当前没有配置真实 Cookie、运行登录工具、读取浏览器 Cookie 或安装后台服务。详情所需的条目访问参数也仅存本机系统凭据库，缓存正文和原文 URL 不包含 `xsec_token`。

### 公众号

入口要求用户显式提供 `https://mp.weixin.qq.com/s/...` 或包含 `__biz/mid/idx/sn` 的公开文章链接。带登录参数如 `key`、`pass_ticket` 的链接拒绝；无 Cookie、无凭据读取、不跟随跳转、不绕过验证页。仅提取已取得网页的 `js_content` 文本；缺失时返回内容不可用或需要登录，不能把标题／验证页当作正文。

未来用户提供文章链接后，可以明确运行：

```sh
scripts/asis reading share --source wechat --url PUBLIC_ARTICLE_URL
```

分享属于个人精选，保持出处并接入既有本机索引；正文为 `page_text`，不据静态页面读取声称文章附件、动态内容和媒体均完整。当前未执行真实分享读取，也没有授权新来源进入模型或本人远程渠道。

## 验证与后续验收

新增15项专项合成检查，加上此前24项，共39项信源检查通过。覆盖授权暂缓时不触碰凭据和网络、只读命令与MCP工具限制、会话握手、知乎分页与摘要归因、小红书可见范围／条目访问参数、公众号链接约束和静态解析、既有索引及权限分离。完整套件372项：356通过、16因可选依赖跳过；独立发布包结果见[验收](validation/reading-connectors-20261016.json)。

测试中的平台返回和 MCP 服务为合成替身，不能替代真实授权后的字段／覆盖与稳定性验收。下一阶段才录入凭据、核验知乎额度和真实分页、完成小红书登录与回环服务、验证 Folo 账户及公众号实际可读链接。后台订阅、平台删除／取消精选同步、自动代选和远程授权管理仍未实现。

协议依据：[知乎官方说明包](https://developer-cdn.zhihu.com/zhihu-cli/releases/stable/skill/zhihu-cli-skill.zip)、[官方发布清单](https://developer-cdn.zhihu.com/zhihu-cli/releases/stable/manifest.json)、[小红书固定发布](https://github.com/xpzouying/xiaohongshu-mcp/releases/tag/v2.5.5)、[工具定义](https://github.com/xpzouying/xiaohongshu-mcp/blob/v2.5.5/mcp_server.go)、[Folo 官方 npm 包](https://www.npmjs.com/package/folocli)。

## Folo 本人浏览器登录

在已配置来源的 Mac 本机运行：

```sh
scripts/asis reading login --source folo
```

命令打开官方 `https://app.folo.is/login`，仅在 `127.0.0.1` 随机端口等待最多10分钟；本人在浏览器完成登录。回调核验随机 state、Host 和单次 Token，通过官方 `api.folo.is` 交换并验证会话后，将凭据存入系统钥匙串 `local.personal-asis.reading` / `folo`，随后启用本机只读访问。回调请求不写日志，网络跳转被拒绝，远端错误只返回固定标识。超时后可重新运行。

不要直接使用官方 `folo auth login`：0.0.5会将会话写入 `~/.folo/config.json`。本项目入口不读取或修改该配置，也不读取浏览器Cookie；会话凭据不进入参数、聊天、配置文件或诊断输出。协议依据为已安装的固定版本和[官方浏览器登录实现](https://github.com/RSSNext/Folo/blob/dev/apps/cli/src/browser-login.ts)。

登录成功不启动后台同步，也不授予模型或远程展示权限。后续先用少量时间线／收藏和单篇详情核验真实字段、游标与本机检索，再决定读取范围；未完成该步骤前不声称账户资料可用。
