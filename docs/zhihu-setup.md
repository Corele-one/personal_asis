# 知乎配置与关注博主更新

2026-10-16用户后续决定：本人很少收藏知乎内容，若不能取得关注博主近期内容，则官方收藏入口没有实际价值。本轮停止推进知乎官方CLI凭据申请／录入与账户读取；不再以收藏作为知乎接通的验收目标。用户的核心需求是关注作者的新内容，RSS／Folo作者订阅仅为待验证候选，尚未承诺或实施。无需为此申请Access Secret，下文初始化步骤仅保留技术参考。

2026-10-16：用户要求开始配置知乎，除了本人收藏，也希望取得关注博主的最近内容。官方 CLI 0.6.1 已安装；本次重新核对官方发布清单，最新版仍为0.6.1，官方说明包0.7.3要求的最低版本也是0.6.1，无需升级。项目系统凭据库中尚无知乎凭据，已打开官方个人中心，随后按用户反馈停止推进凭据配置。账户真实接通、收藏／关注列表和额度均尚未验证，当前未启用后台工作或新增模型／远程展示权限。

## 本人需要完成的步骤

1. 在[知乎开放平台个人中心](https://developer.zhihu.com/profile)登录并申请 Access Secret。
2. 在 Mac 自己的终端运行下方命令，按不回显提示录入。不要在聊天、命令参数或文件中粘贴密钥。

```sh
/Users/corleone/code/personal_asis/scripts/asis reading key --source zhihu
```

凭据保存于系统凭据库服务 `local.personal-asis.reading` 的 `zhihu` 账号，仅注入官方 CLI 子进程的 `ZHIHU_ACCESS_SECRET` 环境。录入不等于账户已验证；后续先查额度，再小范围读取收藏和关注列表，按真实字段核验并接入既有本机索引。仅读取公开／获准可见范围，不承诺私密收藏和完整历史。

## 关注博主最近内容的能力边界

| 入口 | 已核实的协议范围 | 本项目当前状态 |
|---|---|---|
| `me favorites recent` / `lists` / `items` | 本人近期收藏、收藏夹及其中公开内容；近期接口无分页，指定收藏夹使用服务返回的分页游标；内容为标题／摘要 | 只读适配已部署，真实账户待验证 |
| `me followees` | 本人关注的用户列表及主页标识；不是更新内容或关注动态流 | 已有只读调用适配，真实列表待验证；不将关注关系作为文章入库 |
| `me contents` / `me content` | 当前 Access Secret 本人的创作摘要／全文；没有任意博主 ID 参数 | 不能将其用于读取所关注博主的创作；不绕过本人归属限制 |
| RSSHub 作者回答／文章 → Folo | 有 `/zhihu/people/answers/:id` 和 `/zhihu/posts/people/:id` 路由；后者按创建时间查询。路由标记反爬限制，可涉及单独会话／Cookie | 仅核验官方路由代码，尚未安装RSSHub、提供Cookie、添加Folo订阅或验证真实博主；存在路由不等于已接通 |

优先验证博主自己发布的文章／回答，不能把点赞他人内容、转发或主页置顶误称为本人近期创作。具体可见窗口、发布时间排序、摘要／正文覆盖和稳定性需实测，不能承诺完整关注动态或全量历史。即便后续取得关注名单，也不会自动将整个名单发送给公共RSS实例或启用全部博主后台订阅。

官方协议依据：[发布清单](https://developer-cdn.zhihu.com/zhihu-cli/releases/stable/manifest.json)、[官方接口说明包](https://developer-cdn.zhihu.com/zhihu-cli/releases/stable/skill/zhihu-cli-skill.zip)中的 `references/user-api.md`、`references/creator.md` 和已安装CLI的 `me --help` / `me contents --help`。替代路线依据：[RSSHub用户回答](https://github.com/DIYgod/RSSHub/blob/master/lib/routes/zhihu/answers.ts)、[RSSHub用户文章](https://github.com/DIYgod/RSSHub/blob/master/lib/routes/zhihu/posts.ts)。
