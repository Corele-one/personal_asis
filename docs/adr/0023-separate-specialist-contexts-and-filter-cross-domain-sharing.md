# Separate specialist contexts and filter cross-domain sharing

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

Specialist Agents keep separate Domain Working Contexts, and the Supervising Agent receives the results needed for the current work rather than using one shared context for all roles. Cross-domain transfers remain subject to source, model-provider, and channel permissions, preserving domain continuity without turning a specialist assignment into broader personal-data access. Working hypotheses do not automatically become confirmed personal facts or long-term memory; context storage and retention remain to be designed.
