# Keep assistant authority outside the replaceable agent runtime

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

The assistant owns work goals, user action tasks, data and memory policy, permission and confirmation scopes, budgets, device coordination, and results; a replaceable agent runtime supplies model/tool execution and reusable session or recovery mechanisms. This separates durable personal-assistant behavior from framework-specific defaults while reusing execution infrastructure, instead of making a complete existing agent the system authority or rebuilding every agent primitive. Pi is a candidate to validate, not a selected implementation; runtime session storage does not automatically become task, permission, or memory authority.
