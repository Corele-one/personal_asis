# Back up local state with user-held keys

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

> Updated scope, 2026-10-14: local encrypted state backup and restore were validated, but the user deferred independent backup copies and recovery-key preparation because source data already has user-managed cloud backups. These are outside current PA0 acceptance; no periodic cloud-state backup or key export is enabled. Existing local archives and credentials remain. See final acceptance（旧说明已退役，见[当前规格](../../SPECIFICATION.md)）.

Each local node will periodically produce encrypted backups of its SQLite state, memory ledger, and configuration to user-controlled cloud storage or offline media. The VPS will never receive the decryption key or act as the plaintext backup authority, preserving recovery of task and audit state without changing the personal-data boundary.
