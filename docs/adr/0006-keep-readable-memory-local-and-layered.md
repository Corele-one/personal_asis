# Keep readable memory local and layered

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

The local node will maintain a readable Markdown memory ledger separated into personal-model material, open threads, and automatically generated conversation summaries. Reusable rules remain separately versioned in Git, while operation records remain their own audit data; this preserves the benefits of durable memory without making one opaque file the authority for facts, behavior, and history.
