# Allow private model context under an independent provider grant

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

> Superseded scope, 2026-10-14: the user subsequently confirmed source-wide standing permissions, owner-channel disclosure, remotely expressed owner authorization and automatic attributable memory. See [ADR 0033](0033-use-standing-personal-data-and-maintenance-authorizations.md). The current-file-only limits below record the earlier step.

On 2026-10-14 the user explicitly allowed the personal assistant to read and analyze all current Study and Life files, including diaries and health records, using the selected MiMo Flash provider: a private classification should govern handling rather than make those records unusable by the assistant. Private content therefore requires an independent, locally stored provider grant instead of an unconditional cloud-model prohibition; processing remains relevant minimal-context retrieval, and revocation takes effect before a call and before returning its result.

This decision preserves private classification, channel disclosure restrictions, shared budgets, and the separation between tentative interpretation and confirmed personal facts. It does not authorize another provider, a new source root, future file paths, permanent personal-model formation, diagnosis, or publishing private results; current grants enumerate existing files, and PA1 policy is stored separately from PA0's production source configuration.
