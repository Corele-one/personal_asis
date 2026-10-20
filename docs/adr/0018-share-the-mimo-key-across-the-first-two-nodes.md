# Share the MiMo key across the first two nodes

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

> Updated scope, 2026-10-14: ROG is removed from the active deployment. When PA1 is authorized, configure the provider credential only in Mac's Keychain; do not provision a ROG copy. The shared-key choice below applies only if the user explicitly restores a second inference node. No model credentials or calls are enabled by this update.

Mac and ROG will use the same MiMo API key for PA1, with each copy stored only in that node's system credential store. This reduces initial account setup, but a compromise or rotation requires replacing the key on both nodes; future per-node keys remain an available hardening change.
