# 文档索引

当前架构于2026-10-20切换为 Mac Pi + VPS AstrBot 协作；不再维护旧远程搜索／协调路线。

| 文档 | 内容 |
|---|---|
| [总规格](../SPECIFICATION.md) | 节点分工、同步确认、数据驻留与验收 |
| [使用指南](assistant-usage.md) | Pi、AstrBot、Dashboard 与写入操作 |
| [运行与回退](operations.md) | 配置、部署、检查与恢复 |
| [当前状态](project-status.md) | 已实现、已验证、仍待验收 |
| [实施计划](implementation-plan.md) | 本轮交付与后续事项 |
| [原生 Pi](native-pi.md) | 模型／会话、资料说明、窄写入扩展与费用 |
| [同步协议](daily-sync.md) | 事件、修订、删除与确认细节 |
| [平台读写](source-writes.md) | WUCAI／小红书具体操作与一次确认 |
| [资料授权](private-data-authority.md) | 已授权范围、凭据和保留边界 |
| [原生来源检查](native-source-status.md) | 之前只读抽查的日期与覆盖 |
| [外部阅读](external-reading.md) | 本机只读缓存兼容使用 |
| [阅读资料库](reading-library.md) | 分账号采集、统一检索、正文补取与覆盖边界 |
| [小红书](xiaohongshu-setup.md) | 固定版本 MCP 与会话配置 |
| [旧本地兼容](legacy-local.md) | Core／检索／旧付费会话保留范围 |
| [领域词汇](../CONTEXT.md) | 当前概念定义 |
| [ADR 0037](adr/0037-use-two-agents-and-confirmed-daily-sync.md) | 本轮架构取舍 |
| [初始化验证](validation/initialization-20261020.json) | 本轮Git同步与Codex读取后的私密内容初始化 |
| [阅读初始化验证](validation/reading-library-20261020.json) | WUCAI90天、双账号可见收藏与真实本机检索 |
| [本轮验收](validation/two-agent-20261020.json) | 合成、SDK、服务、SSH、UI 分别记录 |

`adr/` 中旧决策、`validation/` 中旧日期记录作为历史证据保留；旧服务运维、远程冻结计划与重复发布说明已删除。`Intention.md`／`advice.md` 是最初动机与建议，不定义当前架构。项目代理规则见 [AGENT.md](../AGENT.md)。
