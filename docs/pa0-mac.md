# PA0 Mac 本地节点

状态：PA0 已按 Mac 单节点范围验收。本文维护当前索引／配置规则；日常命令见 [单节点运行](pa0-mac-only.md)，测试与现场依据见 [最终验收](pa0-acceptance.md)。

## 已实现范围

- 显式索引／核对 Markdown 正文、标题、frontmatter、标签与链接；不打开附件、不做 OCR。
- 文档首次发现分配 UUID；同路径编辑保留身份，SHA-256 标识内容版本。
- 移动仅在设备／inode 唯一且内容哈希相同的情况下保留 UUID，支持移动、路径交换与覆盖。跨卷移动、移动并编辑等无法确信的身份变化创建新 UUID；相同内容本身不构成身份依据。
- 相同版本按内容哈希形成 Replica Group，各副本保有独立身份；多节点代码保留，历史双副本验证见最终验收。
- 核对先比较设备、inode、大小、mtime 和 ctime；只对候选变化读文件和计算哈希。`--force` 可核验全部内容。
- 删除文件不再命中；文件变化但尚未核对时，搜索验证当前哈希并跳过过期结果，报告跳过数。不会将旧版本摘录冒充当前证据。
- 来源根目录不可用或任一候选文件读取失败时，该来源暂停返回结果，保留身份以便恢复；单个来源的读取失败不会清空历史索引，也不阻止另一来源完成核对。
- SQLite 事务串行化索引更新，保留版本元数据；FTS 搜索文本仅保存在本机索引。版本表与业务状态表不另存原始文件副本。
- 本机操作记录仅存核对计数、查询哈希、渠道、命中数和时间；不写查询明文、标题、路径或摘录，保留 180 天。

## 配置与权限

`sources.yaml` 使用 **JSON 兼容的 YAML 1.2 语法**，由标准库读取；目前不支持缩进式 YAML、注释和锚点。参见 [配置样例](../config/sources.example.yaml)。来源根目录必须是绝对路径且互不重叠，符号链接文件／目录跳过。

| 字段 | 含义 |
|---|---|
| `node_id` | 本机节点名，当前为 `mac` |
| `sources[].id` | 唯一来源标识 |
| `root` | 本机原文根目录 |
| `policy` | `normal` 或 `private` |
| `index` | 是否启用本地索引 |
| `remote_metadata` | 是否允许向远程渠道导出非私密文档的元数据，默认关闭 |
| `private_remote_metadata` | 单独允许此来源的私密元数据；仅在明确授权后本机配置，默认关闭，不授权正文／模型 |
| `exclude` | 根目录相对路径 glob；匹配目录时排除其所有后代 |
| `private_paths` | 混杂来源中按相对路径 glob 标为 private，仍保留本机索引；默认空 |
| `remote_metadata_paths` | 可选的远程元数据路径白名单；省略保持既有源级规则，空数组禁止所有条目；private 标记及许可仍优先 |
| `formats` | 本机显式启用的文本格式，默认 `["md"]` |
| `private_remote_evidence` | 私密正文的独立加密阅读许可，默认关闭；仍需元数据和 `remote_evidence` 许可 |
| `remote_evidence` | 单独许可已获元数据权限的条目按需加密阅读，默认关闭；私密另需 `private_remote_evidence` |

private 默认不允许远程元数据；启用时必须另有明确的 `private_remote_metadata` 许可。frontmatter 的 `sensitivity: private`、`policy: private` 或 `classification: private` 覆盖普通来源分类；排除规则仍生效。程序不从正文推断健康分类。最新[持续授权](private-data-authority.md)已覆盖 Study／Life 当前及新增文件的模型处理和本人渠道展示，Life 保持 private。私密 PWA 阅读另设 `private_remote_evidence`，与元数据许可、排除项和版本共同检查；新增根目录或提供商确认一次。

ROG 混杂 Windows 来源采用 `private_paths` 和精确 `remote_metadata_paths` 白名单；该配置不改变 Mac 的既有权限。新增路径不会自动通过 ROG 白名单；分类／白名单变化参与政策摘要，下次轮询撤销 VPS 旧缓存。见 [ROG 现场记录](pa0-rog.md)。

更改来源权限或排除规则后，新 CLI 请求立即按最新配置过滤；后台服务最多 30 秒后重新读取配置并核对。配置只能在本机编辑。

`search --channel feishu/pwa` 与 `catalog` 本身仍是本机序列化命令，不自行发送消息。出站节点与飞书／PWA 接入使用这些严格元数据结果，只包含获准字段，不含正文、摘录、原文 URI、附件路径或绝对根目录；未授权来源不输出标题和路径。搜索结果始终只传元数据；用户另行授权的非私密摘录和正文通过独立按需加密阅读流程提供，详见 [文本与恢复](pa0-text.md)。

## 服务

用户级 launchd 标签：`local.personal-asis.mac`。启动后立即核对，在线每六小时核对；通过 30 秒定时循环检测休眠后的时间间隙，唤醒后核对。来源不可用时每分钟重试。没有文件监听或网络端口。

本机数据目录权限为 `0700`，配置、数据库和服务日志为 `0600`，CLI 设置 `umask 077`。日志只记录运行计数与错误类型。日志文件当前不做自动轮转；索引和版本历史也尚无清理命令。

服务现已支持在本机配置 `coordinator.json` 后进行出站轮询，提供节点配对、Keychain 凭据、短期会话刷新、HTTPS 证书验证、租约及完成 outbox。无域名时支持显式 SSH 回环隧道；部署与实测状态见 [协调说明](pa0-coordinator.md)。加密备份与恢复演练现已由 Mac 更新脚本执行；独立备份和恢复密钥按用户选择暂缓，历史演练见 [文本说明](pa0-text.md)。不要向来源配置加入协调凭据。

历史过程见 [PA0 部署历史](archive/pa0-rollout-2026-10.md)，当前结果以 [最终验收](pa0-acceptance.md) 为准。
