# 新增研究信源与后续候选

2026-10-16，用户批准三条公开信源添加为Folo普通订阅，统一在“研究与工程”分类管理。三次创建成功，随后回查分类及 `isPrivate=false`，订阅总数38→41。普通订阅关系可能对他人可见，用户已明确选择此方式；未升级付费计划。

| 已添加信源 | 订阅地址 | 本轮验证 |
|---|---|---|
| arXiv cs.AR＋cs.DC | <https://rss.arxiv.org/rss/cs.AR+cs.DC> | 合并体系结构与并行／分布式计算；Folo读取2条元数据并入本机索引 |
| SIGARCH 博客 | <https://www.sigarch.org/feed/> | Folo读取2条元数据并入本机索引 |
| LLVM 发布更新 | <https://github.com/llvm/llvm-project/releases.atom> | Folo读取2条元数据并入本机索引；无需个人GitHub会话 |

Folo本机缓存共9条，新增6条仅元数据。正文按需获取，未自动回溯历史、批量下载正文、自动筛选或启用助手后台同步，也未扩大模型／远程展示许可。Folo自身订阅更新和助手后台调度是两个范围。真实结果见[验收记录](validation/xhs-mcp-feeds-20261016.json)。arXiv是预印本发现入口，不能把收录等同于同行评审通过。

后续候选保留CMU CSD PhD Blog、指定研究者／实验室博客和B站／YouTube指定作者及课程；本次未新增这些订阅。先选具体作者再验证更新和字幕覆盖，列表可读不等于音视频理解已接入。小红书使用[独立MCP](xiaohongshu-setup.md)，适合经验检索和公开笔记线索，不承诺完整关注流。知乎官方CLI按用户偏好停止推进，公众号不接。

研究结论仍回到论文、作者原文和官方文档。依据：[arXiv RSS说明](https://info.arxiv.org/help/rss.html)、[SIGARCH](https://www.sigarch.org/)、[CMU CSD PhD Blog](https://www.cs.cmu.edu/~csd-phd-blog/)、[GitHub发布查看说明](https://docs.github.com/en/repositories/releasing-projects-on-github/viewing-your-repositorys-releases-and-tags)。
