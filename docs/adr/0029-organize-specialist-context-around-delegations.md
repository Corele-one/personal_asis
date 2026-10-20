# Organize specialist context around delegations

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

Specialist roles retain confirmed domain goals and constraints, while work records are organized by independent delegations and relevant history is retrieved for each execution instead of indefinitely appending all domain work to one conversation. This preserves continuity, correction, and recoverability without making the runtime's chat thread the authority for the entire domain. Role, delegation, and session identities remain distinct; working hypotheses, confirmed facts, audit records, and readable memory keep their separate responsibilities, with storage and retrieval implementation still pending.
