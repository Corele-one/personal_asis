# 小红书 MCP

2026-10-20 当前服务为固定 v2.5.5 的 Keychain 版本。沿用原会话与独立鉴权，监听 `127.0.0.1:18060`，无公开平台操作 REST 接口、自动登录、Cookie 文件或后台抓取。

当前实际工具目录共8项：`check_login_status`、`list_feeds`、`search_feeds`、`get_feed_detail`、`get_my_profile`，以及经确认适配器使用的 `like_feed`、`favorite_feed`、`post_comment_to_feed`。Pi 的原生 MCP 配置仅直接暴露前五项；后三项经 `source_write` 显示完整参数并由原生UI确认。具体范围见[平台读写](source-writes.md)。

构建命令使用 `scripts/build-xhs-keychain.py --source 上游固定源码目录 --go Go可执行文件 --output 目标二进制 --allow-writes`。脚本核对关键上游文件哈希，保留Keychain补丁，裁掉其他工具和REST操作路由；模块缓存／构建缓存按实际环境配置，不把依赖或二进制提交Git。原只读二进制留作回退。

服务名 `local.personal-asis.xiaohongshu`；supervisor、Python及二进制路径存于本机私密plist，凭据从Keychain临时进入子进程环境。首次本轮bootstrap未成功，随后重新bootstrap和kickstart恢复；实际握手与8项工具目录通过，不将这报告为账户内容或写入成功。

2026-10-16的历史真实读取：本人首页2条、收藏2条、单篇正文、本机搜索及重启会话复用；当时缓存8条（精选2条）。该结果只证明当日场景，不代表本轮登录仍有效、完整关注流、全历史或可自动社交操作。首页推荐不是关注全流；遇到失效／验证码／风险提示停止，由本人处理登录。

本轮没有请求平台内容、点赞、收藏、评论或发帖。新写入工具的真实操作需要具体内容与目标的确认，不能用部署任务代替。完整验证见[本轮记录](validation/two-agent-20261020.json)。
