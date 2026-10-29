# 双 Agent 运行与回退

Google Calendar MCP只读查询与受限写入提案均已部署；本人已授权 `calendar.events.owned` 并开启写入配置。写入仍要求每次预览后由本人私聊确认。权限边界、使用步骤、当前开关及回退见[接入说明](google-calendar-mcp.md)。合成SDK预检不代表真实模型自动选择或事件写入已验收。

## Mac

`~/.local/bin/pi_sync` 指向仓库 `scripts/pi_sync`，独立执行同步；系统 `sync` 保持原有行为。`~/.local/bin/pi` 和既有 Finder／固定启动器均指向本仓库的 `scripts/asis-pi`，使用既有私密生产Python。私密profile为 `.local/pi-agent`；`life-sync.json` 已启用目标 `mac@35.209.202.207:22` 与相对日记目录 `Calendar/Journal/Daily`。Life根目录仍从既有本机 `sources.yaml` 获取，不在Git记录真实路径。

```sh
pi --check
pi --setup-sources
pi_sync
scripts/test-local-agent
```

`pi`的所有启动模式直接打开本地Agent，不触发同步。`pi_sync`需在交互终端运行，真实日记未确认不写，派生资料库按本人既有共享授权刷新；非交互不拉取、刷新或提问。SSH复用本人认证及known_hosts，不自动接受新主机密钥，不把密钥放参数或配置。断网时保留状态，后续手动pi_sync继续；没有模型付费重试。

2026-10-26起，生活自述写入既有Freewrite下H4“聊天随记”，替代此前卡片；问候、命令、日期澄清、提醒和作息回执过滤，习惯／学习归原栏目。旧副本清理及迁移先预览确认。共享库按本人明确选择同步Life／Study笔记索引文本和阅读资料；不自动改写精选背景。`d`／`pi_sync --diff`查看精确原始diff，不重置日记游标。

旧 `local.personal-asis.mac`、`.pa1`、`.tunnel` 已bootout并移出自动启动目录，原plist与固定启动器在忽略目录 `.local/migration-two-agent-20261020`。本机库、旧状态、语义模型和账本保留。小红书 `.xiaohongshu` 继续运行，使用原Keychain和新的固定版受限读写二进制；旧二进制保留。首次bootstrap失败后已重新bootstrap／kickstart核验，不将首次尝试当作一次成功。

共享库部署随 `scripts/deploy-life-vps` 的代码清单发布，固定入口为 `personal_asis.shared_transfer`，Bot增加仅本人可用的 `shared_knowledge`。Mac的 `shared_sync_mode=text`、根目录身份及账号范围保存在忽略的life-sync.json中；首次刷新备份既有索引／阅读库，分别保留两端共享数据库。暂停将mode设off；回退使用既有VPS发布回退脚本，不删除数据库或清空游标。详见[共享库运行与限制](shared-library.md)。

回退Mac入口可恢复该备份的 `previous-asis-pi` 和三个plist再bootstrap；**只有同时回退VPS旧服务才恢复旧轮询／隧道**。小红书旧plist在私密运行目录的 `upgrade-rollback`；回退前核对其目标为原只读二进制。日记、源配置与真实账本不随入口回退覆盖。

本机[阅读资料库](reading-library.md)是显式CLI，不新增launchd或VPS服务。实际数据位于既有PersonalAsis home下的 `reading-library/library.sqlite3`；代码使用当前仓库和既有Python，不需要重新构建小红书二进制。`scripts/asis-library status` 检查账号条数和覆盖，检索／阅读不发网络请求，`fetch` 才按指定条目访问平台。

本次阅读初始化前的32份旧缓存、两个manifest和来源配置已备份到忽略目录 `.local/reading-library-backup-时间戳`，最新备份定位保存在 `.local/reading-library-latest-backup.txt`；未导出Keychain。回退新资料入口时，先关闭使用该库的进程、保留当前数据库副本，再恢复备份的私密资料说明或回退相应代码；旧缓存、旧数据库和平台原记录未被迁移修改，无需用旧副本覆盖它们。备份含私人正文，不进入Git或VPS；遗忘／撤权时须单独处理备份。

## VPS

当前入口 `https://35.209.202.207`，使用已有本人密码。保留nginx、原证书及续期timer。新服务：`personal-asis-dashboard.service`，loopback8766；AstrBot沿用 `astrbot.service`。旧协调8765、旧PWA服务和 `astrbot_plugin_personal_asis` 已从活动部署移除。

- `/home/mac/personal-asis-v2`：指向当前最小发布包，代码不依赖Mac环境。
- `/home/mac/personal-asis-v2-releases/`：发布包；`personal-asis-v2-rollbacks/`：各次切换前的插件、unit及恢复脚本，均保留回退。
- `/home/mac/astrbot/data/plugins/astrbot_plugin_life_agent`：新生活插件；配置保留原本人平台／身份绑定，不自动绑定新用户。
- `/home/mac/.local/share/personal-asis-life`：生活库、Mac状态及本人确认发布的选定摘要、私人Dashboard认证哈希与工作目录。目录0700，数据库／配置0600。
- 原协调目录和旧发布保留为回退材料，不再服务；不删除原数据、凭据或无关AstrBot插件。

```sh
ssh mac@35.209.202.207 -p 22
systemctl is-active astrbot.service personal-asis-dashboard.service
systemctl list-unit-files 'personal-asis-*'
```

## 后续部署

```sh
scripts/deploy-life-vps
```

脚本只上传必要Python模块、插件、Dashboard和部署脚本，附逐文件SHA256清单；不上传 `.local`、笔记、状态、凭据、Git或node_modules。远端保留原生活库和插件配置，先准备回退，再停服务、替换插件／发布链接、检查nginx并启动。异常会执行生成的回退脚本。部署不做真实模型生成、聊天消息或平台写入。

每次成功输出release和backup路径。后续增量回退：在对应 `personal-asis-v2-rollbacks/时间戳/` 运行 `./rollback.sh`。它只恢复前一代码／插件／unit选择，不回滚生活事件库、不删除新记录。最初迁移备份 `20261020_153545` 的脚本用于恢复旧架构；后续备份用于恢复上一v2版本。均需按目标核对，不混用回退脚本。

2.5.1催睡调整为01:00起每10分钟；首次加载会幂等延后仍按旧5分钟排定的后续提醒，已关闭及当晚晚安状态保留。轮次从当前睡前窗口内的投递占位计算，重启不从第一条重复。文案仅按需读取既有主动记录的合格学习主题，不新增表、外部请求或模型调用。

催睡使用同一生活库中独立的 `bedtime_policy`／`bedtime_delivery`／`bedtime_ack` 表；既有记录、同步游标和一次性事项表不迁移。新安装默认关闭，生产针对既有本人平台／私聊绑定开启，后续重启／部署保留规则。用户用 `/life sleep` 查看、`/life sleep off` 停用。切换本人绑定不会继续向旧身份发送。回退到2.0.1会停止催睡，不需要回滚或删除新表。

2.2.0部署新增共用的 `personal_profile.py`，保持原生活库和初始化文件；不会打包 `.local/pi-agent/initialization` 或自动上传本人背景。真正发布摘要前核对本人已确认的完整预览、来源哈希及接收范围，只写生活目录的 `personal-profile.json`（0600），保留旧版本回退。`draft` 文件不能作为记忆加载。代码回退不自动回滚私人背景；需要分别处理。

本人授权后的管理员与10条背景已应用；本次私密配置回退目录保存原 `cmd_config.json`、原背景是否存在及状态，目录0700，不进入Git。恢复管理员配置需要停AstrBot、恢复该配置、重启；背景可单独恢复／移除，避免以代码回退误撤销本人后续授权。

`profile_transfer` 是固定SSH接口，只读当前批准背景或按预览哈希条件替换它，锁文件为 `personal-profile.lock`。本机 `profile_sync.py` 在交互 `pi_sync` 中调用；`personal-profile-remote.json` 是最近快照，`personal-profile-next.json` 是待本人确认的完整候选，`personal-profile-sync-receipt.json` 保存发送占位及核对结果。它们都在私密忽略目录；本机启动Pi不调用SSH，也不自动加载快照正文。回退到没有 `profile_transfer` 的旧发布时，背景检查会报不可用，生活记录同步继续；不删除运行数据。

## 验证边界

本轮已核验服务、实际SDK工具、SSH导出与状态上传、原生Pi的无网络合成TTY、窄写入UI拒绝、MCP工具目录和合成Dashboard浏览器。生产生活库最初检查为空，没有本人日记写入或聊天测试。真实新请求、提醒投递、账户登录有效性和平台写入需要各自场景验收。见[本轮记录](validation/two-agent-20261020.json)。

## 私密初始化文件

Mac：忽略目录 `.local/pi-agent/knowledge-context.md`、`initialization/evidence-manifest.json` 与VPS摘要预览；目录0700、文件0600。VPS：生活目录的 `bootstrap.json` 以及工作区的 `生活初始化背景.md`，供 `life_context` 和认证后的Dashboard读取。部署保留这些运行文件，不打包回Git。摘要含日期、相对来源与原文哈希，无Mac绝对路径；源内容改变后需重新核对，不声称已做后台失效传播。初始化不插入生活事件或提醒，不改日记。
# 2.3.0 习惯／学习与主动简报（2026-10-26）

部署包增加 `life_tracking.py`、`life_attention.py`；Mac新增 `life_projection.py`。原SQLite中生活记录兼容增加 `tracking` 字段，持续目标与主动策略／投递使用独立表；不导入历史笔记或将旧学习清单设为目标。部署在停服前使用实际AstrBot Python运行 `validate-life-sdk.py`，合成临时库的发送接口禁止调用；停服后以SQLite备份接口保存 `life-before.sqlite3`（0600）再切换，回退代码不覆盖后续产生的生活数据。

本轮针对现有绑定本人启用每3天08:00–09:00简报及周一周报，首份分别为2026-10-29、2026-11-02。后续重启／代码部署保留策略，不重新计算或强制开启；停用用 `/life proactive off`，暂停用“稍后”／“这周别问”。2026-10-29综合简报改为复用当前AstrBot提供商每份至多一次有界生成，无新cron；只用既有共享副本，失败不自动重试。投递库预先占位 `sending`，未知不重试；下次定期回顾独立执行。旧代码回退会停止新worker能力，但不删除目标／策略／学习观测，私人备份和已发送平台副本分别保留。

2026-10-26阶段Dashboard保持只读认证，日期查询只改变显示范围；未登录API必须401。2026-10-27新增的本人反馈写入边界见下文。现场SDK导入、服务运行及合成UI不代表真实模型识别质量、实际早间投递或真实日记确认写入通过。

## 2.5.0：记忆来源与PWA反馈

部署包加入life_intake／life_feedback和插件feedback_agent。停服务后先备份原生活库，再运行幂等的reconcile_intake：原始消息不删，补capture_source并清除不符合本人实际行为证据的派生观测，变更追加版本以供下次同步。普通聊天仍作为对话记忆提供给助手；不进入Obsidian。

PWA沿用同一HTTPS与本人会话，新增/api/feedback GET／POST；POST必须有Origin与CSRF，写入同一私密生活库队列。AstrBot原生Agent消费队列，使用当前本人渠道选中的提供商，只开放单记录纠正工具。重启将running标为unknown，不自动重发付费调用；用户先核对前后回执。无需新端口或系统服务。反馈worker和催睡／简报worker独立，等待模型不阻塞到期检查。该入口不执行平台发送，也不开放Computer Use或Mac文件写入。
