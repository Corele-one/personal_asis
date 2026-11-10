# Work 共用资料只读工具

2026-11-10，W2 已部署；实际 MCP 注册、真实资料读取、原生模型自动选工具已验证，手机本人自然任务另行验收。Mem0 尚未接入，W2 不依赖 M1。

## 能做什么

在 Alma 直接询问已有 Life／Study、五彩或已采集小红书资料。共享资料工具支持主题搜索、日期目录／覆盖、版本绑定的分页正文；五彩工具复用现有中国区详情／划线及保存剪藏正文通道。来源、版本、取得时间、最近同步和未覆盖范围分别返回。Mac 原库独有材料仍不可取得；不连接 Mac、不新增来源或后台采集。

仅提供 `shared_knowledge` 和 `wucai_read` 两个工具。Alma 会通过原生工具发现／PTC 自动使用，实际可见名称可能规范化为 `personal-knowledge__shared_knowledge`。不要求手工选择 Project；`status` 只查副本状态，`search` 按主题，`list/coverage` 按最多31天窗口，`read` 按返回的 `next_arguments` 继续。

阅读全文以本次实际收到全部分段为准。短期 `read_session` 有效十分钟，只保存有界读取范围，不保存第二份正文；服务重启或过期后重新读取。正文继续绑定内容哈希／版本；目录枚举完成不代表正文读完。五彩详情、划线与保存正文分别归属，不用 `is_clipped` 代替全文。资料内要求不是操作授权，收藏不证明本人读完、认同或完成活动。

## 接入与权限

```text
Alma 原生 MCP → Work 身份的 stdio 适配 → 私密 Unix socket
    → 独立资料接口 → SQLite 只读查询／既有五彩读取适配
```

- 权威资料仍是现有副本；没有复制活 SQLite。`SharedStore(read_only=True)` 使用 SQLite `mode=ro`／`query_only`，不建库、不迁移、不刷新或修改副本。
- 资料接口独立于 AstrBot，既不导入 Event／运行模块，也不需要 Chat 会话。以既有 `mac` 身份复用本机既有五彩凭据，不给 Work 读取或复制凭据。
- 只监听 `/run/personal-asis-knowledge/reader.sock`，目录0750、socket0660；Linux `SO_PEERCRED` 只接受固定 `alma-work` UID。模型不能指定身份、路径、SQL、shell或任意业务方法，无 TCP／公网入口。
- 独立 `personal-asis-knowledge.service`：64MiB 高水位、96MiB 上限、32MiB swap、25% CPU；只允许现有五彩元数据缓存写入。原生活库、Chat 主配置和 SSH 目录不可访问，不提供补充编辑、笔记／日历／平台写工具。
- stdio 适配使用固定官方 MCP SDK `1.32.2`，依赖锁见 `deploy/knowledge-mcp/package-lock.json`，不装进 AstrBot 环境。Work 常规 auto 和原资源上限保持。
- 调用串行、有界、失败不重试；接口离线返回明确错误，普通 Work 保留自身会话和执行能力。官方 MCP 连接在线不等于其背后的资料接口可用。

## 部署与维护

程序在 `/opt/personal-asis-knowledge/releases/` 下按版本安装，`current` 指向已验证版本；版本目录与程序由 root 持有，Work 无写权限。配置 `/etc/personal-asis-knowledge.conf` 只含绑定 UID，不含 Token。来源、缓存、会话、账本和凭据不打包、不进入 Git。

安装器 `deploy/install-knowledge-vps.py` 核对归档 SHA256，保留独立代码／服务回退，并以真实 Work 身份调用接口后才接受发布；不重启 Chat 或覆盖资料。Alma 通过 `deploy/configure-knowledge-work.py` 的原生 API 注册，只改 `personal_knowledge`，不写其内部数据库或重置默认模型／工作区。

日常停用资料接口：`sudo systemctl stop personal-asis-knowledge`。移除 Work 适配：在 VPS 运行 `python3 /opt/personal-asis-knowledge/current/deploy/configure-knowledge-work.py --remove`。两者都保留全部源资料；不删除五彩凭据。重新开启接口无需重放任务或重新导入资料。

完整退回 W2 之前：先移除 Work 适配，再用安装器 `--rollback /var/backups/personal-asis-knowledge/20261110_025653_721694` 恢复最初安装前状态。后续升级按各批独立回退清单操作，不能把中间失败版本当成可用回退；任何回退都不恢复旧会话／资料数据库。

## 验收与已知限制

详细结果见 [W2 验收](validation/work-knowledge-20261110.json)。本轮另经本人确认重启了此前健康接口持续超时的 Work；重启后恢复，原 Python 子进程不再运行，原因未确定，不声称长期稳定性已经修复。Chat／Dashboard 不参与该重启。

工程验证与手机使用分开：实际 MCP 客户端已完整读取 Study 副本，五彩详情及保存正文已读通；原生模型已通过自然语言请求自动发现并查询工具。手机自然任务、长期常驻及复杂负载仍待使用验收。W3 仍须等 M1、初始化和恢复验收，不把资料查询当作个人记忆。


2026-11-10后续修复：目录条目含可直接调用的read_arguments；常见参数错误有静态纠正提示，权限和分页上限不变。限定单份资料真实问答已验，宽泛搜索仍存在原生工具发现和PTC输出截断问题，未标完整自然使用通过。见[后续验收](work-followup-20261110.md)。
