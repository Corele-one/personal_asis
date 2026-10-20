# Bind confirmation to the exact action

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

> Updated scope, 2026-10-14: [ADR 0033](0033-use-standing-personal-data-and-maintenance-authorizations.md) records explicit standing permission for existing-project maintenance and owner replies/notifications. Operations outside those scopes still require exact confirmation; source originals remain read-only.

Each external write requires a confirmation scope bound to its precise target, content, and key parameters for a limited time. A changed action requires a new confirmation, preventing a prior approval for one calendar event, email, or submission from silently authorizing another.
