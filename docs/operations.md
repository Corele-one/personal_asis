# 双 Agent 运行与回退

## Mac

`~/.local/bin/pi` 和既有 Finder／固定启动器均指向本仓库的 `scripts/asis-pi`，使用既有私密生产Python。私密profile为 `.local/pi-agent`；`life-sync.json` 已启用目标 `mac@35.209.202.207:22` 与相对日记目录 `Calendar/Journal/Daily`。Life根目录仍从既有本机 `sources.yaml` 获取，不在Git记录真实路径。

```sh
pi --check
pi --setup-sources
scripts/asis-life-sync
scripts/test-local-agent
```

交互启动先同步，未确认不写库。非交互／print／RPC／JSON需单独在终端运行同步。SSH使用现有本人认证和known_hosts，不自动接受新主机密钥，不把密钥放参数或配置。断网时继续Pi，后续启动重试读取；没有模型付费重试。

旧 `local.personal-asis.mac`、`.pa1`、`.tunnel` 已bootout并移出自动启动目录，原plist与固定启动器在忽略目录 `.local/migration-two-agent-20261020`。本机库、旧状态、语义模型和账本保留。小红书 `.xiaohongshu` 继续运行，使用原Keychain和新的固定版受限读写二进制；旧二进制保留。首次bootstrap失败后已重新bootstrap／kickstart核验，不将首次尝试当作一次成功。

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

## 验证边界

本轮已核验服务、实际SDK工具、SSH导出与状态上传、原生Pi的无网络合成TTY、窄写入UI拒绝、MCP工具目录和合成Dashboard浏览器。生产生活库最初检查为空，没有本人日记写入或聊天测试。真实新请求、提醒投递、账户登录有效性和平台写入需要各自场景验收。见[本轮记录](validation/two-agent-20261020.json)。

## 私密初始化文件

Mac：忽略目录 `.local/pi-agent/knowledge-context.md`、`initialization/evidence-manifest.json` 与VPS摘要预览；目录0700、文件0600。VPS：生活目录的 `bootstrap.json` 以及工作区的 `生活初始化背景.md`，供 `life_context` 和认证后的Dashboard读取。部署保留这些运行文件，不打包回Git。摘要含日期、相对来源与原文哈希，无Mac绝对路径；源内容改变后需重新核对，不声称已做后台失效传播。初始化不插入生活事件或提醒，不改日记。
