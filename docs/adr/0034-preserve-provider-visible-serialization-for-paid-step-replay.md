# Preserve provider-visible serialization when replaying committed paid steps

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

Tool results become JSON text inside the model transcript, so sorting stored object keys can change a paid request's fingerprint even when its data is equivalent; the real Study recovery exposed this failure. Preserve the existing tool protocol's field order when reconstructing committed steps, and persist final-only request mode for new steps, instead of silently recalculating old fingerprints or repeating paid calls. A future wire-format change must preserve or explicitly version this representation; fresh source-policy checks, payload expiry and unknown-result blocking still apply before replay.
