# 检索质量续作：时间、词法支持和逐字回答

2026-10-19，按[实施计划](implementation-plan.md#下一实施切片)继续补质量门槛。Mac PA0／PA1与VPS已发布 `retrieval-context-3fa59e109dd0af73`；普通检索、角色、历史付费协议、提供商与预算保持原值。新能力仅显式本机调用。前一轮[质量实验](retrieval-quality.md)及其失败指标保留，当前依据见[验收记录](validation/retrieval-context-20261019.json)。

## 修复与协议

真实已知片段探针的一个漏检来自相对时间推断：原文中的相对时间词被当作近期筛选，目标在排序之前已被排除。新增 `infer_time_window=False`／CLI `--literal-time`，只使用调用方显式给出的时间窗口。默认仍沿用旧推断规则；这不是取消日常请求的时间约束。

另一个负例仅与候选重合一个常见中文二元词项，BGE仍给出高于-4.5的分数。新增显式 `quality_profile='strict-lexical-v1'`：有效路径为lexical且查询有至少6个不同中文二元词项时，要求至少两个重合项，或有匹配的英文标识符；完整查询精确命中仍保留。短查询不增加此条件，semantic／有效hybrid不强制词项重合，hybrid降级为lexical时才应用。该规则是有限启发式，不能证明答案充分或所有误报已解决。

任一新增选项启用时使用 `retrieval-v2.3`，策略和时间推断开关绑定Bundle指纹并计入最终上下文字节。未启用时维持原 `v2.1/v2.2`。重排模型仍是原Mac本机BGE固定版本和-4.5门槛，候选上限40；本轮没有重新调门槛、下载模型或切换普通Agent工具。

```sh
ASIS_RUNTIME="$HOME/Library/Application Support/PersonalAsis"
ASIS_PYTHON="$ASIS_RUNTIME/pa1-env/bin/python"
RERANKER_DIR="$ASIS_RUNTIME/models/bge-reranker-v2-m3/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
ASIS_PYTHON="$ASIS_PYTHON" scripts/asis retrieval-v2 search --source study --provider mimo \
  --query '缓存一致性' --mode lexical --reranker-dir "$RERANKER_DIR" \
  --rerank-min-score -4.5 --quality-profile strict-lexical-v1 --literal-time --diagnostics-only
```

## 同数据比较

原16题gold的来源、版本和目标范围均未修改。只显式关闭相对时间推断后，12/12目标找回，负例仍为3/4；再加入词法支持规则后，12/12找回且4/4负例为空。因此漏检修复来自日期解释，误报修复来自词法支持，不能统称为排序器提升。

另增加7条依据现有最小Study片段编写的自然问句，复用原4条负例，共11题。原BGE路径为7/7找回、3/4负例为空，新路径为7/7、4/4。`design=assistant_authored_natural`、`manual_relevance_judgment=false`；它们不是用户标注，也不是独立语料泛化证明。真实问题、qrels和来源身份仅存仓库外私密目录。匿名指标见[私密比较](validation/retrieval-context-private-20261019.json)。

冻结39题和13道保留题指纹保持不变；固定-4.5重跑lexical／hybrid共四组，与各自相同模式基线比较均无召回／固定K精度回退，负例与权限检查通过。hybrid两组Recall均为1.000；lexical仍有无词项重合的改写缺口，Recall分别为0.9444／0.8571。模式内无退步不等于词法召回满分。见[完整合成比较](validation/retrieval-context-synthetic-20261019.json)。

私密评测报告升级为 `retrieval-private-eval-v2`，默认 `--temporal-policy explicit`，另可选 `legacy_auto` 复现旧日期行为；显式记录时间策略与质量规则，避免与旧报告无说明比较。直接检索API的默认日期行为没有变化。

## 一次生成的摘录实验

新增本机 `quality-answer inspect|analyze`，使用独立 `quality-answer-v1`，未接入飞书、PWA、角色或后台。宿主只允许模型返回最多两条逐字摘录、每条最多120字，引用必须属于本次证据且是连续子串。最终答案由宿主拼接，不接受模型自由改写的事实与不确定性文本。缺信息状态必须没有摘录；冲突状态必须有两条不同摘录，并提示仍需核对。逐字检查不是相关性、蕴含或冲突语义证明，这些字段保持未验证。

`inspect`不读模型凭据、不生成，只报告计数与完整messages字节。`analyze`需显式 `--live --request-id`，沿用原MiMo、512 completion上限和共享日／月预算。模型仅接收问题与摘录归属／完整性／日期；排序诊断留在本机。实际完整messages不得超过8192字节，也不得超过同问题、同来源的原PA1 lexical提示大小；必要时减少尾部候选，连一段也放不下则停止，不能放宽预算。这个约束是提示大小比较，不冒充已完成旧模型回答的实际费用对照。

```sh
ASIS_PYTHON="$ASIS_PYTHON" scripts/asis quality-answer inspect --source study \
  --query '缓存一致性' --reranker-dir "$RERANKER_DIR" --min-score -4.5
# 一次真实生成会计入原预算；正文只输出到本人私密终端。
ASIS_PYTHON="$ASIS_PYTHON" scripts/asis quality-answer analyze --source study \
  --query '缓存一致性' --reranker-dir "$RERANKER_DIR" --min-score -4.5 \
  --live --request-id 'my-distinct-quality-question-001'
```

请求身份绑定问题、来源、当前版本证据、策略和完整载荷。成功重复请求免费读取原结果；输入改变不能复用同一付费编号。未知结果保留预留、无效摘录按实际用量记账，均不自动重做。发送前和返回前重新检查许可；撤权／到期清理结果，保留计费和防重标记。原付费会话不迁移到该协议。

真实Study两条回答均返回相关逐字摘录，合计709 Token；完整提示分别1209／1179字节，低于原lexical的1328／1301字节。一次相同编号复用在网络阻断下成功，没有新调用。另两条缺信息问题分别因无合格候选、无法在原lexical成本基线内容纳一段而在付费前停止，账本没有新调用；它们不是模型正确拒答的验收成功。真实缺信息生成与冲突语义尚未通过；合成测试覆盖其结构、逐字引用和计费约束。见[回答记录](validation/retrieval-context-answers-20261019.json)。

自动审批曾因私有Study载荷拒绝真实模型验证；核对[持续授权Q1/Q2](private-data-authority.md)和现行本机MiMo许可后，同一动作重新审核获准。没有新增许可、目的地或预算，也没有绕过审核。

## 发布、回退与下一门槛

Mac工作区／独立包532项＝513通过＋19跳过；VPS核心532项＝365通过＋167跳过，实际SDK／加密／DeepSeek专项31项通过。首次受限沙箱运行的16项套接字错误保留；原生产解释器中的完整重跑通过。新加17项回归验证日期、弱词项、无词项语义候选、费用、未知防重、撤权与清理。

原解释器、来源／模型／渠道配置与前一发布保留；Mac／VPS回退标识均为 `retrieval-context-3fa59e109dd0af73`。Mac恢复其中原plist后bootstrap并显式kickstart、等待running；VPS恢复 `previous-code` 指向并重启原服务。回退不恢复或删除索引、工作及预算库。模型与真实qrels不打包到VPS。

完整生产替换Gate仍未通过。下一步应先解决缺信息问题在原成本约束内的回答行为，并补真实冲突、独立人工自然问题评判；再做显式新Agent会话／恢复与完整提示费用验收。获准全库超过10000 chunks时的语义候选／缓存扩展仍待实现，不能取消预算上限来掩盖降级。用户负责飞书UI验收，本轮没有发送测试消息；角色自主检索、后台持续委托和PA2–PA5继续等待各自门槛。
