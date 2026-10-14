# PA1 首个本机切片

状态（2026-10-14）：已实现本机排序检索、按提供商授权的最小 Context Bundle、MiMo 适配器、日／月 Token 预留及引用校验。模拟检查及真实 MiMo 合成联调通过，用户指定使用 **`mimo-v2.6-flash`**。实际语义模型、PWA／飞书分析入口和 Agent 执行框架仍需分别验证，不能据此宣布完整 PA1 上线。

用户确认首次联调只使用合成资料，预算为每日 **100,000**、每月 **1,000,000 Token**。当前 Mac CLI 的本机配置为 `synthetic_only: true`、`enabled: true`、`model: mimo-v2.6-flash`，密钥由用户经隐藏输入存入系统凭据库。仓库默认仍关闭调用且不预填模型。Study／Life 没有自动添加模型许可。

## 本机接口

在仓库根目录使用 `scripts/asis pa1`，运行状态位于仓库外私密目录。基础切片仅需标准库；`pa1.json`、`pa1.sqlite3` 与真实来源配置均排除 Git。

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

合成限制继续生效，开启 `enabled` 不开放真实来源。自检会核对内置合成文件的内容哈希和固定合成问题，不能仅靠把任意目录叫作“synthetic”通过检查。密钥不存在时在预留和网络调用前失败，不使用明文配置或环境变量回退；密钥不进入参数、聊天、日志或预算库。

## 来源模型权限

`sources.yaml` 新增两个默认空字段，必须在本机单独配置：

| 字段 | 执行含义 |
|---|---|
| `model_providers` | 明确许可的提供商标识；当前适配器为 `mimo` |
| `model_paths` | 逐文件精确相对路径，不解释目录或 glob，也不自动许可新增／移动文件 |

模型许可不继承 `remote_metadata`、`private_remote_metadata` 或 `remote_evidence`。private 来源不能启用云模型，frontmatter／路径私密规则仍优先。没有当前、明确允许的证据时不调用模型。

上下文最多选择 3 个当前内容版本，每个只取最多 600 字符摘录及截断标题。摘录优先正文、跳过 frontmatter，保留准确行列位置，避免标题命中掩盖实际内容。云端只收到问题、`E1` 等临时引用编号、标题和片段；绝对根目录、原文 URI、路径提示与本机身份／版本映射保留本机。调用前和结果返回前重新检查原文哈希、许可及摘录内容，拒绝过期、撤权或被替换的内容。

## 检索及降级

当前默认使用 SQLite FTS5 与本机词项／汉字二元特征相似度排序，通过 reciprocal rank fusion 合并排名；这是词法模式，不声称已有实际语义模型。相同内容版本在上下文中去重。

可选 `semantic_model_dir` 指向已在本机准备好的 Sentence Transformers 模型目录。适配器仅离线加载，不在检索期间下载权重，不允许 remote code；余弦相似度与全文排名合并。缺少目录／依赖时明确返回降级原因并保留词法检索。真实权重、性能及中文／英文语义质量未测，模拟编码器只验证融合与语义分支协议。接口依据 [SentenceTransformer 官方参数](https://sbert.net/docs/package_reference/sentence_transformer/SentenceTransformer.html)。

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

用户在首调后指定 Flash，当前及后续配置使用 Flash。本轮累计 **482 Token**、未知调用 **0**；日剩余 99,518、月剩余 999,518，仅为验收时快照。未向云模型发送私密／未授权 canary、真实资料或路径，VPS 未接收模型密钥或上下文。当前入口为仓库 Mac CLI，PA0 的既有生产 daemon 和 VPS 未增加分析入口。

后续仍需实际本机语义模型与向量缓存、授权真实材料的证据质量检查，以及 PWA／飞书分析入口；Pi／领域角色／持续委托另按 [运行框架计划](agent-runtime-validation.md)验证。本次不扩大真实资料、私密正文或其他提供商授权。
