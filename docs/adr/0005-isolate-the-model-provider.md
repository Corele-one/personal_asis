# Isolate the model provider

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

Business workflows will depend on a small model-provider boundary that returns structured, evidence-aware results, not on a particular cloud model SDK or prompt format. The first provider can be the user's preferred cloud service, while later provider, cost, and privacy changes do not require rewriting task, indexing, or rule behavior.
