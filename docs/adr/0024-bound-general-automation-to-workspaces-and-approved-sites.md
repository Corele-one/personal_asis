# Bound general automation to workspaces and approved sites

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

> Updated scope, 2026-10-14: [ADR 0033](0033-use-standing-personal-data-and-maintenance-authorizations.md) records explicit standing permission for existing-project maintenance and owner replies/notifications. Operations outside those scopes still require exact confirmation; source originals remain read-only.

General scripts and commands may generate code and artifacts in dedicated workspaces while original sources remain read-only; changing existing files, installing software, or changing system configuration requires separately defined permission. Browser capabilities include public pages and explicitly approved authenticated sites for reading and preparing content, while submissions, sends, autosaves, and other remote changes remain subject to external-write confirmation. This retains general automation beyond domain adapters while bounding local and account effects; execution isolation and credential/session integration are not yet selected or implemented.
