# Prefer local conversations and opt-in specialists

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

Accepted 2026-10-19 under the owner's explicit product direction change.

The default interaction is a local, channel-independent conversation with one main agent. Sessions, turns and runs are independent of continuing Work Delegations. The model can answer directly or select a bounded, host-authorized tool; ordinary chat does not create specialist subwork or imply background permission. Python retains transactional state, source authority, permissions, budgets and billing/replay checks; Pi remains replaceable loop infrastructure.

This revises ADR 0022's default supervisor-plus-three-specialists organization. Research, Career and Life roles, goals and histories remain available through existing interfaces and future opt-in delegation. ADR 0025 applies when specialist collaboration actually occurs, rather than requiring it for every conversational request. ADRs 0019, 0021, 0026, 0029, 0033 and 0034 retain their boundaries. The cost of this choice is a separately versioned conversation contract and explicit migration work instead of treating every conversational turn as a business delegation.

P0 adds conversation-v1 alongside existing paid Agent, web and terminal protocols; no existing paid checkpoint is rewritten or retried. It does not deploy production services or change existing channel APIs. Later channel adapters must authenticate and apply channel disclosure policy before calling the same Core API. Local-first permits later remote access through a bounded relay while keeping private content, keys and authoritative state on the approved Mac. See audit and rollout（旧说明已退役，见[当前规格](../../SPECIFICATION.md)）.
