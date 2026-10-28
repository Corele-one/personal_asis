# AstrBot Google Calendar MCP

## 当前结果（2026-10-28）

给本人操作的分步清单见[HTML 配置教程](google-calendar-mcp-tutorial.html)；只读PKCE脚本为[`scripts/google-calendar-oauth-bootstrap.py`](../scripts/google-calendar-oauth-bootstrap.py)，扩权脚本为[`scripts/google-calendar-oauth-upgrade-write.py`](../scripts/google-calendar-oauth-upgrade-write.py)，激活脚本为[`scripts/activate-google-calendar-write.py`](../scripts/activate-google-calendar-write.py)。

Google Calendar只读查询已接入并启用。本人于2026-10-28完成`calendar.readonly`授权；VPS令牌格式和0600权限核对通过。上游MCP真实`list-calendars`只读调用成功，AstrBot服务状态为active。

本人提出开启写入后，Life插件`2.7.0`已部署受限写入提案工具，并经实际AstrBot `4.27.3` SDK合成预检通过。本人已在Google同意增加`calendar.events.owned`，VPS核对令牌仅包含`calendar.readonly`与`calendar.events.owned`，权限0600；写入开关已启用，启动日志确认写入提案工具上线。真实日历事件还没有被修改。

同日浏览器配置进展：本人当次确认Google用户数据政策后，已核对Google Auth Platform初始化完成；应用名`AstrBot Calendar`，External测试模式。桌面客户端`AstrBot Calendar VPS`已创建，Google Calendar API页面显示“已启用”。本人已将下载的Desktop OAuth JSON放入仓库根目录并明确要求转入VPS；随后已转入`/home/mac/astrbot/data/google-calendar-mcp/gcp-oauth.keys.json`，远端格式检查通过、权限0600，工作区副本已删除；文件内容未展示或写入日志。本人已把Gmail账号加入OAuth测试用户。

OAuth进展：最初在浏览器遇到空白页，且VPS gcloud ADC流程要求额外`cloud-platform` scope，因此均未使用。随后本人按只读PKCE流程在VPS完成授权；屏幕回执和远端核对确认唯一scope为`calendar.readonly`，刷新令牌与访问令牌存在且`tokens.json`为0600。临时授权脚本、gcloud临时配置和SSH转发均已清理。

复用AstrBot已经安装的MCP SDK，通过现有Life插件内的窄工具封装，以stdio调用现成的`@cocal/google-calendar-mcp@2.7.0`（[上游源码](https://github.com/nspady/google-calendar-mcp)）。不将上游工具直接全局注册，因为原生全局注册无法在每次工具调用时验证本人私聊边界；封装只允许七项只读工具，并通过插件现有`owner(event)`校验平台、发送者和私聊类型。不另写Google Calendar API适配器或主Agent。

## 复用检查

- 实际VPS为AstrBot 4.27.3，已有原生MCP客户端，配置入口为`data/mcp_server.json`；检查时没有Google Calendar专用插件或原生Calendar MCP条目。
- [官方插件市场索引](https://github.com/AstrBotDevs/AstrBot_Plugins_Collection)本轮取得1,332条收录，没有找到Google Calendar专用条目。市场中的[AstrScheduleSync](https://github.com/D1ff1culTT/astrbot_plugin_AstrScheduleSync)对接Radicale CalDAV，不是Google Calendar OAuth/MCP。
- [Google官方远程MCP](https://developers.google.com/workspace/calendar/api/guides/configure-mcp-server)仍要求Workspace Developer Preview Program资格，当前没有确认本人具备该资格，不以此作为默认方案。
- [AstrBot官方MCP指南](https://docs.astrbot.app/use/mcp.html)确认支持stdio；本轮另以实际安装SDK验证，未用新文档替代版本核对。

## VPS准备状态

安装范围仅为服务用户`mac`，没有更改AstrBot Python依赖或系统Node：

- Node.js `v22.23.4`，官方分发文件SHA-256校验通过，位于`/home/mac/.local/opt/google-calendar-mcp/node-v22.23.4-linux-x64/`。
- npm包固定`@cocal/google-calendar-mcp@2.7.0`，安装位于`/home/mac/.local/opt/google-calendar-mcp/app-2.7.0/`，使用`--ignore-scripts --omit=dev`，保留锁文件。
- 私密状态目录`/home/mac/astrbot/data/google-calendar-mcp/`权限0700，Google OAuth客户端与`tokens.json`权限均为0600。
- Life插件配置`google_calendar_enabled=true`、`google_calendar_write_enabled=true`，仅在既有owner绑定的平台私聊生效；没有将上游Calendar工具全局注册，`data/mcp_server.json`中的其他MCP配置保持原状。
- 上游服务器环境限制七项读取工具：`list-calendars`、`list-events`、`get-event`、`search-events`、`get-freebusy`、`get-current-time`、`list-colors`，时区为Asia/Shanghai。上游仍额外注册`manage-accounts`，但Life插件不向AstrBot Agent暴露该工具，调用端也只接受上述七个名称。实际查询仍应显式传入时间范围和时区。

## 安全范围与验收边界

OAuth授权已完成。密钥内容、授权码和令牌不得贴到聊天、命令参数、Git或日志。所选项目已启用Google Calendar API；External且处于Testing时，账号已加入Test users，刷新令牌通常七天到期，见[上游授权说明](https://github.com/nspady/google-calendar-mcp/blob/main/docs/authentication.md)。

当前令牌scope为`https://www.googleapis.com/auth/calendar.readonly`和`https://www.googleapis.com/auth/calendar.events.owned`。Google将后者定义为对本人拥有的日历查看、创建、修改和删除事件；它不包含日历共享设置管理。[Google官方scope说明](https://developers.google.com/workspace/calendar/api/auth)。

上游2.7.0的工具过滤仍额外注册`manage-accounts`，本轮在实际SDK握手中已复现。无论读写，Life插件都不把该工具注册给AstrBot Agent，只按本地七项读取／三项写入白名单接收上游调用。不能把上游`ENABLED_TOOLS`过滤当成该账号管理工具已从服务器清单移除的证据。

插件版本`2.7.0`在既有Life插件内调用上游stdio MCP会话。`google_calendar_read`每次调用都校验既有owner平台、发送者ID和`is_private_chat()`；`google_calendar_propose_write`在代码、OAuth scope及配置开关均允许时，只生成提案，不直接执行写入。新增／修改／删除事件仅支持本人拥有日历上的单个非重复事件；创建不含参会者，修改／删除拒绝现有参会者，且通知参数固定为`none`。修改／删除先读取并保存事件快照，确认时重新读取；若事件已变化则拒绝。预览绑定同一私聊，有效五分钟、一次使用，服务重启会清空待确认操作。确认前没有写调用；执行前先消费确认码，未知结果不自动重试。上游`manage-accounts`不对Agent开放，只允许三项写工具白名单；没有开放批量写、邀请回复、日历创建或日历共享管理。读取参数和结果仍有限制。

仅插件部署备份与回退可用。当前`2.7.0`部署前备份位于`/home/mac/astrbot/plugin_backups/google-calendar-20261028_173132_824459`；较早的完整撤出备份仍为`/home/mac/astrbot/plugin_backups/google-calendar-20261028_164752_958943`。本人已完成scope同意；线上写入开关为true、服务active、写入工具启动标记已核验。实际SDK合成预检覆盖提案不直接写入、确认码执行一次及本人边界；真实MCP `list-calendars`读取成功且没有打印日历内容。尚未执行任何真实事件写入；真实模型调用与本人私聊体验仍待验收。

写入提案已开启；每次增删改仍必须展示目标日历、事件、时间及时区和完整参数，并取得本次确认；提醒、生活记录或本轮开启功能的授权不等于某一次事件操作确认。未知写入结果不自动重试。

## 已验证与未验证

实际AstrBot 4.27.3 SDK完成Life插件工具注册和合成owner边界预检，明确拒绝`manage-accounts`、群聊及其他发送者。真实OAuth令牌经上游MCP执行`list-calendars`成功；AstrBot启动日志确认连接了7个读取工具，`astrbot.service`为active。

真实事件读取、令牌刷新续期、真实模型自动选择该工具、本人聊天体验尚未验证。Google Testing模式下刷新令牌仍可能有期限，届时只需重新完成同样的只读OAuth流程。

## 回退

回退备份包含旧Life插件和原始插件配置；回退时恢复这两项并重启`astrbot.service`。撤权需同时在Google账号侧撤销AstrBot Calendar授权并删除VPS令牌；关闭Life插件开关或回退插件本身不等于撤销Google授权。
