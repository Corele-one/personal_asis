# Resume interrupted runs on the owning node

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

The first agent-capable version preserves interrupted work on its executing Local Node and waits for that node to return, then resumes from durable progress rather than automatically transferring the run to another device. This avoids prematurely requiring encrypted runtime-state replication and cross-device execution ownership while retaining offline continuity; coordinator-visible state remains policy-limited. Checkpoint and unknown-result recovery still need implementation, and resumption must not blindly repeat external side effects.
