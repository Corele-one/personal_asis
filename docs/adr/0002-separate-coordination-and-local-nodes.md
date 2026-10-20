# Separate the coordination node from the local node

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

> Updated scope, 2026-10-14: the user removed ROG from operation and maintenance because its content is not useful enough to maintain. PA0 now requires only Mac, VPS, PWA and Feishu; the two-node acceptance gate below is historical. Nonprivate PWA reading uses separately authorized ephemeral ciphertext relay, never VPS plaintext storage. See Mac-only operation（旧说明已退役，见[当前规格](../../SPECIFICATION.md)）.

The VPS will provide low-sensitivity coordination, notifications, and mobile entry, while trusted local nodes retain the personal indexes and perform access to personal source systems and sensitive work. PA0's full acceptance gate includes both Mac and ROG local nodes, as specified by ADRs 0013 and 0014 and the current specification; implementation may begin with the Mac slice. PA0 permits only policy-authorized metadata on the VPS, not derived caches, source text, summaries, complete indexes, or local credentials. Derived caches are a deferred deployment choice for later stages. Searches wait for offline nodes and label available results as partial, preserving a continuously reachable mobile channel without turning the VPS into the personal archive.
