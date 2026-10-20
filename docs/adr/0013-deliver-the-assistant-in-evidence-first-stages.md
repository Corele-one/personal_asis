# Deliver the assistant in evidence-first stages

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

> Updated scope, 2026-10-14: PA0 uses Mac as its only active local node. ROG is disabled and no longer a delivery prerequisite; the original multi-node rollout below is retained as decision history. Later stages still follow PA0 acceptance. See Mac-only operation（旧说明已退役，见[当前规格](../../SPECIFICATION.md)）.

The project will deliver PA0 source evidence search first, then add context bundles and hybrid retrieval, task candidates, calendar confirmation, memory and rules, and email in later independently verifiable stages. PA0 uses SQLite FTS5, explicit indexing and reconciliation, Mac plus ROG nodes, a state-first PWA, and limited Feishu search interaction so durable evidence behavior is proven before model calls, vectors, or file watchers add failure modes.
