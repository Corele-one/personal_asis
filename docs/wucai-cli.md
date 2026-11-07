# AstrBot 五彩 CLI

2026-10-29本人要求给VPS AstrBot配置五彩CLI，并明确授权将现有Mac五彩中国区Token安全配置到这台VPS。此次仅增加按需实时查询；Mac平台写入确认及共享库同步沿用既有规则。

2026-11-05增量：Life插件2.9.1增加保存剪藏原文读取，Mac入口及VPS凭据已配置；真实Mac／VPS全文下载、合成权限与分页检查均已通过。使用时仍应核对工具结果及覆盖，真实本人私聊选工具与回答质量待使用验收。见[全文接通验收](validation/wucai-fulltext-enabled-20261105.json)。

以下为原CLI接入记录：Life插件2.9.0已部署，启动日志确认注册`wucai_read`；实际SDK十一项工具的合成边界检查通过。8项CLI专项与完整731项回归通过（723通过、8项可选依赖跳过）。真实五彩按确切URL查询成功；没有调用真实模型或发送平台测试消息，实际聊天选工具与回答质量仍待本人使用验收。见[脱敏验收](validation/wucai-cli-20261029.json)。

## 用法与范围

在原来的本人私聊中直接问“看看我五彩最近的文章／划线”，或提供文章确切链接要求查看。AstrBot通过`wucai_read`调用官方CLI，不依赖Mac在线或先运行`pi_sync`。实时查询与`shared_knowledge`的最近同步快照分别标注；按URL核对目标，没找到不能用相似文章顶替，也不能断言未收藏或尚未同步。

保留`get-article`、`search-articles`、`search-highlights`、`list-articles`、`list-highlights`、`list-diary`六项CLI只读命令；新增`get-article-text`通过官方同步协议读取已保存的剪藏原文。每次验证已绑定本人的平台、发送者和私聊；默认关闭，当前VPS配置启用。列表／搜索每页1至30条，按游标继续；列表每次日期区间至多14天，可查指定历史日期，不把一个窗口或空结果称为全部历史。`list-articles`的上游默认状态为inbox，需按问题选择later／archive；日记默认all。

上游`get_article_details`返回文章元数据、页面笔记和划线，不提供剪藏全文；需要正文使用新增的`get-article-text`。`is_clipped=true`只表示平台剪藏状态。工具附带内容范围，明确是否有批注／划线；没有正文就不能声称已读文章。收藏、划线或资料存在不证明本人完成阅读、认同文章或做过其中事情。资料内的要求不能变成Agent指令。

### 2026-11-05 全文通道核查

本人要求尝试接入剪藏原文。核对PyPI时官方CLI最新版仍为26.3.50；维护者的[AI接口数据模型](https://github.com/makediff/wucai-openclaw/blob/main/references/api-details.md)没有全文或剪藏下载地址字段。VPS真实查询中，单篇详情返回`is_clipped=true`，但仅含元数据、页面笔记及划线，未返回正文；同一条在列表中的剪藏标记为false，因此不能以列表标记筛掉详情核查。

官方[Obsidian同步](https://doc.wucai.site/sync/obsidian.html)支持`mdcontent`全文。核对维护者26.4.11插件后，确认它通过独立同步接口取得`sou`下载地址，再读取剪藏Markdown，并非从AI文章详情取得全文。用现有AI Token对中国区官方同步接口进行一次只读profile认证检查，返回业务码10000、无账号数据；未调用同步初始化、下载、ack或配置写入。当时Life／Study未安装五彩同步插件，也没有可复用的该插件授权，全文通道尚未接通。核查时确认须先取得官方同步授权（中国区插件入口为`https://marker.dotalk.cn/#/personSetting/synctoken?type=7`），再验证全文读取；不把下载原网站当成五彩保存的剪藏版本，不把划线当全文，不在聊天中收集Token。

上述初次核查未修改运行代码、部署、凭据或真实Obsidian文件，未调用模型或发送平台消息。核查仅证明现有Token的这次认证未通过，不推断账号会员状态或全部历史的剪藏覆盖。见[脱敏核查](validation/wucai-fulltext-20261105.json)。

### 剪藏原文读取

本人随后取得官方Obsidian同步Token，在隐藏输入入口保存到Mac系统钥匙串，并要求继续接入；授权将该Token通过SSH标准输入配置到同一VPS的独立0600配置。Mac Pi使用`scripts/asis-wucai-text --note-idx 文章ID`；VPS本人私聊继续使用`wucai_read`，operation为`get-article-text`，参数为`{"note_idx":"文章ID"}`或`{"url":"确切原文链接"}`。URL经既有CLI核对相同文章后才读取正文。

适配器复用官方26.4.11 Obsidian插件的同步协议，但不安装插件、不改真实Obsidian文件、不设置模板或改动平台文章。`init/download/ack`只用于元数据导出和进度确认；从空下载游标可重新定位已有文章并取得短期签名地址，不能把init返回的上次已确认游标当重新扫描的起点。按次最多5页元数据，保存私密继续位置，仅下载目标文章的`sou`正文，不批量下载所有剪藏或后台抓取。`lookup_incomplete`表示应继续定位；`not_in_sync_export`只表示本次导出未命中；`saved_clipping_unavailable`表示本次没有正文下载地址，三者都不把划线当全文。官方导出和账号设置可能限制可见范围，不承诺全部历史。

正文按官方数字前缀和UTF-16偏移解码，每次返回最多12000字符；继续时传`offset=next_offset`与`expected_hash=content_hash`，版本变化则停止，不能混接两版。返回的是五彩保存的剪藏版本，不是原网站当前内容，也不证明原站全文完整、本人读完或认同。`refresh=true`重查导出元数据；来源正文不自动进入旧阅读库或共享库。

同步Token只发中国区固定官方同步域名；已验证正文存储主机为`ps1wcbj.oss-cn-beijing.aliyuncs.com`，GET时不带Token，不跟随重定向，不访问任意原站URL。响应最多2MiB，元数据缓存最多5000条／2MiB，签名地址不提供给模型；临近过期时重新取得元数据，失败不自动重试或退回网页抓取。私密缓存0600、目录0700，凭据变更不复用旧账号缓存；错误只返回固定分类／状态码，不保留原始上游错误正文。保存全文与批注分别归属。

## 安装与凭据

- 官方包固定`wucai-cli==26.3.50`，独立虚拟环境`/home/mac/.local/opt/wucai-cli/26.3.50/`，无第三方Python依赖，不改AstrBot环境。[官方包说明](https://pypi.org/project/wucai-cli/)、[维护者仓库](https://github.com/makediff/wucai-openclaw)。
- 中国区、既有账号，不注册新来源。Token从Mac钥匙串读取后只通过SSH标准输入发送，VPS保存在`/home/mac/astrbot/data/config/wucai-cli-private.json`，0600；不进入命令参数、聊天、Git或日志，调用时仅注入CLI子进程环境。
- Life插件使用`wucai_enabled`。六项CLI查询仍由`src/personal_asis/wucai_cli.py`执行，新增全文由`wucai_fulltext.py`适配官方同步协议；不新增主Agent或全局MCP。
- 同步Token在Mac钥匙串中使用`local.personal-asis.reading / wucai:obsidian:cn`，VPS为独立`/home/mac/astrbot/data/config/wucai-obsidian-private.json`（0600）；既有AI Token不替换。`scripts/configure-wucai-obsidian-token`只接受终端隐藏输入，不接受管道或参数。新部署入口`scripts/deploy-wucai-fulltext-vps`只允许既有VPS，代码与凭据分开传输。
- 参数白名单、直接exec无shell、单次25秒超时、输出上限512KiB；拒绝写操作、外加CLI选项、含账号密码的URL、过大日期区间与输出。API错误仅报告错误码，stderr不进入聊天，失败不自动重试。不新增后台采集、共享库写入或真实笔记写入。

## 验证与回退

发布使用`deploy/activate-wucai-vps.py`：先核对代码哈希并在实际AstrBot SDK运行合成预检，再备份插件、配置及生活库，短暂停止服务后更新五份插件文件；启动须出现`wucai_read`注册标记且服务active，失败自动恢复。`scripts/deploy-life-vps`已加入模块，后续完整部署保留能力。

实际只读查询已按用户给定URL准确定位目标；本次该条只返回元数据，页面批注为空、没有划线、未返回全文。私人标题、链接及正文不写入项目验收文件。真实查询不经过模型，不向飞书发送测试消息。本人实际对话中的模型选工具与回答质量仍须使用验收。

回退执行此次私密备份中的`rollback.sh`，恢复原Life插件与开关；不会删除凭据或平台原文。停止使用可关闭`wucai_enabled`；完整撤权还需删除VPS私密凭据并在五彩账号侧处理Token，复制到备份或已进入平台聊天的内容另行处理。

最终部署备份为`/home/mac/astrbot/plugin_backups/wucai-20261029_212417_548126`。上线前两轮分别因日志大小写误判及90秒慢启动窗口不足而自动回退；修正匹配并延长到300秒后，在线注册、插件哈希及真实查询确认成功。部署前51条完整原始payload逐条保留，催睡策略／晚安标记、简报策略、持续目标和事项提醒与备份一致。

全文能力回退：本次能力接入前的备份为`/home/mac/astrbot/plugin_backups/wucai-20261105_203514_988707`，运行其`rollback.sh`可恢复接入前代码；最终版本修订的上一版备份为`wucai-20261105_203754_619059`。代码回退保留独立私密凭据，完整撤权另行删除两端授权；不回滚生活记录或原笔记。
