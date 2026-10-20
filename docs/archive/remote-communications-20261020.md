# VPS／机器人／远程通信归档清单

归档日期：2026-10-20。用户决定先完成本机 Pi Agent，远程部分作为下一阶段。本清单表示代码原位冻结和文档归档，不表示删除能力、撤销授权或已停止线上服务；本轮未 SSH 登录、重启或卸载服务，也未核验当前线上状态。原验收记录只证明各自日期的结果。

## 原位保留的实现

| 边界 | 路径 |
|---|---|
| VPS 协调、协议与本机轮询 | `src/personal_asis/{coordinator,transport,node}.py` |
| 加密阅读／分析／Agent Relay 与 Worker | `src/personal_asis/{evidence,analysis_channel,agent_channel,retrieval_channel}.py` |
| 飞书交互 | `src/personal_asis/{feishu,agent_feishu,feishu_cards}.py` |
| 旧远程 PWA／认证／静态页面 | `src/personal_asis/{pwa,web_auth}.py`；`web/{index.html,app.js,app.css,sw.js,manifest.webmanifest}` |
| AstrBot 插件 | `integrations/astrbot_plugin_personal_asis/` |
| 服务／隧道／部署 | `src/personal_asis/service.py`；`scripts/deploy-coordinator`；`deploy/` |
| 脱敏配置样例 | `config/coordinator.example.json`；`config/pwa.example.json` |

本机 `conversation_web.py` 与 `web/conversation.*` 属于当前 Core 客户端，不归入旧远程 PWA。`disclosure.py` 是宿主权限能力，不属于 Relay。原始资料、私密配置、数据库、凭据、已付费检查点及账本不搬迁或复制进归档。

旧命令 `coordinator`、`node`、`daemon`、`service`、`tunnel`、`pwa`、`feishu`、`pa1 channel-worker/channel-install` 保留显式兼容入口；只有主动调用相应命令才加载远程实现。保留入口不构成新建远程工作或部署授权。

## 材料与历史验收

- [原远程使用指南](remote-usage-20261020.md)、[调整前 README 快照](project-readme-20261020.md)。
- [协调服务](../pa0-coordinator.md)、[Mac 旧单节点运维](../pa0-mac-only.md)、[旧 PWA](../pa0-pwa.md)、[飞书](../pa0-feishu.md)。
- [本人渠道 Agent](../agent-channels.md)、[Agent PWA](../agent-pwa.md)、[飞书卡片](../feishu-cards.md)。
- [PA0 历史验收](../pa0-acceptance.md)、[PA1 历史验收](../pa1-acceptance.md)、[部署历史](pa0-rollout-2026-10.md)。

旧远程合成测试保留在 `tests/test_{coordinator,node,service,evidence,analysis_channel,analysis_http,agent_channel,retrieval_channel,feishu,agent_feishu,feishu_cards,pwa,web_auth,astrbot_plugin,context_commands,context_ui}.py`，相关浏览器脚本为 `tests/context-ui.cjs`。它们可单独用于未来兼容检查，不导入本机日常验收套件。

未来接线按[下一阶段计划](../remote-communications-plan.md)进行；当前任务和本机验收以[本机 Pi 主线](../local-agent-focus.md)为准。
