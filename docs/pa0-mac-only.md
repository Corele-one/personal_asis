# PA0 Mac 单节点运行

2026-10-14，用户明确选择“只用 Mac 检索，停用 ROG 节点”，原因是希望减少资料维护。本决定覆盖此前要求两个节点持续运行的部署假设；保留多节点代码和历史验收能力。

## 当前状态

- 日常搜索只使用 Mac：Study 267 个、Life 179 个 Markdown，沿用既有权限。PWA／飞书和非私密按需加密阅读继续使用。
- ROG 的 `personal-asis.service`、`personal-asis-tunnel.service` 已停止并禁用；Windows 任务 `PersonalAsis-ROG` 已禁用。来源配置和索引保留，不重新核对或删除 Windows 原资料。
- VPS 的 `rog` 注册设为停用，清除短期会话、配对码和远程缓存结果，保留长期凭据摘要。新任务只创建 Mac 工作，历史任务视图跳过停用节点，不产生永久等待。
- ROG 的 3,309 个本机文档索引、整理／验收报告及 `F:\Backup\PersonalAsis\ROG` 加密备份保留。运行状态的停用记录放在仓库外。
- Mac 本机加密备份已恢复验证；向 ROG F 盘复制的等待操作未完成，临时密文管道已清理。此项额外副本不作为当前单节点检索范围的前提，不能报告为已有异机备份。

Mac 关机或休眠时，新搜索等待恢复；正文必须由在线 Mac 读取和加密返回。VPS 保存获准元数据，不保存来源明文或备份密钥。停用 ROG 不扩大 Mac 的读取范围、私密正文或模型权限。

## 维护与可选恢复

日常只需在 Mac 的既有来源中保存资料。节点会定期核对索引；更改来源权限仍只在 Mac 本机进行。无需维护另一份 ROG 资料库。

节点启停是 VPS 本机管理员操作，没有 PWA 权限切换按钮：

```sh
# VPS：停用节点；保留本机资料和已有 enrollment
scripts/asis --home /home/mac/.local/share/personal-asis-coordinator coordinator disable --node-id rog
# 只有用户以后明确决定恢复 ROG 时才执行
scripts/asis --home /home/mac/.local/share/personal-asis-coordinator coordinator enable --node-id rog
```

恢复 ROG 后还需在 ROG 本机重新启用索引／隧道服务及 Windows 开机任务。`disable` 保留 enrollment，`revoke` 则撤销长期凭据并要求重新配对；二者用途不同。

## 验证

合成测试验证停用后的短期会话失效、旧任务不再等待或暴露该节点结果、新任务只分派启用节点，以及显式恢复后原 enrollment 可继续使用。现场验证记录包括 ROG 服务／开机任务状态、生产启用节点列表、新旧任务节点范围及保留索引／备份计数。历史跨设备验收仍见 [ROG](pa0-rog.md) 和 [文本记录](pa0-text.md)，不冒充当前仍运行两个节点。

本次运行 98 项合成测试，ROG 环境 95 项通过、3 项 AstrBot 专用检查跳过；专用 3 项已在 VPS 的实际 SDK 解释器通过。生产检查确认仅 `mac` 启用，ROG 会话数为零，13 项旧搜索视图均排除 ROG，新建 PWA／飞书渠道任务均只派发 Mac；本次没有发送飞书测试消息。切换验收时 Mac 离线，因此两项新任务仅等待 `mac`，尚未现场确认它们恢复后的完成结果。ROG 的 3,309 个索引文档和两份加密归档保留，后台服务及开机任务均禁用。
