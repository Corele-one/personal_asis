# 信息来源接入讨论

状态：已选择部分接入路线，尚未启用真实订阅、读取账户或安装连接器。当前实际入口仍是本机配置的 Markdown，见 [Mac 实施说明](pa0-mac.md)。首批来源为微信公众号、知乎、WUCAI、Folo，并新增用户指定的小红书 MCP。

## 已确认的接入方向

- 同时支持 Subscription Discovery（订阅发现）与 Personal Selection（个人精选），分别保留订阅到达、用户手选与 Agent 代选的关系；同一文章可属于多个入口，选择来源不互相覆盖。
- WUCAI 的首个入口直接适配官方读取接口。用户很少维护本地 Obsidian，优先减少中转与维护，不要求先设置五彩到 Obsidian 的同步。
- Obsidian 继续作为可选本机来源，既有本机 Markdown 检索和 journal 来源政策保留。直接接口选择不改变本机状态／索引、审计或可读记忆的职责；正文按已选分层策略留存，普通正文缓存期限为 30 天。
- WUCAI 只读函数是拟接入能力；账号区域、读取范围、凭据和实际返回字段仍待配置及验证，未开放更新／删除／追加等平台写操作。
- Folo 读取全部现有订阅，由系统按持续委托的主题筛选相关内容；读取订阅不等同于归档全部正文或将全部内容发给模型。
- 公众号首版利用现有 Folo／WUCAI 可用入口、收藏、剪藏与分享链接，不另建任意公众号更新抓取。
- 知乎使用官方 CLI 作为首个连接器；用户希望读取关注内容。官方文档已核实关注用户列表，关注动态流／关注作者更新内容的实际覆盖仍待验证，不能把该用户需求记成已实现能力。
- 小红书采用用户指定的 [xpzouying/xiaohongshu-mcp](https://github.com/xpzouying/xiaohongshu-mcp)，封装为受控来源适配器，纳入关键词搜索、用户分享、可见收藏和首页推荐流；搜索可限定已关注作者，具体主题和抓取上限待配置。
- 留存选择分层策略：个人精选保持可检索；订阅条目先筛选，相关时再读取和缓存可用正文，未进入精选的正文缓存默认保留 30 天。Agent 可按用户认可的规则自动把部分缓存正文加入本机精选，标注代选、理由和出处，允许撤销；不回写平台收藏，也不把代选当作用户认同。移除精选不自动排除再次代选，之后仍可按规则重新选入，每次重新满足来源政策并保留选择记录。规则细节、到期计算与最小引用证据保留仍待设置。依据：[阅读内容分层留存 ADR](adr/0027-retain-personal-selections-and-cache-relevant-subscription-content.md)、[规则代选 ADR](adr/0030-promote-reading-cache-under-approved-selection-rules.md)。
- 首次接入对个人精选尽量回溯全部可获取历史，订阅流主要从启用后增量获取。各连接器记录可获取日期范围、分页覆盖与失败，不能把平台当前可见记录称为完整历史；历史精选回溯也不意味着将全部内容放入模型上下文。
- 普通文章和非敏感用户批注可按最小上下文供 MiMo 分析；Study／Life 的私密和健康资料按用户另行确认的[持续授权](private-data-authority.md)使用，新外部来源仍需明确接入范围。敏感性尚不能确定的内容需先在本机处理分类，不先发给云模型判定其是否敏感。此阅读来源选择不授权全量账户数据上传；个人模型和其他提供商需适用明确的持续许可或新增确认。依据：[阅读模型披露 ADR](adr/0028-allow-minimal-mimo-context-for-nonsensitive-reading-content.md)。

## 来源关系与建议流程

公众号／知乎等是内容发布出处，WUCAI 提供收藏、划线与批注，Folo 汇集订阅条目；同一文章可能经多个渠道到达。

建议通过统一来源适配层向本机检索与持续委托提供内容。保留原始出处、平台条目身份、版本与到达渠道；同文多渠道到达不增加独立证据数量。作者原文、用户划线和用户批注分别记录，不把收藏的作者观点自动当作用户观点或已掌握知识。

已选择按需正文留存，拟实现流程为“获取获准新条目 → 保留出处与完整性状态 → 按委托筛选 → 读取相关正文 → 带证据输出”；普通正文缓存 30 天，个人精选另保持可检索。Agent 依认可规则可将缓存正文晋升为标注明确的代选精选，具体规则与索引／清理机制尚未实现。

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
2. 30 天缓存的到期／清理机制，个人精选留存／删除与长期索引规则，引用证据需要保留的最小内容。
3. 各账号具体来源配置、分类规则、主题与抓取／预算上限、更新／删除和失败处理。
4. 阅读结果、领域工作上下文和经复核的长期记忆如何衔接；媒体理解仍为独立后续能力。

媒体和个人讨论用于发现线索；关键申请要求与技术结论继续按 [总规格](../SPECIFICATION.md)查证一手材料。Folo 的条目证据等级取决于原始出处；WUCAI 收藏也不自动提升可信度。
