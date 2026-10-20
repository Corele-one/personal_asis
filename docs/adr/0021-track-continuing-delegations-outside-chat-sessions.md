# Track continuing delegations outside chat sessions

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

Continuing work is represented by a Work Delegation with its own goal, scope, progress, results, and pause state; individual Delegation Runs belong to it, while chat can initiate or inspect the work. This supports continuity across conversations and available devices without making conversational history the only progress record. Creating a run or accepting a delegation does not confirm every user action task it may propose; existing task-candidate and external-write confirmation rules continue to apply.
