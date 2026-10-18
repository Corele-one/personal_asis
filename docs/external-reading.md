# 首批外部阅读信源：WUCAI 与 Folo

2026-10-16当前状态：WUCAI中国区、Folo和独立小红书MCP已完成真实只读接通。新增三条Folo普通订阅及MCP会话／服务重启验证见[最新验收](validation/xhs-mcp-feeds-20261016.json)；配置见[接入记录](external-reading-setup.md)。下文最初切片中的零条目、未登录和旧发布状态是历史快照，不覆盖当前状态。完整历史、自动增量和平台删除同步仍未实现。

2026-10-16 Folo真实接通：Folo已完成本人浏览器登录，会话验证成功并仅存Mac钥匙串；订阅列表返回38项，当前时间线3条已入本机索引，收藏接口本次返回0条；单篇feed_content、实际游标续页和特定条目搜索通过。完整历史及有内容的收藏分页仍未验收。未新增模型／远程展示许可或后台工作，知乎／小红书仍待后续登录，公众号不再推进。Mac发布 `reading-folo-5450f19d0ed1dc1c`，380项回归364通过、16跳过，见[现场验收](validation/folo-live-20261016.json)。

2026-10-16真实续验：用户已录入WUCAI中国区凭据，实际读取近期和2026-07-05—18历史窗口，旧记录详情及next_cursor续页成功；24条已进入本机缓存并验证搜索，整库历史尚未回溯。真实字段映射／空划线／详情包装已修复，见[现场验收](validation/wucai-live-20261016.json)。官方14天限制是单次日期跨度，可指定历史日期，不是只读最近14天；已取得文章信息、划线和批注，不承诺剪藏全文。下文首批记录中的“凭据缺失／字段未验”仅保留当时状态。

2026-10-16续配：Folo CLI下载问题已解决，官方0.0.5已安装；另已准备知乎CLI、小红书MCP和公众号分享入口。按用户要求暂缓登录／授权／账户验证，当前状态见[续配说明](external-reading-setup.md)和[最新验收](validation/reading-connectors-20261016.json)。下文保留首批日期的安装／验收快照。

日期：2026-10-15。本轮交付本机只读适配器、分页检查点、出处／内容类型、30 天缓存与现有索引／PA1 的连接。用户选择 **WUCAI 中国区**，凭据稍后补充。**代码与合成验收不等于真实账户接通**；WUCAI 实际响应字段、会员条件及可读覆盖仍需 Token 就绪后核验，Folo 官方 CLI 尚未安装成功。知乎、小红书及公众号独立适配未在本切片实现。

## 能力与边界

| 来源 | 本轮实现 | 未验收／未实现 |
|---|---|---|
| WUCAI | 固定区域 HTTPS 端点；官方 `list_articles`／`get_article_details` 读取协议；日期自动分为最多 14 天的窗口；文章／划线／页面笔记分开呈现 | 真实响应字段与分页、会员权限、账户历史覆盖。没有读取日记，不承诺剪藏全文 |
| Folo | 官方 CLI 的时间线、收藏分页和文章详情；原样采用 CLI 的收藏游标；订阅列表只保留元数据，相关正文按需 `fetch` | 官方 CLI 安装／登录及账户返回范围；不承诺历史齐全，也不自动标记已读 |
| 本机检索 | `reading_wucai`／`reading_folo` 接入既有 Markdown 索引与 PA1；证据携带出处和内容类型；PA1 同一原始 URL 只选一条证据 | 新来源默认无模型许可、无本人远程展示许可；飞书／PWA 的来源选择和授权管理没有在本轮扩展 |
| 留存 | 普通缓存取得后 30 天失效；精选保留；单条遗忘和来源撤权；沿用既有向量／回答／Agent 会话清理 | 平台删除／移出收藏的全量差异同步、取消精选、代选规则、后台持续拉取 |

Folo 的 `feed_content` 只表示订阅端返回的内容，可能是摘要，不能标为完整原文。WUCAI 只把已知划线字段作为 `highlights_only`，未知全文字段不使用。未识别的响应结构拒绝入库并返回固定错误标识，不保存原始响应或 Token；无法核实分页时报告 `pagination_unverified`，不会把短页冒充完整覆盖。当前 WUCAI 字段映射基于公开协议候选，必须真实接通后才能声称已验证。

## 配置与凭据

在仓库根目录运行。生产服务必须先部署含 `reading_cache` 检查的新代码，才能将缓存接入生产来源；旧代码不识别新字段，不能依赖旧服务执行到期拒读。

```sh
scripts/asis reading configure --source wucai --region cn
scripts/asis reading configure --source folo
scripts/asis reading status --source wucai
scripts/asis reading status --source folo
```

`configure` 只注册本机来源，不请求平台。既有 Study／Life 权限保留。新文件默认 `unclassified`，以 private 处理；模型授权、远程元数据、正文和私密正文展示均不自动授予。来源参数保存在私密运行目录的清单中，不需要修改源码或把真实配置提交 Git。

WUCAI 中国区从[官方 Token 页面](https://marker.dotalk.cn/#/personSetting/openapi)取得以 `wct-` 开头的 OpenClaw 专用 Token。**不要把 Token 发到聊天里，也不要放进命令行参数**；在自己的交互终端输入：

```sh
scripts/asis reading key --source wucai
```

Folo也可使用 `scripts/asis reading login --source folo` 在官方浏览器完成登录并直接保存到系统凭据库，详见[安全登录入口](external-reading-setup.md#folo-本人浏览器登录)。

命令不回显，使用既有系统凭据库服务 `local.personal-asis.reading`，账号 `wucai:cn`；区域不能在同一缓存上切换。Folo 使用该凭据服务中的 `folo` 账号，通过子进程环境 `FOLO_TOKEN` 传给官方 CLI，不写参数、源码或日志。工具不会读取浏览器 Cookie 或代替用户登录。

Folo 官方仓库当前 `package.json` 标记 `0.0.5`；本轮对 npm 官方注册表的下载失败（连接重置／TLS 失败），**未核实 npm 当前已发布版本、未安装 CLI**。安装就绪后，用实际绝对路径配置，再在交互终端录入账户 Token：

```sh
scripts/asis reading configure --source folo --folo-cli /ABSOLUTE/PATH/TO/folo
scripts/asis reading key --source folo
```

调用固定官方地址 `https://api.folo.is`，只构造本切片允许的只读命令。没有开放 CLI 任意参数、平台收藏修改、标记已读、订阅修改或刷新 Feed。

## 首次真实读取与继续分页

建议先小范围核验字段、出处与覆盖，再增加页数。WUCAI 默认最近七天，Folo 默认全部订阅的当前可见时间线；以下每次最多读取两页：

```sh
scripts/asis reading sync --source wucai --since 2026-10-09 --until 2026-10-15 --max-pages 2
scripts/asis reading sync --source folo --stream subscriptions --max-pages 2
scripts/asis reading sync --source folo --stream selections --max-pages 2
```

出现 `page_limit` 后，对**相同流和相同日期范围**加 `--resume` 沿用检查点。WUCAI 可指定更早日期，自动拆分 14 天窗口；Folo 收藏按官方 CLI 返回的收藏时间游标继续，不用文章发表日期代替。Folo 暂不支持本命令的日期过滤，指定日期会明确拒绝。

```sh
scripts/asis reading sync --source wucai --since 2026-10-09 --until 2026-10-15 --max-pages 2 --resume
scripts/asis reading sync --source folo --stream selections --max-pages 2 --resume
scripts/asis reading fetch --source folo --item-id ENTRY_ID
scripts/asis search 搜索词
```

未带 `--resume` 从当前查询第一页重新核对；这不是后台增量调度。`visible_window_exhausted` 只表示平台对该窗口／流返回结束，`complete_account_history` 始终为 false；缺页、重复游标、未知分页和失败会显示为部分覆盖。某页失败后保留先前检查点，不跨过失败页。完整页面成功处理后才推进游标，重复拉取以平台条目 ID 覆盖而不重复建条目。

## 分类、模型与本人渠道

缓存正文每行标明作者原文、用户划线、用户批注或页面笔记。截取到行中间时，上下文仍有单独的 `reading_attribution`；收藏不代表认同，作者观点不作为用户经历。外部内容不能作为指令执行。订阅元数据不作为云模型的正文证据。

本机复核某个条目确属普通阅读资料后，可以修改该条目的分类；分类本身不授予模型或远程访问：

```sh
scripts/asis reading classify --source wucai --item-id NOTE_ID --classification normal
```

模型使用沿用 PA1 独立来源许可；本人远程展示也仍需独立许可。当前没有新增云模型调用或对新来源授予模型许可。平台返回新内容版本时重新置为未分类，避免旧普通分类扩展到新敏感内容。普通文章／批注的最小 MiMo 上下文原则仍见 [ADR 0028](adr/0028-allow-minimal-mimo-context-for-nonsensitive-reading-content.md)。不要为接入方便直接授权整个未分类账户为私密模型来源。

## 过期、遗忘与撤权

```sh
scripts/asis reading clean --source folo
scripts/asis reading forget --source wucai --item-id NOTE_ID
scripts/asis reading revoke --source wucai
```

普通缓存按正文取得时间到期；再次看到订阅元数据不会延长已取得正文的有效期，也不会覆盖正文。精选保留但可遗忘。`forget` 是本机明确排除，后续拉取不会悄悄重新加入；平台原记录不变。`revoke` 关闭该连接器的本机使用并清除缓存文件，重新 `configure` 才可启用；钥匙串项和必要防重／计费标记保留。没有开放“取消精选后仍可依规则代选”的界面或规则，此处遗忘不等于取消精选。

现有索引每次搜索、正文阅读、PA1 证据重核和历史复用都会检查清单的启用状态、有效期与缓存哈希；到期立即不可用，不依赖下一次索引核对。物理文件由显式清理、后续拉取及既有 PA1 维护周期清理；索引核对删除失效 FTS 内容，既有 PA1 清理移除相关向量与派生回答。没有新增定时器，也不声称在到期时刻已经清除所有磁盘／备份副本。

清单仅保存出处、条目身份、版本哈希、到达关系、分类和分页进展；正文在仓库外生成的缓存 Markdown 中。账户记录、私人路径、正文、缓存和凭据不进入 Git，不发给 VPS。部分分页不用于判断平台删除或取消收藏；平台端删除的自动发现和全量同步仍待后续切片。

## 验证与公开协议依据

- 专项合成测试见 [test_reading.py](../tests/test_reading.py)：只读边界、分页／恢复、窗口拆分、归因、普通分类和模型许可分离、去重、到期拒读、遗忘／撤权、派生证据失效及不保存凭据。
- 本轮部署和测试快照见 [验收记录](validation/reading-sources-20261015.json)。真实账户请求、Folo 实际 CLI 和手机端使用未验收；测试替身不算平台连通。
- [WUCAI 官方接入说明](https://doc.wucai.site/tools/openclaw.html)、[官方协议说明](https://github.com/makediff/wucai-openclaw/blob/main/SKILL.md)、[官方 API 示例代码](https://github.com/makediff/wucai-openclaw/blob/main/scripts/wucai_api.py)。
- [Folo 官方 CLI 说明](https://github.com/RSSNext/Folo/blob/dev/apps/cli/skill.md)、[时间线](https://github.com/RSSNext/Folo/blob/dev/apps/cli/src/commands/timeline.ts)、[收藏游标](https://github.com/RSSNext/Folo/blob/dev/apps/cli/src/commands/collection.ts)、[详情只读命令](https://github.com/RSSNext/Folo/blob/dev/apps/cli/src/commands/entry.ts)。
