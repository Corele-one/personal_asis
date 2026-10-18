# 公开检索真实联调与发布续验

2026-10-18。用户明确允许真实收费接口联调，并在通过后部署现有 Mac／VPS。本文是此前 [481项模拟验收](validation/web-search-20261018.json) 的续作，不改写历史记录。当前已发布 `web-live-cfb5d209d8b32103`；Mac PA0／PA1及VPS协调／PWA／AstrBot运行，代码／插件哈希一致，来源／模型配置哈希不变；旧代码与plist保留。完整结果见[本轮验收](validation/web-search-live-20261018.json)。

## 真实结果与修正

- Exa：首个25秒超时结果未知，保留本机标记，未重发该请求；另一不同查询成功返回 SQLite 官方文档。随后真实 Pi→Exa→静态正文→MiMo 取得引用回答，3次模型、3,561 Token。JSON前的说明文字经仅提取一个完整最终对象归一化后，原付费步骤零新增Token恢复成功；原引用／schema检查保留。
- Jina：真实 HTML POST 返回401，明确要求认证（当前出口IP信誉限制）。没有将静态降级报告成 Jina 转换成功；没有 Jina Key，也没有代开账户或充值。保留可选 Keychain 鉴权入口。
- 用户随后指定已有 Key 的 DeepSeek 官方 Search API。真实 Search＋正文快照＋本机HTTPS校验通过。API凭据只存Mac钥匙串 `local.personal-asis.web/deepseek`，不转发VPS。MiMo仍为现有 `mimo-v2.6-flash`，日／月和单次Token上限不变。
- 真实 MiMo也曾达到512输出上限，另一次未调用工具便伪造E1；均被宿主拒绝，计费与防重保留。官方API只支持 `tool_choice=auto`，不能靠指定函数强迫调用。因此新 `agent-web-v3` 的显式纯公开工作由宿主先按批准词搜索一次、读取首个结果，再以原输出上限调用一次JSON模式MiMo。旧v1/v2及普通Agent保留原输入，混合来源仍走受控工具循环。
- 两次真实搜索曾因HTTP／章节锚点被过滤而返回证据不足；随后核对到实际 URL 为 SQLite HTTP文档加锚点。修正为仅尝试HTTPS、移除网络不发送的章节fragment；不回退HTTP，不放行私网。HTTP升级后不信任旧正文，改用本机HTTPS内容。
- 最终 DeepSeek→公开正文→本机校验→MiMo闭环为1次搜索、1次阅读、1次模型调用，1,362 Token；引用SQLite论坛实际片段并声明来源、部分内容及日期未知。复用原请求新增0 Token；这不是SQLite官方手册的完整质量验收。

精确调用、失败、用量、发布包与服务验证见本轮机器可读记录；不公开真实私人正文、Token值、Cookie或账号信息。

## Provider与权限

DeepSeek 独立 Search 使用 `POST /v1/tools/search`，只发单独批准的 query、count、need_content，不发 ori_question、个人问题、笔记或定位信息。摘要仍是 discovery，正文在Mac私密工作会话中按URL保存为最多6000字符快照；只有 `fetch_web` 通过本机DNS／HTTPS／重定向检查后才生成编号证据。过期、重定向目的地不一致或HTTP升级均使用本机静态内容，不能复用不匹配快照。

**本版没有调用 DeepSeek 任意URL Fetch接口。** 远端Fetch的DNS／重定向不能由本机逐跳约束，因此不为绕开Jina认证而放宽现有SSRF规则。Search附带的正文来自公开发现，仍标partial、Provider日期未核实，不声称具有本地原文字符位置。DeepSeek检索排名／authority不自动成为本人事实或独立可靠性判断。

公开DNS如只返回代理benchmark地址，改由固定IP、校验证书的Google DoH查询A记录；再次检查公网地址并固定TLS连接。私网／环回／混合响应不触发绕行，仍拒绝。DoH只披露公开目标域名，不传原问题；禁用EDNS子网定位。没有修改系统DNS／代理设置。Jina鉴权仅可发固定Reader POST，DeepSeek鉴权仅可发固定Search POST，均不跟随重定向。

网络操作与MiMo Token分开记账；DeepSeek官方当前列成功Search／Fetch各每千次5元，本版只调用Search；客户端记录次数、结果与成本未知状态，不把估算当已核对账单。未知Exa结果不自动重试，两笔既有MiMo未知预留保持不动。无后台网络／账号抓取、无新外部来源披露许可。

## 本机与飞书入口

```sh
# 本机终端隐藏输入，不把Key放在参数或聊天
scripts/asis web key --provider deepseek
# 显式新纯公开工作；不加个人来源即不读旧笔记
scripts/asis-agent run --web --web-backend deepseek \
  --public-query 'SQLite WAL concurrency site:sqlite.org' \
  --query '概括取得的页面并引用，说明来源与片段局限。' --request-id NEW_ID
# 恢复仅沿用原编号、Provider、协议和回执
scripts/asis-agent resume --request-id NEW_ID
```

发布后的本人飞书私聊测试：

```text
/asis web-deepseek SQLite WAL concurrency site:sqlite.org | 概括取得的页面并引用，说明来源与片段局限。
```

`/asis web` 保留Exa/Jina（Jina不可用时静态降级）；两个新文字入口均仅公开范围，不读取Study/Life，不自动创建角色或目标。原搜索、角色、卡片和工作控制保留旧协议；现有卡片表单没有新增联网选项。新文字入口通过既有加密中转，VPS只处理短暂回复明文及密文中转，凭据和工作记录仍在Mac。真实飞书消息与手机UI由用户验收，不以SDK模拟或加密探针代替。

## 测试与回退

Mac checkout：501项＝482通过＋19跳过；Mac独立包同为501项＝482通过＋19跳过。VPS核心501项＝334通过＋167跳过；实际AstrBot SDK／加密检索／DeepSeek专项31项全部通过。SDK解释器有未关闭事件循环ResourceWarning，完整集也有既有SQLite资源警告，未据此伪造失败或忽略记录。生产加密通道对v3既有结果的status探针通过，0新增Token；真实平台消息与UI未测试。

部署后又通过生产加密通道新建一次真实纯公开工作：DeepSeek搜索1次、读取1次、MiMo1次，supported并含[E1]，1,395 Token，约28.95秒；没有发送平台消息。整个本轮MiMo共享账本新增9,469 Token，包含失败实验的已知计费，既有未知预留仍为2笔。DeepSeek共6次成功Search（含被客户端过滤的发现结果），按当前标价估算0.03元，未核对账单；没有调用DeepSeek Fetch。Exa有1次未知超时及2次成功，费用未知；Jina没有成功转换。密钥、真实私人正文和完整响应均未进入公开记录。

Mac checkout和独立包运行完整测试，VPS运行标准库核心集与实际AstrBot SDK专项；准确数量、跳过和警告记录在本轮JSON。新增覆盖DoH边界、凭据固定目标、公开新命令、DeepSeek快照与恢复、日期未知、HTTP升级／fragment、原付费v1恢复、v3无笔记公开路径及格式归一化。真实私密资料、多来源质量、无人值守重启和飞书UI没有重新验收。

保留原 `retrieval-v2-de593bc25486b7cc` 代码和两套Mac解释器。Mac回退恢复私密 `deployment-rollbacks/新发布编号` 的原plist，VPS恢复同名rollback目录保存的旧代码链接与插件，再重启同样服务；不回滚或删除work／预算数据库。v3工作应暂停并保留防重标记，不能交给旧代码当新工作重算。所有来源／模型配置哈希必须不变，Keychain新增DeepSeek凭据不属于来源授权更改。

参考：[DeepSeek Search/Fetch官方文档](https://api-docs.deepseek.com/zh-cn/guides/search/)、[MiMo工具选择限制](https://mimo.mi.com/docs/en-US/api/chat)、[Google DoH JSON接口](https://developers.google.com/speed/public-dns/docs/doh/json)。
