而且你现在**没启动资金反而是一件好事**：它会迫使你先验证“Personal Assistant 到底有没有真实价值”，而不是先花一万块买 Mac mini + NAS，最后发现自己只是搭了个很漂亮的 HomeLab。

看你现在这份设计，我会对它做一个很关键的调整：

> **短期不要试图统一你的文件，先统一“对文件的认识”。**

也就是说，MacBook、ROG、Obsidian 里的资料**暂时一个都不用搬**。你的 Personal Index 应该允许资料天然分散。

---

## 1. 你现在已经有足够的硬件了

我会把你现有设备直接定义成：

```text
                     iPhone
                       │
                      PWA
                       │
                       ▼
              ┌────────────────┐
              │   Google VPS   │
              │ Coordination   │
              │      Node      │
              │                │
              │ Task Queue     │
              │ Notifications  │
              │ Task State     │
              │ Derived Cache  │
              └───────┬────────┘
                      │
               outbound connection
                 │           │
          ┌──────▼─────┐ ┌──▼──────────┐
          │ MacBook Air│ │   ROG 16    │
          │ Local Node │ │ Local Node  │
          │            │ │             │
          │ Obsidian   │ │ WSL         │
          │ Documents  │ │ Projects    │
          │ Papers     │ │ Datasets    │
          │ SQLite     │ │ SQLite      │
          │ Index      │ │ Index       │
          └────────────┘ └─────────────┘
```

**这其实已经是一套完整架构了。**

NAS 和 Mac mini 只是未来：

```text
MacBook Local Node
          ↓
Mac mini Always-on Local Node
          ↓
NAS canonical storage
```

的升级而已。

所以我甚至建议你把现在定义里的：

> Local Node：运行在用户 Mac 上……

改成更一般的：

> **Local Node：运行在用户控制的可信终端上，持有该终端可访问的来源系统及其个人索引，并执行需要原始资料或本地权限的操作。一个用户可以拥有多个 Local Node。**

因为你的 ROG 明明也是一个很重要的 Source System 所在节点。

---

# 2. 一个非常重要的设计：不要做“中央 Personal Index”

你现在没有 NAS，所以很容易觉得：

> 那我的 index 怎么办？Mac 和 ROG 上资料不在一起。

答案是：

## **Federated Personal Index**

也就是：

```text
Mac Index
├─ Obsidian
├─ PDF
├─ coursework
└─ documents

ROG Index
├─ NPU
├─ WSL projects
├─ datasets metadata
└─ experiment logs
```

VPS 可以知道：

```text
doc_id: 8af21...
title: HVX Softmax Stage 1
node: macbook
source: obsidian
path_hint: Research/NPU/Softmax.md
status: available/offline
```

但**不需要拿到正文**。

于是你在 PWA 问：

> 我之前关于 SCNA 做过哪些实验？

流程可以是：

```text
PWA
 ↓
VPS
 ↓
发现需要查询 Mac + ROG
 ↓
Mac 在线 ──→ 搜索 Mac Index
ROG 在线 ──→ 搜索 ROG Index
 ↓
返回若干 candidate
 ↓
组装 Context Bundle
 ↓
LLM
 ↓
回答 + Evidence Links
```

如果 ROG 睡眠：

```text
ROG offline

→ task = waiting_external
→ VPS 告诉 PWA：

“ROG 节点当前离线。
 已搜索 MacBook 中的资料。
 ROG 上还有 17 个相关索引条目尚未读取。”
```

等你下一次打开 ROG：

```text
agent reconnect
→ 收取 pending task
→ 查询
→ 更新结果
```

这和你设计里的：

* Task State
* Derived Cache
* Coordination Node
* Local Node

其实天然匹配。

---

# 3. VPS 甚至不应该主动连你电脑

这一点我建议一开始就设计对。

不要：

```text
VPS
    SSH → MacBook
```

也不要让：

```text
MacBook:8000
```

暴露公网。

而是让 **Local Node 主动连接 VPS**：

```text
MacBook ───────► VPS
ROG     ───────► VPS
```

开始甚至连 WebSocket 都不用。

每隔几十秒：

```http
GET /api/node/macbook/jobs
```

有任务：

```json
{
  "task_id": "...",
  "action": "search",
  "query": "SCNA softmax"
}
```

本地执行以后：

```http
POST /api/tasks/xxx/result
```

就够了。

Mac 睡眠没有关系。

醒来继续 poll。

这实际上非常符合你所谓的 **Coordination Node**：

> 它调度工作，但没有能力直接读取你的电脑。

以后觉得 polling 不够优雅，再换 WebSocket。

---

# 4. Personal Index 第一版千万不要上向量数据库

这一点我非常建议你坚持你写的：

> **Text-Only Index**

第一版甚至不要 embedding。

直接：

**Python + SQLite FTS5。**

SQLite 官方的 FTS5 本来就是为了在大量文档中进行全文检索，可以直接建立全文索引。([SQLite][1])

例如本地数据库：

```text
personal-index.db
```

先只有：

```text
documents
──────────────────────────────────
doc_id
source_id
node_id
path
title
mtime
size
sha256
tags
sensitivity
index_version
```

再：

```text
document_text
──────────────────────────────────
doc_id
content
```

再建立：

```sql
CREATE VIRTUAL TABLE document_fts USING fts5(
    title,
    content,
    tags
);
```

已经足够用了。

### 第一版索引内容

只处理：

```text
.md
.txt
```

甚至 `.pdf` 都先别碰。

刚好从：

> Obsidian

开始。

因为这是**最干净、最结构化、最有价值**的数据。

---

# 5. 你应该先写一个 `sources.yaml`

这可能是整个项目第一份真正值得写的代码之外文件。

比如 Mac：

```yaml
node: macbook-air

sources:

  - id: obsidian-main
    type: obsidian
    root: /Users/xxx/Documents/Obsidian
    include:
      - "**/*.md"
    sensitivity: normal
    personal_model: propose

  - id: coursework
    type: filesystem
    root: /Users/xxx/Documents/Courses
    include:
      - "**/*.md"
    sensitivity: normal
    personal_model: deny

  - id: diary
    type: filesystem
    root: /Users/xxx/Documents/Diary
    sensitivity: private
    cloud_context: deny
    personal_model: deny
```

ROG：

```yaml
node: rog16

sources:

  - id: npu-project
    type: filesystem
    root: /home/xxx/npu
    include:
      - "**/*.md"
      - "**/*.txt"
      - "**/*.log"
    sensitivity: normal

  - id: csapp
    type: filesystem
    root: /home/xxx/csapp
    sensitivity: normal
```

这比把所有资料搬进：

```text
~/PersonalData/
```

重要得多。

因为你开始建立：

> **我拥有什么信息，以及这些信息允许如何被使用。**

而不是重新整理一遍硬盘。

---

# 6. Index Reconciliation 也不用做复杂

你术语表中这一点我非常喜欢：

> Avoid: 文件监听

第一阶段我也**完全不会做 filesystem watcher**。

直接每次：

```text
scan sources
      ↓
读取 path / size / mtime
      ↓
和 SQLite 比较
      ↓
没变化 → skip
mtime/size 变化 → hash
      ↓
hash变化 → reindex
```

例如：

```bash
pa index
```

手动运行。

之后：

```bash
pa reconcile
```

每小时/每天运行。

其实 Syncthing 自身也采用“文件系统通知 + 定期完整 scan”的组合，因为 watcher 有可能漏事件，因此仍推荐周期性扫描。([Syncthing Documentation][2])

你现在甚至没必要上 watcher。

---

# 7. 那 PWA 到底应该长什么样？

这里我会把你原先的想法进一步收紧。

**不要把主页做成 ChatGPT。**

主页应该是：

```text
┌───────────────────────────────┐
│ Personal Assistant            │
├───────────────────────────────┤
│ Ask / Explore...              │
│ [___________________________] │
├───────────────────────────────┤
│ Nodes                         │
│ ● MacBook Air      Online     │
│ ○ ROG 16           Offline    │
├───────────────────────────────┤
│ Tasks                         │
│ 3 Running                     │
│ 1 Waiting for ROG             │
│ 2 Waiting for confirmation    │
├───────────────────────────────┤
│ Pending Confirmations         │
│                               │
│ Add event:                    │
│ IC Design Homework            │
│ Sep 24 23:59                  │
│                               │
│ [Reject]       [Confirm]      │
└───────────────────────────────┘
```

再有四个 tab：

```text
Explore
Tasks
Inbox
Audit
```

我认为**这才是 PWA 相比 ChatGPT 真正值得存在的原因**。

ChatGPT 的 UI 核心是：

> conversation

你的 PWA 核心应该是：

> **state**

---

# 8. PWA 这个选择本身是对的

因为你现在并不需要开发：

```text
macOS app
Windows app
iOS app
```

PWA 已经能提供：

* 安装到设备
* Service Worker
* 离线 UI shell
* Push
* Notifications

Web Push 本身就是通过 Service Worker 工作；即使页面没打开，Service Worker 也可以在收到 push 时启动并展示通知。([MDN Web Docs][3])

所以：

> **Mobile Entry = PWA**

作为 v0/v1，我觉得非常合理。

以后你真用了一年，发现 PWA 在系统集成上开始限制你，再做 native app。

而不是反过来。

---

# 9. 最妙的是：第一版甚至不要 LLM

既然你说：

> 现在没启动资金

那我甚至不会让 **OpenAI API 成为系统依赖**。

第一阶段：

```text
query
 ↓
FTS5
 ↓
documents
 ↓
Evidence Links
```

比如：

> softmax exp approximation

输出：

```text
[1] HVX Softmax.md
    Research/NPU/HVX Softmax.md#SCNA

[2] Stage1 Report.md
    Research/NPU/Stage1 Report.md#Experiment

[3] exp-benchmark.log
    node: ROG16
```

单单做到这里，你就已经拥有：

**跨设备个人搜索引擎。**

这本身就很有价值。

LLM 暂时可以继续：

> ChatGPT。

比如 PWA 做一个：

```text
Copy Context Bundle
```

一按：

```text
## Context

### HVX Softmax
...

### Stage1 report
...

Evidence:
...
```

复制进 ChatGPT。

一点 API 钱都不用。

---

# 10. 等你确认真的好用，再把 LLM 塞进去

所以我会让整个系统具有这样的接口：

```text
                     ┌─ ChatGPT 手工
Context Bundle ──────┼─ OpenAI API
                     ├─ Gemini API
                     ├─ Claude API
                     └─ Local Model
```

而不是：

```text
Personal Assistant = GPT wrapper
```

这样以后模型换多少代，对你的系统基本没影响。

你的真正资产是：

```text
Sources
Indexes
Evidence
Rules
Tasks
Operation Records
Personal Model
```

模型只是：

```text
reason(context)
```

这一层。

---

# 11. 你现在的术语表需要“砍一刀”

它作为**最终设计文档**很好。

但作为 **MVP TODO List**，太大了。

我现在会直接冻结其中大约一半。

### v0 做

* Source System
* Personal Index
* Index Reconciliation
* Evidence Link
* Context Bundle
* Text-Only Index
* Task
* Task State
* Draft
* Confirmation
* External Write
* Operation Record
* Coordination Node
* Local Node
* Mobile Entry
* Control Console
* Sensitivity Policy

### 暂时不做

```text
Personal Model
Memory Ledger
Conversation Summary
Memory Review

External Evidence
Signal Source
Research Strategy
Freshness Policy
Direction Hypothesis

Rule Proposal
Reusable Rule

Email Adapter
Task Digest
Retention Policy
Evidence Snapshot
```

不是因为这些设计不好。

而是它们属于：

> **“一个真正开始被使用以后才知道应该怎么设计”的模块。**

尤其是 Personal Model 和 Reusable Rule。

如果你一开始就做，很容易变成自己脑补需求。

---

# 12. 我会给你定一个极其具体的 v0

甚至可以把它叫：

> **PA0 — Where is my stuff?**

只实现一个能力：

## 用户问：

> 我之前研究过什么 Softmax approximation？

系统完成：

```text
① VPS 创建 Task

② MacBook Local Node
   搜索 Obsidian

③ ROG Local Node
   搜索项目 README / log

④ 返回结果

⑤ VPS 汇总 metadata

⑥ PWA 显示：

   HVX Softmax.md
   Stage1 Report.md
   SCNA benchmark.log

⑦ 点击 Evidence Link

⑧ 打开对应原始文件位置
```

如果 **PA0 已经让你觉得“好用”**，

再做：

> PA1 — Context Bundle

然后：

> PA2 — Task Candidate

然后：

> PA3 — Calendar Confirmation

然后：

> PA4 — Memory

---

# 13. 你第一阶段真正应该实现的 repo，我甚至都可以帮你定下来

```text
personal-assistant/
│
├── coordinator/
│   ├── api/
│   ├── tasks/
│   ├── auth/
│   └── db/
│
├── local-agent/
│   ├── sources/
│   ├── index/
│   ├── search/
│   └── client/
│
├── web/
│   ├── pwa/
│   ├── tasks/
│   ├── explore/
│   └── audit/
│
├── shared/
│   ├── models/
│   └── protocol/
│
├── docs/
│   ├── glossary.md       ← 你刚才这一份
│   ├── architecture.md
│   └── threat-model.md
│
└── README.md
```

技术上第一版我会选得非常无聊：

```text
Local Agent:
Python

Local Index:
SQLite + FTS5

Coordinator:
FastAPI + SQLite

Frontend:
最简单的 React/Vite PWA
甚至 Vanilla TS 都可以

Transport:
HTTPS REST

Local Node connection:
polling

Deployment:
systemd @ Google VPS

Mac:
launchd

ROG/WSL:
systemd
```

**没有 Redis。**

**没有 PostgreSQL。**

**没有 Kafka。**

**没有 Elasticsearch。**

**没有 Qdrant。**

**没有 Kubernetes。**

**没有 LangChain。**

😂

因为这些东西现在全部是在给自己创造工作。

---

## 最终你会得到一条很漂亮的硬件演进路径

现在：

```text
        Google VPS
         Coordinator
           ▲    ▲
           │    │
       MacBook  ROG
```

未来有第一笔钱：

```text
        Google VPS
         Coordinator
             ▲
             │
          Mac mini
       Always-on Node
        ▲         ▲
    MacBook      ROG
```

以后资料真的很多：

```text
        Google VPS
         Coordinator
             ▲
             │
          Mac mini
        Compute Node
             │
             ▼
            NAS
        Source Storage
```

你现在写的任何核心代码都不用推翻。

**只是一个原本经常离线的 Local Node，被 Mac mini 替换成 always-on；原本散落的 Source System，逐渐被 NAS 接管。**

这就是我最喜欢你现在这个方向的地方：

> **没钱的时候，这套架构能跑。**
>
> **以后有钱了，它也不是废案。**

而且我觉得你现在最应该抵制的诱惑就是“先搭一个很厉害的 AI Agent”。你真正值得先做出来的东西非常朴素：

> **让任意一台设备上的资料，都第一次拥有稳定的 `doc_id`、可搜索的 Personal Index 和能回到原文的 Evidence Link。**

一旦这个底座成立，后面的 Memory、Task、Rule、Agent、LLM 都会开始有地方“落地”。这一步才是真正从“使用 ChatGPT”跨到“拥有自己的 Personal Computing Infrastructure”。

[1]: https://www.sqlite.org/fts5.html?utm_source=chatgpt.com "SQLite FTS5 Extension"
[2]: https://docs.syncthing.net/users/syncing?utm_source=chatgpt.com "Understanding Synchronization — Syncthing documentation"
[3]: https://developer.mozilla.org/en-US/docs/Web/API/Push_API?utm_source=chatgpt.com "Push API - Web APIs | MDN"
