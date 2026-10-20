# Keep personal content out of Git

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

The private Git repository will version implementation, specifications, reusable rules, and sanitized test fixtures only. Original notes, personal indexes, context bundles, and operation records remain outside the repository, so rule review and rollback do not turn the source repository into a copy of the user's personal archive.
