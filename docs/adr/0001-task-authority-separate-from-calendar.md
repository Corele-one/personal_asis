# Keep task authority separate from the calendar

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

The assistant will maintain its own task authority, because tasks can be pending, blocked, completed, or lack a scheduled time. After the user confirms a time-bound arrangement, the assistant may create or update a Google Calendar event as an external projection; it will not treat the calendar as the sole task store or perform bidirectional synchronization.
