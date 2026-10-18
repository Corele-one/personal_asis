# 信息来源接入讨论

2026-10-18联网续验：用户选择并本机录入DeepSeek Key，公开Search＋正文快照／本机校验＋MiMo引用已通过，发布 `web-live-cfb5d209d8b32103`；Exa真实查询可用，Jina匿名401仍未通过。仅公开查询与公开目标域名发送给搜索／DoH，不发个人原问题；Key在Mac钥匙串，不上VPS。此Provider不增加WUCAI/Folo/小红书的模型／远程许可，三账户仍未分类、仍按原边界。任意URL的DeepSeek Fetch未启用。当前记录见[真实联网续验](web-search-live-deployment.md)。

## 2026-10-18 分层状态核对

同日联网增量核对（未部署）：三账户仍 enabled，Keychain 凭据可取，仅说明凭据存在；未重读真实私人正文或重验登录有效性。WUCAI/Folo/小红书缓存仍24／9／8，MiMo providers与远程元数据／正文许可均为空。新[账户按需正文入口与 Web Provider](web-search-integration.md)已经在 checkout 串接：明确 item 经现有只读 detail→缓存／索引→V2归属正确 Chunk；模型、渠道分别过滤，默认不自动分类或新增许可。纯只读 V2 渠道不再额外要求 MiMo许可，实际展示仍须渠道与私密阅读授权；未部署，不能当作当前飞书已通。知乎不推进。

公开搜索复用 Exa MCP，元数据请求已成功核实当前 schema；Jina由 doctor识别，但本轮真实搜索／转换／MiMo生成未联调。Agent的公开发现摘要与读取正文分别建模，公开内容不进入账户缓存，账户内正文不发送给公开搜索。时效、错误、受控DNS／跳转、派生快照失效与独立费用记录见[联网集成](web-search-integration.md)。

下表保留同日 Retrieval V2 初次核对的范围：当次只读配置、manifest、活动索引与服务，未读取账号凭据或重新执行平台请求。认证／真实读取证据来自注明日期的 10-16 验收，不能推断当前会话仍有效；上述同日联网续作另核对凭据存在性。当前 checkout 含尚未进入 GitHub main 的已部署连接器代码；后面的旧配置快照保留其原日期。

| 来源 | 连接器／配置 | 认证与真实读取依据 | 当前缓存完整性 | 进入统一索引 | Agent 调用 | 模型／渠道披露 |
|---|---|---|---|---|---|---|
| Study／Life | 本机源已配置 | 当前来源／索引元数据可读；本轮不读取正文做评测 | 已有文本提取；不代表媒体全读 | 活动 267／184 | 现有 search_notes 可用 | 已有 MiMo 普通／私密及本人渠道许可 |
| WUCAI | 只读适配器、CN 已配置 | [10-16真实窗口／详情／分页](validation/wucai-live-20261016.json)，本轮未复验认证 | 24 条：3 highlights_only、21 metadata_only；无剪藏全文证明 | 活动 24；不等于 24 条正文 | 本机 reading CLI 可读；Pi 无 Live 工具，search_notes 仍受披露许可限制 | 当前无模型许可，无远程元数据／正文许可 |
| Folo | CLI 与账户源已配置 | [10-16登录／读取](validation/folo-live-20261016.json)及[订阅续验](validation/xhs-mcp-feeds-20261016.json)，本轮未复验认证 | 9 条：1 feed_content、8 metadata_only；feed_content 不等于原站全文 | 活动 9 | 同上 | 同上 |
| 小红书 | 指定独立 MCP 服务 running，受控只读适配器 | [10-16首页／收藏／详情／重启复用](validation/xhs-mcp-feeds-20261016.json)，本轮未复验会话 | 8 条：1 note_text、7 metadata_only；无 OCR／视频／全历史 | 活动 8 | 同上；没有把 MCP 所有工具注册到 Pi | 同上 |
| 知乎 | CLI／适配器配置存在 | account_access=deferred；按用户偏好停止官方收藏路线，未验证账户 | 0 | 无活动条目 | Pi 不可读取未接通内容 | 无模型／远程许可 |
| 公众号／分享 | 适配入口代码存在，用户不推进公众号 | 未验证账户或真实分享读取 | 0 | 无活动条目 | 代码存在不表示已启用实时读取 | 无模型／远程许可 |
| 公开研究 | 既有 research 显式 public_query／URL 路径 | 本轮只查上游公开仓库 | 临时公开研究结果，未当私人库同步 | 不自动进入个人统一索引 | 原按需研究入口；通用 Live 路由未实现 | 公开检索词与私人问题分开，继续按现有政策 |

## 统一身份、索引和同步边界

现有真实路径是 adapter → ReadingCache manifest／到达关系 → 本机生成 Markdown → PA0 文档索引；缓存不是来源权威。V2 在其后独立派生 Chunk sidecar，复用 manifest 的当前哈希、启用、精选／30 天过期和遗忘检查。版本／删除／撤权清理接入 `pa1 clean`（仅 sidecar 存在时）；没有自动增加抓取频率。

Source Item 保留平台 item_id 和到达路径，Document 保留 PA0 UUID／content_hash；同一原始作品以保守 canonical URL 识别，Chunk 分开寻址作者、划线与批注。同文不同来源的相同片段合并 aliases，不按到达次数计独立佐证；不同部分／版本不能冒充相同完整证据。字段、未知时间、部分正文、provider/channel 动态检查及 Indexed/Live 选择详见 [Retrieval V2](retrieval-v2.md)。未取得的 original_publisher、created_at、updated_at 留空；fetched_at 不替代 published_at，收藏不代表本人认同。

手动分页与清理已实现；自动增量调度、平台删除事件／tombstone 同步、全历史覆盖、别名跨站转载合并、原生划线 ID、Live 路由仍属 Phase 2。缓存过期后本轮拒读，未来重新获取也需获准读取和模型／渠道政策，不能自动扩大许可。

2026-10-16最新接入：小红书已切换到独立MCP，使用系统钥匙串保存会话与服务鉴权；首页2条、收藏2条、单篇正文、本机搜索和服务重启后会话复用均通过真实验证，缓存共8条（精选2条）。Folo已按用户选择新增arXiv cs.AR＋cs.DC、SIGARCH博客、LLVM发布三条普通订阅，均归“研究与工程”，订阅总数38→41，各读取2条元数据并入本机索引，Folo缓存共9条。Mac发布 `reading-mcp-e181642291535fcc`，395项回归379通过、16跳过；PA0、PA1、独立MCP和隧道运行正常。没有新增模型／远程许可或助手后台抓取；完整历史、完整关注流及平台删除同步未完成。知乎官方CLI停止推进，公众号不接。见[小红书说明](xiaohongshu-setup.md)、[研究信源](source-recommendations.md)和[本轮验收](validation/xhs-mcp-feeds-20261016.json)。

前一Folo接入快照（2026-10-16，以下数量与等待状态仅属当时）：Folo已完成本人浏览器登录，会话验证成功并仅存Mac钥匙串；订阅列表返回38项，当前时间线3条已入本机索引，收藏接口本次返回0条；单篇feed_content、实际游标续页和特定条目搜索通过。完整历史及有内容的收藏分页仍未验收。未新增模型／远程展示许可或后台工作，知乎／小红书仍待后续登录，公众号不再推进。Mac发布 `reading-folo-5450f19d0ed1dc1c`，380项回归364通过、16跳过，见[现场验收](validation/folo-live-20261016.json)。

前一WUCAI接入快照（2026-10-16）：用户改为逐项完成WUCAI、Folo、知乎、小红书，公众号不需要。WUCAI已凭真实凭据验证近期与约90天前的历史记录、详情和分页，本机缓存24条；单次最多14天并非只能看最近14天。其余账户仍待登录。完整历史覆盖／剪藏全文仍未验收，见[最新记录](validation/wucai-live-20261016.json)。下段为前一配置切片的快照。

状态（2026-10-16）：WUCAI／Folo只读协议、本机缓存和既有索引已部署；WUCAI中国区保留。现已补装Folo官方CLI，安装知乎官方CLI及指定小红书MCP，并实现知乎收藏、小红书受控MCP和公众号显式分享入口。按用户要求，Folo／知乎／小红书账户访问设为暂缓，未登录、检查凭据或验证账户；新来源条目0，未执行真实公众号链接。使用见[首批说明](external-reading.md)与[其他信源续配](external-reading-setup.md)。实际字段／覆盖、完整关注流和后台订阅仍未验收，下文公开核查保留原日期，不将规划写成已交付能力。

## 已确认的接入方向

- 同时支持 Subscription Discovery（订阅发现）与 Personal Selection（个人精选），分别保留订阅到达、用户手选与 Agent 代选的关系；同一文章可属于多个入口，选择来源不互相覆盖。
- WUCAI 的首个入口直接适配官方读取接口。用户很少维护本地 Obsidian，优先减少中转与维护，不要求先设置五彩到 Obsidian 的同步。
- Obsidian 继续作为可选本机来源，既有本机 Markdown 检索和 journal 来源政策保留。直接接口选择不改变本机状态／索引、审计或可读记忆的职责；正文按已选分层策略留存，普通正文缓存期限为 30 天。
- WUCAI只读协议及中国区真实字段已在 10-16 验证并部署，范围与正文完整性见本页当前矩阵；未开放更新／删除／追加等平台写操作。
- Folo 读取全部现有订阅，由系统按持续委托的主题筛选相关内容；读取订阅不等同于归档全部正文或将全部内容发给模型。
- 公众号首版利用现有 Folo／WUCAI 可用入口、收藏、剪藏与分享链接，不另建任意公众号更新抓取。
- 2026-10-16用户澄清知乎核心需求是关注博主近期内容，本人很少收藏；因此停止推进以收藏为主的官方CLI配置，不申请／录入Access Secret。官方关注接口只给用户列表，本人创作接口不能代查博主。作者RSS→Folo为待验证候选，尚未接通或启用订阅；见[需求与协议核验](zhihu-setup.md)。
- 小红书采用用户指定的 [xpzouying/xiaohongshu-mcp](https://github.com/xpzouying/xiaohongshu-mcp)，封装为受控来源适配器，纳入关键词搜索、用户分享、可见收藏和首页推荐流；搜索可限定已关注作者，具体主题和抓取上限待配置。
- 留存选择分层策略：个人精选保持可检索；订阅条目先筛选，相关时再读取和缓存可用正文，未进入精选的正文缓存默认保留 30 天。Agent 可按用户认可的规则自动把部分缓存正文加入本机精选，标注代选、理由和出处，允许撤销；不回写平台收藏，也不把代选当作用户认同。移除精选不自动排除再次代选，之后仍可按规则重新选入，每次重新满足来源政策并保留选择记录。规则细节、到期计算与最小引用证据保留仍待设置。依据：[阅读内容分层留存 ADR](adr/0027-retain-personal-selections-and-cache-relevant-subscription-content.md)、[规则代选 ADR](adr/0030-promote-reading-cache-under-approved-selection-rules.md)。
- 首次接入对个人精选尽量回溯全部可获取历史，订阅流主要从启用后增量获取。各连接器记录可获取日期范围、分页覆盖与失败，不能把平台当前可见记录称为完整历史；历史精选回溯也不意味着将全部内容放入模型上下文。
- 普通文章和非敏感用户批注可按最小上下文供 MiMo 分析；Study／Life 的私密和健康资料按用户另行确认的[持续授权](private-data-authority.md)使用，新外部来源仍需明确接入范围。敏感性尚不能确定的内容需先在本机处理分类，不先发给云模型判定其是否敏感。此阅读来源选择不授权全量账户数据上传；个人模型和其他提供商需适用明确的持续许可或新增确认。依据：[阅读模型披露 ADR](adr/0028-allow-minimal-mimo-context-for-nonsensitive-reading-content.md)。

## 来源关系与建议流程

公众号／知乎等是内容发布出处，WUCAI 提供收藏、划线与批注，Folo 汇集订阅条目；同一文章可能经多个渠道到达。

建议通过统一来源适配层向本机检索与持续委托提供内容。保留原始出处、平台条目身份、版本与到达渠道；同文多渠道到达不增加独立证据数量。作者原文、用户划线和用户批注分别记录，不把收藏的作者观点自动当作用户观点或已掌握知识。

已选择按需正文留存，目标流程为“获取获准新条目 → 保留出处与完整性状态 → 按委托筛选 → 读取相关正文 → 带证据输出”；首批切片已实现手动按需拉取、出处／到达关系、普通缓存30天、个人精选留存和既有索引／清理连接。WUCAI／Folo／小红书已有注明日期的真实读取验证；按持续委托筛选、规则代选与平台差异同步仍未实现。

## 公开接入方式核查（2026-10-13）

| 来源 | 已确认的候选方式 | 尚需核验／选择 |
|---|---|---|
| WUCAI | 已选择[官方 Agent 读取接口](https://doc.wucai.site/tools/openclaw.html)，可适配只读查询而不采用 OpenClaw 主 Agent；[Obsidian 同步](https://doc.wucai.site/sync/obsidian.html)仍为可选入口 | 用户读取范围、区域、会员和凭据未确认；接口剪藏全文能力待验证，不能把划线当全文 |
| Folo | [官方 CLI](https://raw.githubusercontent.com/RSSNext/Folo/dev/apps/cli/skill.md)提供订阅列表、timeline、文章详情／readability 正文、收藏和 OPML 导出；已选全部现有订阅按主题筛选 | 已发布版本和实际账号返回范围未测试；OPML 只列订阅源，不含历史文章或阅读状态 |
| 知乎 | 已选[官方 CLI](https://developer.zhihu.com/console/docs?key=zhihu_cli)，可读关注用户、本人内容、收藏及公开搜索；另有[官方平台](https://developer.zhihu.com/)相关接口 | 已核查官方 Skill v0.7.3；关注用户列表与关注内容流不同，动态流未确认。额度、收费和真实返回范围待验证 |
| 微信公众号 | [官方发布列表接口](https://developers.weixin.qq.com/doc/service/api/public/api_freepublish_batchget)属于获授权公众号／服务号的发布能力；[腾讯凭据说明](https://cloud.tencent.com/document/product/1301/126229)涉及公众号 AppID/AppSecret | 不能外推个人微信全部关注账号和任意历史读取。建议先用分享链接、WUCAI 剪藏、Folo 已有可用订阅；持续追踪指定账号逐源验证 |
| 小红书 | 已选[xiaohongshu-mcp](https://github.com/xpzouying/xiaohongshu-mcp)，纳入搜索、分享、可见收藏和首页推荐 | 需用户完成授权登录；具体主题／数量、分页覆盖、实际账号可读内容和稳定性未测试 |

WUCAI 的 [官方 Skill](https://github.com/makediff/wucai-openclaw/blob/main/SKILL.md)可列举／搜索文章和划线、获取单篇划线与元数据，需对应区域的专用 Token；详情是否返回剪藏全文尚未确认。[传统 API](https://doc.wucai.site/tools/api.html)说明 PRO 和按 URL 获取单页划线，不能据此推断全库导出。

知乎具体字段来自其公开[文档目录接口](https://developer.zhihu.com/console/api/v3/docs)，本轮未使用用户 Access Secret 或测试私人数据。公众号入口可读取性、全文完整性和更新连续性需按账号验证；读取失败要保留限制，不能把摘要标成全文。

### 知乎官方 CLI 核查补充

[官方稳定版 Skill](https://developer-cdn.zhihu.com/zhihu-cli/releases/stable/skill/zhihu-cli-skill.zip)的能力表区分 `me followees`（关注用户列表）、`me contents`（当前凭据本人的创作列表）与 `me favorites`（收藏相关）。全文命令限本人创作，其他内容的摘要不能自动标成全文。此次官方能力表未列关注动态流命令；接入时核验实际版本，保留用户希望查看关注内容的需求，未确认时明确覆盖限制，不冒充完整更新流。

### 小红书 MCP 核查补充

依据当前[工具注册代码](https://github.com/xpzouying/xiaohongshu-mcp/blob/main/mcp_server.go)，`search_feeds` 支持关键词及“已关注”搜索范围，`list_feeds` 是首页推荐；“已关注关键词搜索”不等同完整关注时间线。`get_my_profile(tab="fav")` 可读自己的可见收藏，`favorite_feed` 是收藏写入，不能混用。

[主页实现](https://github.com/xpzouying/xiaohongshu-mcp/blob/main/xiaohongshu/user_profile.go)读取当前页面已加载内容，没有全量历史分页循环；只承诺可见返回，不承诺全部收藏历史。详情需要搜索／列表返回的条目身份与访问参数，文字、图片和视频链接分别保留，取得媒体链接不表示已经 OCR、图像理解或转写。

读取适配器排除发布、评论、点赞、收藏修改与删除登录态等写工具；通知工具即使标有只读提示，也会清除未读标记，不能作为纯读取工具开放。部署需将 MCP 绑定本机回环地址，并把登录态留在 Git 外的私密目录；具体隔离和授权登录接法待实施，本轮未登录或读取浏览器 cookies。

Folo 标记已读、修改订阅和收藏，WUCAI 更新／删除／追加记录，均为写操作，不因只读接入而开放。[Folo webhook](https://github.com/RSSNext/Folo/wiki/Actions)可能传送正文，不作为默认向 VPS 推送个人全文的入口。原文、批注、私人订阅身份与派生内容仍按本机来源／提供商／渠道政策处理。

## 部署与实施留项

1. 已认可代选规则的具体条件与数量上限；移除后仍允许再次代选的原则已定。各平台实际历史覆盖与知乎关注内容能力仍需核验。
2. 首批30天缓存的到期拒读、文件清理、精选留存及本机遗忘／撤权已实现；取消精选、平台删除同步、规则代选及引用证据长期保留仍需后续配置／实现。
3. 各账号具体来源配置、分类规则、主题与抓取／预算上限、更新／删除和失败处理。
4. 阅读结果、领域工作上下文和经复核的长期记忆如何衔接；媒体理解仍为独立后续能力。

媒体和个人讨论用于发现线索；关键申请要求与技术结论继续按 [总规格](../SPECIFICATION.md)查证一手材料。Folo 的条目证据等级取决于原始出处；WUCAI 收藏也不自动提升可信度。
