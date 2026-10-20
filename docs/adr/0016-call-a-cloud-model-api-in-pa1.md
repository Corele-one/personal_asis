# Call a cloud model API in PA1

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

PA1 will invoke a cloud model through the existing provider boundary rather than relying on manual copy-and-paste into ChatGPT. One selected online local node builds the context bundle and calls the provider directly; cross-node synthesis is deferred, so the VPS never aggregates source text. Every invocation remains constrained to an evidence-linked minimal context bundle.
