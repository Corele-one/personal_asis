# Protect the control console with strong web authentication

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

The VPS-hosted control console will be a private HTTPS site protected by the user's independent strong authentication, preferring passkeys and allowing appropriate fallback authentication. It is the channel for sensitive confirmations and audit views, rather than exposing these by default through a chat platform.
