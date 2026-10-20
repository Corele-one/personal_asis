# Use Xiaomi MiMo as the first model provider

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

PA1 will implement Xiaomi MiMo as the first cloud-model adapter through its documented OpenAI-compatible API format. The adapter keeps endpoint, model name, and credentials as deployment configuration rather than business rules, so a later provider can replace it without changing retrieval, evidence, task, or policy behavior.
