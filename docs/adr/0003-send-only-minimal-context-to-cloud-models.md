# Send only minimal context to cloud models

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

The local node will index and retrieve personal material, then send a cloud model only the context bundle needed for the active question. Original vaults and full indexes remain local, and each bundle must be traceable through an operation record; more restrictive source-specific policies, such as keeping journals entirely local, remain possible later.
