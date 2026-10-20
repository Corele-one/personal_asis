# Route specialist collaboration through the supervisor

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

2026-10-19 scope revision: [ADR 0035](0035-prefer-local-conversations-and-opt-in-specialists.md) makes a single main conversational agent the default. This decision remains applicable to explicitly selected specialist collaboration; the original decision below is retained as history.

Requests for cross-domain specialist assistance pass through the Supervising Agent, which routes work and consolidates the necessary results while system policy checks enforce access and disclosure. This gives collaboration one traceable route for scope, duplicate-work handling, and aggregate budgets instead of allowing unrestricted peer delegation. Routing can be automatic within the delegation's approved scope; execution concurrency and the concrete work protocol remain undecided.
