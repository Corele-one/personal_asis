# Use SQLite for local transactional state

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

Each local node will use SQLite for index metadata and transactional assistant state such as tasks, confirmation scopes, reminder deliveries, and operation records. Readable memory and rules remain Markdown, while source originals remain in their source systems; a cloud database is not the authority for personal state.
