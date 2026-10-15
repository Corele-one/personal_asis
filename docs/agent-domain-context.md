# 本机领域目标与约束

当前交付总览见[项目完成情况](project-status.md)；本页保留该切片的范围与验收快照，最新串行角色／飞书卡片发布见[本轮记录](validation/agent-roles-20261015.json)。

2026-10-15：已实现领域目标／约束，以及[相关委托历史检索](agent-work-history.md)。本人可明确保存、查看、替换和删除目标／约束，本机按需 Agent 可显式采用；不是四角色协作或自动长期记忆的完整交付。没有从 Study／Life 自动提取个人事实，也没有创建真实个人目标。

## 使用

以下以合成目标示意，实际内容只存仓库外的运行目录。使用既有生产 Python；`scripts/asis-agent` 还会启用离线模型环境：

```sh
export ASIS_PYTHON="$HOME/Library/Application Support/PersonalAsis/pa1-env/bin/python"
scripts/asis domain set --domain research \
  --goal '合成示例：整理缓存一致性问题的证据' \
  --constraints '区分材料支持的结论与未知项' \
  --source study --request-id domain-research-001 --allow-model
scripts/asis domain show --domain research
scripts/asis domain list
scripts/asis-agent run --domain research --source study \
  --query '现有材料能支持哪些缓存一致性结论？' --request-id research-run-001
scripts/asis-agent resume --request-id research-run-001
scripts/asis domain forget --domain research --request-id forget-research-001
```

领域 ID 为既有 `supervisor`、`research`、`career`、`life`。省略 `--allow-model` 只允许本机保存，后续 `agent run --domain` 会明确拒绝；加入该参数只许可本条文本进入既有 MiMo，不新增根目录、模型提供商或预算。`--source` 必须显式给出已有来源；模型使用还需当前来源独立许可。领域名与来源 ID 不等同。

每次有效修改使用新 `--request-id`，替换整条目标和约束。旧编号重复请求返回当前记录，不回滚到旧目标；同编号不同内容拒绝。新编号重新确认后更新复核期；重复旧请求不能延长复核期。`list` 只显示领域、修订、许可和复核元数据，正文通过 `show` 查看。

`agent run` 只有显式选择领域时才读取该目标，不自动猜测领域或拼接其他领域目标。模型上下文标注为本人确认的目标／约束，只包含所选领域名和文本；来源根目录摘要和路径不发送。恢复沿用原修订和已付费输入，不接受更换领域。现有 PWA／飞书的 Agent 请求尚不选择领域，也没有远程修改此配置的入口。

## 存储、撤销与复核

记录保存在本机 `work.sqlite3`，文件权限 600，默认 90 天复核；到期后保留可查看记录并停止供模型使用，需本人新请求重新确认。凭据／显式排除内容在本机拒绝，不上传给模型分类。

记录绑定来源根目录身份及当前 MiMo 许可，运行和每一步都重新核验。修改或忘记某领域后，清理采用旧修订的会话、结果和检查点，其他领域及未选择领域的工作保留。旧工作编号保持不可重新执行，重新分析使用新编号。调用中途撤销也拒绝保存或发布旧内容，但按实际返回用量结算费用；未知调用不自动重做。

忘记会清空目标／约束和来源绑定；保留修订墓碑及更新请求的单向摘要，以阻止旧修改／删除被重复执行。已付费与执行防重标记不删除。SQLite 使用现有 secure_delete；不承诺撤回模型、平台、系统备份或先前导出中的副本。

## 验证与边界

新增 11 项合成检查覆盖本机默认许可、仅选中领域入模、跨进程步骤恢复、来源根目录／提供商撤销、90 天复核、旧更新防重、删除与其他领域隔离、中途撤销结算，以及 CLI。使用实际 Pi 和模拟模型，不调用真实 MiMo，不写入真实领域目标。

目标首片的完整回归、独立包和部署结果见 [本人渠道续验](agent-channels.md)及[脱敏记录](validation/agent-domain-context-20261015.json)。相关历史检索已在[后续切片](agent-work-history.md)实现；总管分工和跨领域汇总、专业角色独立运行、远程领域编辑及自动长期记忆仍待实现。
