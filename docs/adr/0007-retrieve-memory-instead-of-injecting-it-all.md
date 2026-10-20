# Retrieve memory instead of injecting it all

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

Each inference will include only a concise stable personal model and applicable reusable rules by default. Conversation summaries and open threads are retrieved when relevant to the active question, which preserves continuity while bounding privacy exposure, cost, and the influence of stale context.
