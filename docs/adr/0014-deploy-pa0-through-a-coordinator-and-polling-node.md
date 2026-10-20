# Deploy PA0 through a coordinator and polling local node

> 历史决策：本文保留原决定与日期。2026-10-20 的当前节点分工、数据驻留与入口以 [ADR 0037](0037-use-two-agents-and-confirmed-daily-sync.md) 和 [当前规格](../../SPECIFICATION.md) 为准；旧远程服务已退役。

> Updated scope, 2026-10-14: only Mac is active and maintained; ROG polling, its tunnel and Windows startup task are disabled. Outbound polling and offline recovery remain required for Mac; historical two-node deployment does not require restoring ROG. See Mac-only operation（旧说明已退役，见[当前规格](../../SPECIFICATION.md)）.

PA0 will deploy a VPS coordinator, Mac and ROG local nodes that initiate outbound polling, and a minimal private PWA. The ROG node runs as a WSL user service. The PWA submits searches to the coordinator; each available local node executes local retrieval and returns evidence results, while work for sleeping nodes waits, preserving phone access without exposing either device service to the public internet.
