# 保留的旧本地能力

默认入口已切换原生 Pi，VPS 生活功能由 AstrBot 增量插件负责。旧本地 Conversation Core／Work、角色、语义与词法检索、公开搜索、共享预算、来源许可和已付费检查点仍保留用于恢复历史工作与显式实验。

```sh
pi --engine conversation --continue
pi --engine legacy --continue
scripts/asis chat
scripts/asis web-chat
scripts/asis status
scripts/asis search 查询词
scripts/asis pa1 budget
```

旧付费步骤必须保留 provider-visible 序列化、结果未知不自动重试、原账本额度和撤权清理。不得把旧工作自动导入 Pi 原生会话或 AstrBot；不删除真实数据库／凭据。显式旧引擎不自动运行新日记同步。

旧远程协调、Relay、飞书卡片、PWA搜索和频道worker已移除；这些兼容命令不能重新引用退役模块。历史外部阅读适配器包括 Folo 只供既有显式缓存操作，不接入当前 Pi 主线；知乎／公众号仍排除。

旧模型／领域／检索质量记录保留在 `validation/` 中，均仅证明各自日期和场景，不能证明新架构已验收。旧本地合成回归仍运行；与已删除远程实现绑定的测试随实现退役。
