# Authorize Google Calendar from the service

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

The assistant service, not the interactive ChatGPT environment, will hold its own narrowly scoped Google OAuth authorization for the first calendar adapter. This permits the deployed assistant to read or write calendar events after a confirmation without relying on a desktop chat session's connection.
