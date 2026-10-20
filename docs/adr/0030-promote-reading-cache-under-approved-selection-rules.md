# Promote reading cache under approved selection rules

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

The Agent may automatically retain selected cached bodies as local Personal Selections under user-approved rules, with an Agent Selection marker, reasons, original provenance, and revocation. This reduces manual maintenance without presenting agent choices as the user's own reading, endorsement, or confirmed personal facts; it does not write favorites back to source platforms or expand data-disclosure permissions. Removing a local selection does not automatically create an exclusion: later rule-based selection remains allowed and must again satisfy source permissions and record its provenance. Concrete rules and limits remain to be configured; source deletion or permission revocation cannot be bypassed by reselection.
