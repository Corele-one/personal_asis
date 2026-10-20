# Allow minimal MiMo context for nonsensitive reading content

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

> Updated scope, 2026-10-14: the user separately authorized current private Study/Life material for MiMo Flash analysis under an independent local grant. See [ADR 0032](0032-allow-private-model-context-with-explicit-provider-grants.md); the original decision below did not itself authorize that scope.

The user permits ordinary reading articles and nonsensitive personal annotations to enter minimal, relevant Context Bundles analyzed by MiMo, instead of limiting all reading inputs to local retrieval. Existing restrictions on private journals, health data, personal-model formation, and other providers remain in force; unclassified potentially sensitive content must be resolved locally before disclosure. Account-wide uploads are not authorized, and concrete local source policy, classification, budget checks, and the provider adapter still need implementation before live calls.
