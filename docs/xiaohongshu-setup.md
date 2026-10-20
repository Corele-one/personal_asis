# 小红书 MCP

2026-10-20 当前服务为固定 v2.5.5 的 Keychain 版本。沿用原会话与独立鉴权，监听 `127.0.0.1:18060`，无公开平台操作 REST 接口、自动登录、Cookie 文件或后台抓取。

当前实际工具目录共8项：`check_login_status`、`list_feeds`、`search_feeds`、`get_feed_detail`、`get_my_profile`，以及经确认适配器使用的 `like_feed`、`favorite_feed`、`post_comment_to_feed`。Pi 的原生 MCP 配置仅直接暴露前五项；后三项经 `source_write` 显示完整参数并由原生UI确认。具体范围见[平台读写](source-writes.md)。

构建命令使用 `scripts/build-xhs-keychain.py --source 上游固定源码目录 --go Go可执行文件 --output 目标二进制 --allow-writes`。脚本核对关键上游文件哈希，保留Keychain补丁，裁掉其他工具和REST操作路由；模块缓存／构建缓存按实际环境配置，不把依赖或二进制提交Git。原只读二进制留作回退。

服务名 `local.personal-asis.xiaohongshu`；supervisor、Python及二进制路径存于本机私密plist，凭据从Keychain临时进入子进程环境。首次本轮bootstrap未成功，随后重新bootstrap和kickstart恢复；实际握手与8项工具目录通过，不将这报告为账户内容或写入成功。

2026-10-16的历史真实读取：本人首页2条、收藏2条、单篇正文、本机搜索及重启会话复用；当时缓存8条（精选2条）。该结果只证明当日场景，不代表本轮登录仍有效、完整关注流、全历史或可自动社交操作。首页推荐不是关注全流；遇到失效／验证码／风险提示停止，由本人处理登录。

上述服务切换验收没有请求平台内容、点赞、收藏、评论或发帖。新写入工具的真实操作需要具体内容与目标的确认，不能用部署任务代替。完整验证见[本轮记录](validation/two-agent-20261020.json)；后续本人授权的收藏读取见下方统一阅读资料库。

## 多账号

新增账号使用独立 Keychain 会话／鉴权、launchd 服务和回环端口，原账号的默认钥匙串条目与 `18060` 保持兼容。账号标识只允许小写字母与数字，以字母开头；实际账号名和端口映射保存在本机私密 `xhs-accounts.json`，不提交 Git。浏览器可执行文件缓存可复用，平台会话与指纹 seed 按账号分开。

用户本人先登录新增账号，用 Cookie-Editor 手工导出 Header String。以下命令的 `second` 是示例标识；隐藏输入不会回显 Cookie，不读取浏览器 Cookie，也不执行自动登录：

```sh
PYTHONPATH=src python3 -m personal_asis.xhs_accounts import --account second --dialog
PYTHONPATH=src python3 -m personal_asis.xhs_accounts install --account second --label 第二账号 --port 18061 --binary /本机固定版二进制路径
```

默认使用现有 PersonalAsis home；可传 `--home`。终端隐藏输入可省略 `--dialog`。导入会拒绝与原账号相同的 `web_session`，不会覆盖原账号。端口重复、非回环、已存在账号改址均拒绝。遇到失效、验证码或风险提示，由本人处理后重新手工导出。

重新启动 Pi 后，原账号对应 `xiaohongshu`，新增账号对应 `xiaohongshu_second`；说明中显示实际配置的账号名。两个 MCP 分别直接暴露5项读工具。多个账号同时启用时，`source_write` 必须明确传 `account`（原账号是 `default`），确认框显示账号名、标识与完整参数。没有账号的旧待确认小红书计划拒绝执行。

新增账号仅接入原生 Pi MCP，不合并旧单账号 reading 缓存／索引；旧 `reading sync --source xiaohongshu` 仍属于原账号。登录检查、真实读取、本人确认写入分别验收，不以服务启动代替账户有效。

本人后续授权的[统一阅读资料库](reading-library.md)提供独立的分账号收藏采集、检索和按需补取。它保留旧缓存兼容关系，不将两个账号写入旧单账号索引；当前小红书覆盖仍只是收藏tab可见页。
