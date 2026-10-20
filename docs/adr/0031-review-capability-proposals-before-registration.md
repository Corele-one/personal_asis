# Review capability proposals before registration

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

Successful temporary scripts or workflows can produce versioned Capability Proposals describing purpose, dependencies and call relationships, required permissions, validation, and rollback; only a user-confirmed version becomes a registered long-term tool or skill. This allows capability accumulation while preventing one successful execution from silently changing future executable behavior. Registration does not authorize later external writes or wider source/provider access, and material version or permission changes require renewed review; capability proposals remain distinct from reusable-rule proposals.
