# PA1 本机检索与模型分析

状态（2026-10-14）：已实现 FTS5＋实际离线语义检索、分段向量缓存、独立来源模型政策、最小 Context Bundle、MiMo 适配器、日／月 Token 预留及引用校验。用户指定 **`mimo-v2.6-flash`**，并明确授权当前 Study／Life 的全部文件，包括日记与健康资料。PWA／飞书分析入口、外部研究适配器和 Agent 框架仍未交付，不能据此宣布完整 PA1 上线。

首次联调仅用合成资料。随后用户明确授权真实及私密材料分析，当前 Mac CLI 为 `synthetic_only: false`、`enabled: true`、`model: mimo-v2.6-flash`；共享预算仍为每日 **100,000**、每月 **1,000,000 Token**。密钥存系统凭据库，仓库默认关闭模型调用。当前独立政策按根目录持续许可 Study／Life，包含新增、修改和移动文件；本次核对 Study 267、Life 181，共 **448** 个 Markdown。新增根目录或提供商确认一次，凭据和显式排除项优先，详见[持续授权](private-data-authority.md)。

## 本机接口

在仓库根目录使用 `scripts/asis pa1`，运行状态位于仓库外私密目录。基础切片仅需标准库；`pa1.json`、`pa1.sqlite3` 与真实来源配置均排除 Git。

已安装的语义环境可直接使用：

```sh
scripts/asis-pa1 retrieve --source study --query "共享内存副本如何保持一致"
scripts/asis-pa1 bundle --source life --query "作息记录"
scripts/asis-pa1 analyze --source life --query "概括相关记录的自述与缺失信息，不作诊断" --request-id UNIQUE_REQUEST_ID
scripts/asis-pa1 budget
scripts/asis-pa1 semantic-test
```

`scripts/asis-pa1` 使用仓库外独立 `pa1-env`，并关闭 Hugging Face 在线访问与遥测；MiMo 调用仍按已配置端点执行。PA0 保持原生产代码与解释器。结果与上下文只显示在本机 CLI；实测完整结果保存在本机私密 `pa1-validation/`，不进入 Git 或远端。

```sh
scripts/asis pa1 init
scripts/asis pa1 self-test
scripts/asis pa1 budget
scripts/asis pa1 retrieve --query "关键词"
```

自检创建并自动清理隔离合成来源，包含允许材料、私密 canary 和未授权 canary；不读取 Study／Life 正文，不调用模型。普通本机检索仍可按原本机读取范围使用，不能将本机返回的摘录直接视为云模型许可。

真实联调准备：

```sh
# 本机交互终端隐藏输入，密钥只存系统凭据库
scripts/asis pa1 key
# 读取当前账户可用模型；官方页面枚举／示例可能不同，以账户结果为准
scripts/asis pa1 models
scripts/asis pa1 configure --model mimo-v2.6-flash --enable
# 调用方保留此请求编号；结果未知时不得换编号自动重发
scripts/asis pa1 self-test --live --request-id UNIQUE_REQUEST_ID
```

新安装的合成限制继续生效，开启 `enabled` 不开放真实来源；本机另经 `configure --allow-real-sources` 解除限制，逐来源许可仍检查。自检核对内置合成文件哈希和固定问题，不能把任意目录叫作“synthetic”通过检查。密钥不存在时在预留和网络调用前失败，不使用明文配置或环境变量回退；密钥不进入参数、聊天、日志或预算库。

## 来源模型权限

当前 CLI 将模型政策写入本机独立 `pa1-policy.json`，绑定来源 ID 和根目录身份，避免旧 PA0 运行代码读取新模型字段而失败。底层字段也兼容合成样例中的 `sources.yaml`；独立政策存在时由它管理模型许可，来源读取／分类／排除规则仍来自原配置：

| 字段 | 执行含义 |
|---|---|
| `model_providers` | 明确许可的提供商标识；当前适配器为 `mimo` |
| `model_paths` | 逐文件精确相对路径，不解释目录或 glob，也不自动许可新增／移动文件 |
| `private_model_providers` | 私密资料的独立提供商许可，必须同时具有普通提供商许可 |
| `model_all_files` | 源级全文件许可，新安装默认关闭；当前 Study／Life 已按确认范围启用，包含根目录内后续新增路径 |

模型许可不继承 `remote_metadata`、`private_remote_metadata` 或 `remote_evidence`。private 来源、frontmatter 和路径私密分类保持有效，另有 `private_model_providers` 才可使用。用户本轮授权已明确包含日记与健康资料，见 [ADR 0032](adr/0032-allow-private-model-context-with-explicit-provider-grants.md)。包含私密证据的派生回答仍标为 private；本人飞书私聊／已启用工作通知和私有 PWA 展示另获持续授权，能力需逐项实现。没有当前、明确允许的证据时不调用模型。

```sh
# 仅在用户已明确授权这些已有来源及私密处理时执行
scripts/asis-pa1 authorize --source study --source life --all-source-files --include-private
# 立即撤回一个来源；缓存不构成许可
scripts/asis-pa1 revoke --source life
# 暂停所有真实来源模型分析，仍可本机检索
scripts/asis-pa1 configure --synthetic-only
```

早期授权仅包含现有路径，自动审批曾拒绝把它推断为未来文件许可；后来用户通过 Q1–Q11 访谈及整体确认，明确选择源级持续授权，现已启用。早期新字段写入 PA0 配置的兼容问题已通过独立 PA1 政策解决；本轮生产更新、重启和回滚准备按新维护许可执行，见[应用记录](private-data-authority.md)。

上下文最多选择 3 个当前内容版本，每个只取最多 600 字符摘录及截断标题。摘录优先正文、跳过 frontmatter，保留准确行列位置，避免标题命中掩盖实际内容。云端只收到问题、`E1` 等临时引用编号、标题和片段；绝对根目录、原文 URI、路径提示与本机身份／版本映射保留本机。调用前和结果返回前重新检查原文哈希、许可及摘录内容，拒绝过期、撤权或被替换的内容。

## 检索及降级

未配置语义模型时使用 SQLite FTS5 与本机词项／汉字二元特征相似度排序，通过 reciprocal rank fusion 合并排名。当前已配置实际语义模型，融合全文与语义排名；相同内容版本去重，指定 `--source` 时仅检索对应来源。

实际模型为 `intfloat/multilingual-e5-small`，固定版本 `614241f622f53c4eeff9890bdc4f31cfecc418b3`，仅加载 safetensors 和标准 Sentence Transformers 模块，CPU 本机运行。依照 [官方模型说明](https://huggingface.co/intfloat/multilingual-e5-small/blob/614241f622f53c4eeff9890bdc4f31cfecc418b3/README.md)，查询加 `query: `、正文加 `passage: `，384 维、最多 512 Token；按正文段落拆分为最多 400 字符、重叠 80 字符的窗口，跳过 frontmatter 和独立标题，覆盖长文尾部。窗口仍可能被分词器截断，不承诺所有语言或极端符号组合都完整编码。

`semantic.sqlite3` 仅存来源文档身份、内容哈希、模型指纹和向量，不存原文、标题、路径或问题；按本机／提供商与来源筛选范围隔离。当前内容和许可先于缓存检查；修改、删除、撤权、禁用来源或模型变化后清理对应作用域的旧向量。其他未访问作用域可能仍有旧向量，但不能绕过当前许可用于检索。损坏缓存或推理失败会明确降级到词法检索，不影响预算和模型许可。关闭语义设置不会自动删除文件，可手工删除私密缓存后重建。

重建环境与显式下载公开权重：

```sh
python3 -m venv "$HOME/Library/Application Support/PersonalAsis/pa1-env"
"$HOME/Library/Application Support/PersonalAsis/pa1-env/bin/python" -m pip install -r requirements/pa1-semantic.txt
"$HOME/Library/Application Support/PersonalAsis/pa1-env/bin/python" scripts/pa1-fetch-semantic --target "$HOME/Library/Application Support/PersonalAsis/models/multilingual-e5-small"
scripts/asis-pa1 configure --semantic-model-dir "$HOME/Library/Application Support/PersonalAsis/models/multilingual-e5-small" --semantic-query-prefix 'query: ' --semantic-document-prefix 'passage: '
```

缺少目录／依赖或推理故障时返回降级原因；检索期间不下载权重、不运行远程代码。接口依据 [SentenceTransformer 官方参数](https://sbert.net/docs/package_reference/sentence_transformer/SentenceTransformer.html)。

## 预算与失败

本机独立 SQLite 以事务预留 Token，并发请求不能同时抢占同一剩余额度。按 Asia/Shanghai 的调用启动日／月计账；接近 80% 显示提示，额度不足时阻止模型调用，不影响本机检索。预留包括输入 JSON 字节数、保守的模板余量和最大输出 Token；成功后按服务端用量结算，本轮真实调用均在预留内，但两次小样本不能证明所有输入的估算覆盖；返回用量超出预留时按已知用量记账并拒绝结果。

未知网络结果、缺失／损坏的用量或进程中断保留预留额度；不释放为“免费失败”，同一请求编号不能自动重试。明确 401／403 认证拒绝结算为零；非法引用／截断答案按实际已知用量结算并拒绝显示结果。请求编号绑定问题、证据版本、模型及参数，成功的同一请求复用本机结果，不重复调用。

合成自检每次创建并清理临时来源，文档身份随之变化；重新执行相同编号会拒绝身份冲突，而不是再次付费调用。其临时原文 URI 在清理后不可打开，合成文本可由内置 fixture 重建；常规证据定位仍要求原来源在线。未知调用不能通过另取新编号绕过核对。

这里只做 Token 限额，不等同于人民币账单上限。输出上限同时覆盖可见内容和推理 Token，当前请求关闭 thinking、stream 及工具。引用校验保证编号存在且与正文引用一致，不能证明模型对证据的理解一定正确；用户仍可回到本机原文核对。

## MiMo 接口依据

2026-10-14 核查官方新版 [Chat Completions 文档](https://mimo.mi.com/docs/en-US/api/chat/openai-api) 与 [JSON 输出说明](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/text-generation/structured-output)：使用 `https://api.xiaomimimo.com/v1/chat/completions`、`api-key`、`max_completion_tokens`、`response_format: json_object`，读取服务端 `usage`。旧 `platform.xiaomimimo.com/static/docs/` 地址返回 404，未用旧搜索摘要确定模型可用性；模型名保持部署配置。

HTTPS 使用系统证书校验；不跟随重定向、不使用环境 HTTP 代理、不自动重试。该切片只在 Mac 本机执行，VPS 不接收上下文或模型密钥，AstrBot 原模型流程不承载 PA1。

## 验证与剩余工作

新增检查覆盖权限独立、逐文件许可、私密拒绝、正文摘录、上下文篡改／撤权／版本、模拟语义排名、并发及跨日／月预算、成功防重、未知结果保留额度、认证拒绝、非法引用和 API 用量校验。新增 20 项均通过；使用 Mac 生产 Python 完整回归共 119 项，113 项通过、6 项因可选 AstrBot SDK／格式依赖或 Linux 工具环境跳过。HTTP 测试使用本机 loopback 临时端口与合成数据；首次受沙盒端口限制，在允许绑定端口的环境重跑通过。

2026-10-14 从账户 `/models` 核实 Flash 可用，真实联调仅发送内置两篇合成资料，输出上限 512，thinking 关闭。记录如下；预算库保留两次用量，不因换模型清零：

| 请求 | 模型 | 输入／输出／合计 Token | 结果 |
|---|---|---|---|
| `pa1-synthetic-20261014-first` | `mimo-v2.6-pro` | 159／83／242 | 引用／结构校验通过；发现首条摘录只含标题，随后修正 |
| `pa1-synthetic-20261014-flash` | `mimo-v2.6-flash` | 169／71／240 | 两条正文均被正确引用，服务端 reasoning Token 为 0 |

用户在首调后指定 Flash，当前及后续配置使用 Flash。首次合成联调累计 **482 Token**、未知调用 **0**；当时日剩余 99,518、月剩余 999,518，仅为初次验收快照。当时未向云模型发送私密／未授权 canary、真实资料或路径，VPS 未接收模型密钥或上下文。当前入口为仓库 Mac CLI，PA0 的既有生产 daemon 和 VPS 未增加分析入口。

### 实际语义模型与真实材料续验（2026-10-14）

独立环境实际版本为 Python 3.14、Sentence Transformers 5.7.0、Transformers 4.57.6、PyTorch 2.14.1（完整直接依赖见 [固定版本](../requirements/pa1-semantic.txt)）。对模型加载和合成检索拦截 `socket.connect`，确认不联网；[可复查结果](validation/pa1-semantic-20261014.json)包含中英文转述、双向跨语言查询、长文尾部、私密／未授权 canary 与热缓存。**Top-1 为 5/6，Top-3 为 6/6**；“中文南瓜浓汤→英文烹饪段落”仅排第三，不能声称语义质量完全通过或覆盖所有真实资料。修正段落分割后，长文尾部摘录可精确回到原文；合成冷检索约 0.4 秒、热检索约 0.02 秒（不含首次加载），这不是 448 篇真实语料的性能承诺。

本轮新增 21 项检查，包含缓存复用／失效／损坏、来源筛选、长文定位、独立私密模型许可、根目录变更、撤权、来源级可选范围、派生结果分类、引用组和证据不足拒答。完整应用回归 **140 项：134 通过、6 跳过**，最终许可入口及错误阶段诊断修改后另有 27 项 PA1 针对性检查通过。跳过项仍为可选 SDK／格式或 Linux 工具环境。文档链接、围栏与配置 JSON 检查通过。

用户明确授权后，仅从 Study／Life 分别选取当前相关的三条最小摘录，按本机来源筛选真实调用；以下不记录真实正文、标题、路径或个人分析内容：

| 请求 | 来源 | 总 Token | 结果 |
|---|---|---|---|
| `pa1-real-study-20261014T214722` | Study | 405 | 引用／结构通过，冷检索加模型约 96.6 秒 |
| `pa1-real-life-20261014T214859` | Life | 400 | 引用校验拒绝展示，实际用量正常结算 |
| `pa1-real-life-structured-20261014T215406` | Life | 511 | 格式校验拒绝展示，实际用量正常结算 |
| `pa1-real-life-citations-20261014T215619` | Life | 555 | 引用／结构通过，private 派生分类保留；热缓存加模型约 7.3 秒 |

Life 的失败暴露了更稳健的输出处理需求：协议明确逐个引用，校验也支持 `[E1, E2]` 等常规引用组，但编号集合必须准确对应；未知编号、缺引和不一致仍拒绝。模型可返回 `insufficient_evidence`，此时只显示程序生成的证据不足提示，绝不展示无引用的模型个人断言。最终 Life 结果的三个编号及正文引用一致；以禁止实际 API 调用的提供商桩重放同一真实请求，命中本机结果，没有重复付费。

最终预算快照：含初次合成调用与两次格式失败，日／月累计均为 **2,353 Token**；日剩余 **97,647**、月剩余 **997,647**，未知调用 **0**。完整成功结果及最后一次提供商响应只保留在本机私密 `pa1-validation/`。结构和引用检查不等于个人事实、医疗解释或模型理解的人工验收。

该轮验证时 PA0 仍使用原发布包与原 Python。该轮发现旧 SSH 隧道自 18:02 已断开；仅唤起既有隧道后，loopback 返回协调服务 404（证明已连通），隧道与节点进程均 running。该轮没有发布新生产代码、重启节点或修改 VPS。随后确认持续维护许可并完成的新发布另见[应用记录](private-data-authority.md)。

后续仍需更广的真实检索质量评估、PWA／飞书分析入口和外部研究适配器；Pi／领域角色／持续委托另按 [运行框架计划](agent-runtime-validation.md)验证。当前已明确许可源级持续读取／分析、本人私密展示与可纠正的自动记忆；这些权限可分别检查和撤销，长期记忆及渠道分析仍需实现。

### 持续授权应用

用户已确认源级持续授权与维护范围，详情以[当前政策和落地状态](private-data-authority.md)为准。本机配置 `model_all_files: true` 后仍执行根目录边界、来源排除、凭据内容和 `assistant_exclude: true` frontmatter 检查；命中已知凭据格式或显式排除标记的整篇资料暂不索引，也不进入模型。内置检测覆盖已知路径、私钥／Token 形态、明显凭据赋值及认证／Cookie 头，不承诺识别所有可能的秘密；用户可将凭据独立存放并维护显式排除项。普通健康／日记类别不会单独触发禁止。

```sh
# 清理已过期、删除或撤权的本机 PA1 缓存；保留必要计费／防重标记
scripts/asis-pa1 clean
```

PA1 成功回答在 30 天后不再复用，过期或撤权后的旧请求编号会拒绝再次付费执行。`clean` 检查全部向量作用域、缓存回答及 `pa1-validation/` 内关联原响应；模型撤权立即触发清理，本机节点每次索引核对后也清理。提供商或飞书历史副本、离线节点及备份不被声称为同时抹除；自动长期记忆和相应复核仍未交付。
