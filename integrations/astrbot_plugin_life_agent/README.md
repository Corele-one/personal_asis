# AstrBot 生活增量插件

复用 AstrBot 模型／会话，增加本人生活原话、可修正整理、明确时间事项提醒、生活工作区工具。所有入口检查配置中的唯一 `owner_platform` + `owner_id` 且只接受私聊。没有自动绑定和群聊收录。

主存储实现是 `src/personal_asis/life_store.py`；部署时复制为插件的 `life_store.py`，不依赖 Mac 项目或旧 Relay。`scripts/deploy-life-vps` 只打包必要模块、插件与 Dashboard，验证哈希、备份、切换；失败自动恢复旧代码与服务，不删除生活库。

配置 schema 自带，首次迁移从已有本人绑定生成；后续部署保留配置。普通文本记录不等于模型已成功整理，工具成功前不能回报已整理。提醒 `sending`／`unknown` 不自动重发。

完整范围见[项目规格](../../SPECIFICATION.md)、[运维](../../docs/operations.md)。
