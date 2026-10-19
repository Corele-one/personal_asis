# Retrieval Quality：离线重排与版本绑定评测

2026-10-19后续当前发布为 `retrieval-context-3fa59e109dd0af73`：[质量续作](retrieval-context-quality.md)已修复原探针的时间误筛与弱词项误报，并完成两条真实摘录生成；完整生产替换Gate仍未通过。下文保留首轮模型比较、失败和部署的历史范围，不覆盖[最新记录](validation/retrieval-context-20261019.json)。

2026-10-19，按[实施计划](implementation-plan.md#下一实施切片)交付 P2 的独立质量实验。普通 PA0／PA1／Pi、已有飞书只读入口和历史付费工作的序列化保持原协议；本页能力仅显式本机使用。没有新增云提供商、来源／渠道披露、后台工作或 Token 上限。

当前Mac／VPS已发布 `retrieval-quality-e6d8bd41f7ea44a3`。Mac checkout／独立包515项＝496通过＋19跳过；VPS核心515项＝348通过＋167跳过，实际SDK／加密／DeepSeek专项31项通过。模型权重只存Mac仓库外，VPS没有取得模型或个人qrels。首次发布因bootstrap后进程未启动而回滚，显式kickstart并等待running后重发；原解释器、配置及模型账本不变。回滚目录标识为`retrieval-quality-e6d8bd41f7ea44a3-retry1`，Mac恢复原plist，VPS恢复其中`previous-code`指向并重启原服务；不回滚索引／工作／预算库。

## 运行恢复

本轮初查 VPS 协调、PWA、AstrBot、nginx 为 active，Mac PA0／PA1运行，但 SSH 隧道 stopped／退出255。重启既有隧道后，回环转发收到 VPS HTTP响应；生产加密只读 Study 检索返回11段，0模型调用，模型账本逐项摘要未变化，未发飞书消息。

Life 曾被索引标为 unavailable。首轮逐文件检查有一个读取错误，第二轮未复现；随后真实核对 Study 267／Life187、外部24／9／8，合计495个活动条目，Study／Life为ready。不能仅凭恢复推断具体根因，也不把本次人工恢复当无人值守休眠／重启验收。知乎与公众号条目0，未请求平台。

## 显式重排协议

`retrieval_v2.search` 和 `build_bundle_v2` 新增可选 `reranker`、`min_score`、`max_rerank_candidates`。未传重排器时仍返回 `retrieval-v2.1`，旧 Bundle 指纹和模型输入字段不变；显式重排返回 `retrieval-v2.2`。没有将该协议注册到普通 Agent 或旧 `agent-web-v1/v2/v3` 工作。

宿主先执行当前来源、根目录、版本、模型、渠道、日期和完整性过滤，再对最多40个去重候选评分；调用方可显式设置1–100。未评分候选不会绕过门槛补足结果。完整原始查询在标题／片段的精确命中保留为优先发现锚点，单独记录`exact_original`，防止分类器错删标题／批注；它也不是答案充分性证明。其他候选必须达到显式门槛。原始 logit 只表示特定模型的相关性；`answer_sufficiency_verified=false`，不能解释为事实概率、已回答全部子问题或冲突已解决。失败／非有限分数拒绝本次实验，不回落到未重排候选。

只有相关候选进入最终字节预算；新路径按重排顺序选择段落，防止作品多样性启发式把低相关段挤到前面。最终 JSON 的协议／质量字段也计入预算。Bundle 指纹绑定协议、模型文件及依赖指纹、门槛和候选上限；导出仍重新检查来源、位置和权限。

`LocalCrossEncoder` 只接受已存在的绝对本机目录、标准 Bert/XLM-RoBERTa 单分数分类器和 Safetensors，拒绝自定义 `auto_map`、链接模型与远程代码；加载使用 `local_files_only=True`、`trust_remote_code=False`、`token=False`。CPU批量8，问题最多128 token、输入对最多512 token，必要时只截断候选尾部。评分不下载、不发请求，既有 `semantic` 可选依赖足够，不需要FlagEmbedding。

显式试验：

```sh
ASIS_RUNTIME="$HOME/Library/Application Support/PersonalAsis"
ASIS_PYTHON="$ASIS_RUNTIME/pa1-env/bin/python"
RERANKER_DIR="$ASIS_RUNTIME/models/bge-reranker-v2-m3/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
ASIS_PYTHON="$ASIS_PYTHON" scripts/asis retrieval-v2 search --source study --provider mimo \
  --query '缓存一致性' --mode lexical --reranker-dir "$RERANKER_DIR" \
  --rerank-min-score -4.5 --rerank-candidates 40 --diagnostics-only
```

`RERANKER_DIR` 须指向已准备的本机模型。-4.5仅对应本文固定版本的合成评测，不是所有模型／问题均通过的推荐值，真实探针仍有误报。诊断输出仅有协议、计数、固定状态及模型指纹；非诊断输出含真实候选，只留私密终端。没有修改 `pa1.json` 或默认模型。

## 可复查的质量比较

冻结39题的正文、问题及指纹保持不变；另冻结13道保留题，查询与39题不重合，仍使用同一合成语料。粗网格预先固定为 `-6/-4/-2/0/2`，两个候选都未通过。随后只核对冻结题：BGE误报的最高分为-5.412069，原正确改写目标为-4.395195，存在粗网格遗漏的区间。因此另固定 `-5.75/-5.5/-5.25/-5/-4.75/-4.5/-4.25` 细网格，只在39题上选择通过门槛的最高值-4.5，再验证13题。保留题没有用于调门槛；此前粗网格的失败结果也保留，不把同语料新问法当独立真实语料泛化保证。

最终BGE＋E5 hybrid在39题Recall@5维持1.000，负例0/3→3/3，返回段Precision（非空题宏平均）0.2359→0.8194；固定5槽Precision仍为0.2000。保留题Recall维持1.000，负例2/6→6/6，返回段Precision0.1455→0.8929。两组检索Gate通过、越权0。V2 lexical＋同门槛仍有两道无词项重合改写缺口；小模型mMARCO在所有粗网格点均有回退，不选为通过方案。完整失败／网格见[比较](validation/retrieval-quality-comparison-20261019.json)、[39题](validation/retrieval-quality-frozen-20261019.json)及[13题](validation/retrieval-quality-holdout-20261019.json)。这不是完整生产替换Gate通过。

比较保留旧 E5 hybrid、V2 lexical、V2 hybrid及可插拔本机重排。报告精确记录模型固定版本／文件哈希、依赖指纹、参数、socket阻断守卫、真实CPU评分和合成分数内存复用；不同冷热条件的耗时分开解释，不把缓存重放时延冒充首次推理。

`retrieval_eval.retrieval_gate` 检查同数据／K、Recall无退步、固定K的Precision无退步、所有负例为空和越权为0。该函数只计算检索门槛；即使通过也不会置生产替换为true。答案忠实性／相关性、新Agent完整提示和费用、真实领域任务及本人UI仍分别验收。

首个候选 [mMARCO MiniLMv2](https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1) 在中文改写、批注和多文档部分证据上暴露缺口，不能以部分排序改善自动上线；第二候选 [BGE reranker v2 m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) 按同样标准比较。两者官方模型卡均标Apache-2.0，固定版本下载仅包含配置、tokenizer和Safetensors，没有下载Python模型代码或调用托管推理。[Transformers用法](https://huggingface.co/BAAI/bge-reranker-v2-m3#using-huggingface-transformers)与[本机加载参数](https://sbert.net/docs/package_reference/cross_encoder/model.html)用于核对实现边界，模型卡宣传不作为本项目质量结论。

可独立复测，每次都需显式门槛：

```sh
PYTHONPATH=src "$ASIS_PYTHON" -m personal_asis.retrieval_eval \
  --version v2 --mode hybrid --semantic-home "$ASIS_RUNTIME" \
  --reranker-dir "$RERANKER_DIR" --min-score -4.5 --suite frozen --output /tmp/asis-quality.json
PYTHONPATH=src "$ASIS_PYTHON" -m personal_asis.retrieval_eval \
  --version v2 --mode hybrid --semantic-home "$ASIS_RUNTIME" \
  --reranker-dir "$RERANKER_DIR" --min-score -4.5 --suite holdout --output /tmp/asis-quality-holdout.json
```

## 真实语料的私密评测

`retrieval_private_eval` 接收仅存本机的 `retrieval-private-qrels-v1` JSON。每题显式来源，数据集绑定来源根目录身份；目标绑定document UUID、content hash、原文字符范围。来源撤权、根目录变化、版本变化、日期越界或目标不存在，评测立即拒绝，不能用旧gold继续宣称通过。

CLI要求输入文件0600、输入／输出位于checkout外、拒绝符号链接，输出0600；整个模型加载及评测阶段阻断socket连接。成功和失败输出均不回显问题、标题、路径、正文或文档身份，只留匿名序号、计数、指标和数据集整体指纹。真实qrels及逐题来源不得入Git。

```sh
PYTHONPATH=src "$ASIS_PYTHON" -m personal_asis.retrieval_private_eval \
  --home "$ASIS_RUNTIME" --dataset "$ASIS_RUNTIME/retrieval-quality-validation/qrels.json" \
  --output "$ASIS_RUNTIME/retrieval-quality-validation/report.json" --mode lexical
```

首轮使用12篇获准真实笔记（Study8／Life4）的已知片段探针及4道无支持问题，共16题，`design=known_span_smoke`、`manual_relevance_judgment=false`。它验证片段可找回、权限／版本绑定及当前规模，不代表人为完整标注、自然问题综合质量或答案评测。报告中的Precision仅相对所标最小目标，不把其他未标相关片段自动判成错误结论。未来人工领域评测可用 `design=human_qrels`；本轮未伪造人工标注。

同一数据集下，词法基线与两个模型均为11/12目标命中（Recall0.9167），一个目标仍未进入前5。基线4道负例均返回候选；mMARCO和BGE在0门槛均为4/4空结果。BGE在冻结集选定-4.5后只有3/4空结果，说明合成门槛不能直接推广真实语料，**真实探针Gate未通过，完整生产替换仍不允许**。相关匿名指标见[私密探针摘要](validation/retrieval-quality-private-probes-20261019.json)。本轮不通过改写探针或再调门槛掩盖该结果。

## 发布边界与后续

质量结果、回归及发布状态以[本轮记录](validation/retrieval-quality-20261019.json)为准。本机模型文件留在仓库外；模型不是新的云处理／渠道授权。回退时恢复原代码／plist，保留索引、工作和预算；停用新CLI参数即可继续旧检索，不删除原资料或重做付费工作。

完整生产替换前仍须真实领域问答、证据不足／冲突、完整提示预算和显式新Agent会话的端到端验收。后台委托、角色自主检索、自动记忆和PA2–PA5不因本页交付而启用。
