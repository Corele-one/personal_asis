# Personal Assistant Specification

## 1. Purpose

This project is a personal work and development system. It helps the user locate their own material, connect it to an external question when requested, and turn reviewed work into auditable tasks and reusable rules. Its long-term scope includes health observations, sleep, diet, and future career choices, connected through a record–review–action–feedback loop.

The system's durable assets are source configurations, personal indexes, evidence links, task state, operation records, readable memory, and reusable rules. A model provider is replaceable reasoning infrastructure, not the authority for any of them. Domain workflows, proposed starting defaults, and acceptance scenarios are defined in [Personal development workflows](docs/personal-development.md); these extend product scope without changing PA0's delivery gate.

## 2. Goals and non-goals

### Goals

- Preserve existing source systems. The assistant indexes them and links back to originals; it does not migrate them into a central archive.
- Work across trusted devices that are frequently offline.
- Let the user start searches from a phone without exposing either laptop to the public internet.
- Make evidence, policy, state changes, confirmations, and external writes inspectable.
- Keep source text and full indexes on Local Nodes; make the VPS a low-sensitivity coordinator.
- Grow in independently verifiable stages.
- Support low-burden voluntary wellbeing records and evidence-linked reviews, without requiring devices, subscriptions, or months of data before the first useful review.
- For the current user, prioritize third-year undergraduate graduate-application choices, meal-photo capture, bedtime/wake check-ins, and authorized read-only journal reflection.
- Compare multiple career Direction Hypotheses against interests, demonstrated abilities, available time, wellbeing constraints, and user-defined resource limits; validate them through bounded Action Trials.
- Support optional Model Cross-Review and explicitly authorized Opportunity Subscriptions after the relevant policy and budget controls exist.

### Non-goals for PA0

- No LLM call, semantic vector index, file watcher, OCR, image understanding, email, calendar write, task candidate extraction, personal model, automatic memory, or reusable-rule execution.
- No source migration, NAS, central PostgreSQL, Redis, Elasticsearch, Qdrant, Kafka, Kubernetes, or a public service on either laptop.
- No QQ interface or AstrBot reasoning/task authority. Feishu is the only chat interface; the existing AstrBot-hosted Feishu transport may be reused by a scoped PA0 plugin (see [transport boundary](docs/pa0-feishu.md)).

## 3. System boundary

```text
Feishu bot ──┐
             ├── VPS Coordination Node ── outbound polling ── Mac Local Node
Private PWA ─┘
```

### Coordination Node (VPS)

The VPS provides task coordination, node status, a private HTTPS PWA, Feishu event handling, and a policy-authorized federated metadata catalog. It does not store source originals, complete indexes, full text, summaries, vectors, local credentials, or decryption keys.

### Local Nodes

The current PA0 deployment runs on Mac only, following the user's explicit scope change on 2026-10-14. ROG WSL remains an optional, disabled node. Each enabled node:

- reads only its local Source Configurations;
- owns its SQLite index and transactional state;
- initiates authenticated outbound polling to the VPS;
- executes assigned local searches and returns allowed metadata/evidence results;
- is allowed to sleep or be offline without being treated as failed forever.

The Mac runs as a user `launchd` service. ROG's WSL service is disabled and outside the current maintenance scope. Later explicitly enabled trusted devices may use the same protocol.

## 4. Data classification and storage

### Source data

Sources remain on their existing systems. PA0 indexes Markdown body, titles, links, tags and frontmatter, plus explicitly enabled PDF/Office text with page, paragraph, slide or cell locations. Images, audio and video are not decoded; OCR is excluded. See [text implementation](docs/pa0-text.md).

The initial test configuration is:

| Source | Policy |
|---|---|
| `Note/` | `normal`; eligible for future restricted derived cache and personal-model proposals |
| `Daily/` | `private`; no VPS cache, no cloud-model context, no personal-model use |

Wellbeing sources and derived material retain private classification. Under the user's confirmed [standing authorization](docs/private-data-authority.md) and [ADR 0033](docs/adr/0033-use-standing-personal-data-and-maintenance-authorizations.md), the current Study/Life roots and future files inside them may be indexed, retrieved and analyzed by approved providers, including diaries and health records. Credentials and explicit user exclusions take precedence; new roots or providers require one scoped confirmation. A private classification controls processing and disclosure rather than unconditionally disabling the assistant. Directory traversal and symlinks do not extend permission beyond a configured root.

The live Mac sources are Study and Life. Their separately configured metadata, encrypted-reader and model permissions reflect the same confirmed scope while remaining individually inspectable and revocable; authorization does not cause a full-corpus cloud upload. Old Note/Daily test roots were removed and ROG is inactive; earlier permissions and tests remain historical, not automatic authorization for other roots. No cloud sensitivity classifier is used.

`sources.yaml` and the PA1 policy remain authoritative on their owning Mac. Authenticated owner inputs from local conversation, bound Feishu private chat or PWA may express grants and revocations for Mac to verify, persist and audit. The remote authorization-management endpoints are not yet implemented.

### Local State Store

Each Local Node uses SQLite for document metadata, index state, task state, confirmation scopes, reminder delivery, and operation records. Human-readable memory and reusable rules remain Markdown in later phases. Source originals are never copied into the transactional authority; the local FTS search index necessarily retains searchable text, separately from business-state and version-metadata tables. It is not an archive of source files and remains private to the owning node.

### Document identity and versions

- A `document_id` is a stable UUID assigned on first discovery by the owning Local Node.
- A `content_hash` identifies one indexed Document Version.
- Evidence snapshots record both values, plus source location and indexing time.
- A reconciliation may preserve a `document_id` through a confidently detected rename or move. If identity cannot be determined, it records a new document rather than silently guessing.
- Documents with the same content version on different nodes are shown as one Replica Group with separate available evidence paths.

### VPS catalog

PA0 search tasks synchronize policy-authorized metadata: node status, source ID, document ID, title/path hint, update time, availability and coverage counts. The user authorized private as well as nonprivate on-demand PWA text reading. Local `remote_evidence`, additional `private_remote_evidence` for private content, metadata path permissions and fresh exclusion/version checks jointly gate access. Nodes encrypt bounded text and locations for a temporary browser key; the VPS holds only ephemeral ciphertext in memory, never source plaintext or decryption keys. The existing PA0 Feishu search implementation remains metadata-only; private analysis and excerpts are authorized for the bound owner, and a separate PA1 analyze/research owner-private endpoint now provides validated replies; see [PA1 acceptance](docs/pa1-acceptance.md). Local FTS holds extracted text; PA0 itself does not invoke models or build vectors; PA1's separate local CLI now provides those capabilities under independent policy.

## 5. Security and privacy requirements

- All PWA traffic uses HTTPS and independent owner authentication. The user explicitly selected static-password login for the initial IP deployment; require a long password, salted scrypt storage, rate limiting, secure cookies, session expiry, Origin and CSRF checks. Passkeys/TOTP remain optional later choices, never silently enabled or substituted.
- Each Local Node enrolls once with a pairing code, stores its node credential in the system credential store, and uses short-lived, renewable credentials for subsequent HTTPS requests.
- Feishu events must arrive through the authenticated platform SDK TLS socket transport or pass platform signature verification on a webhook, and be accepted only from the configured user `open_id`. The initial existing AstrBot socket adapter uses one-time private-chat binding; the PA0 plugin rejects webhook, group and other-platform events. See [Feishu implementation](docs/pa0-feishu.md).
- Bound owner Feishu private chat may show personal analysis and relevant private excerpts, including proactive notifications for already-enabled work. The user accepts Feishu platform exposure of these replies. Group chat, other recipients and public disclosure need separate permission; this scope does not activate new background work. The PA0 search plugin currently implements metadata-only responses; expanded analysis is provided by the separately authorized PA1 owner endpoint.
- PWA shows evidence cards with title, node, source, path, location, and minimal excerpt according to policy. Original files open only through an online owning Local Node on the user's device.
- Source policy authority and execution remain on Mac; verified owner requests may originate from local conversation, bound private chat or authenticated PWA. Channel-originated permission management must be implemented and verified before being advertised as available.
- Node state backups are encrypted before leaving the node; decryption keys never enter the VPS.
- The earlier `F:\Backup` target is historical after ROG was disabled. On 2026-10-14 the user explicitly deferred independent backup placement and recovery-key preparation because source data already has user-managed cloud backups. These operations are outside the current PA0 acceptance scope. Existing encrypted state backups and OS credentials are retained; source cloud backups do not establish verified assistant-state or credential recovery. See [backup and recovery](docs/pa0-text.md).

## 6. PA0 — source evidence search

### Implementation status

PA0 passed all seven acceptance criteria under the revised Mac-only scope on 2026-10-14, including a real user-operated hardware sleep followed by automatic heartbeat and same-task recovery. Production code is updated; independent backup placement and recovery-key preparation are explicitly deferred by the user. A full hardware reboot remains untested. PA1 now has a separate local CLI with offline semantic retrieval and independently authorized real-source analysis, documented below. See the [final acceptance record](docs/pa0-acceptance.md).

On 2026-10-14 the user explicitly chose Mac-only retrieval and disabled ROG to reduce maintenance. The active production node is `mac` (448 Study/Life Markdown documents as verified on 2026-10-14); PWA, Feishu and encrypted nonprivate text reading remain enabled. ROG services, tunnel and Windows startup task are disabled, and its server registration is disabled without erasing enrollment, source files, local index or encrypted backups. New searches target only Mac; old views exclude disabled nodes and their cached results. Earlier real two-node replica/offline tests remain historical validation, not a current deployment prerequisite. Mac encrypted local backup/restore passed; its additional F-drive copy was not completed and the transfer attempt ended. See [Mac-only operation](docs/pa0-mac-only.md) and [text implementation](docs/pa0-text.md). Current Study/Life files, including private journals and health records, are separately authorized for minimal MiMo Flash analysis in the local PA1 CLI; Owner private disclosure is now authorized under ADR 0033; current endpoints and validation are tracked separately.

### User flows

1. The user submits a query through Feishu or PWA.
2. The VPS creates a search task and assigns it only to enabled Local Nodes (currently Mac).
3. Each online node performs SQLite FTS5 retrieval against its configured text sources.
4. The VPS aggregates allowed metadata and evidence locations into result cards.
5. PWA renders a State-First view: query, evidence cards, node availability, active/waiting tasks, and audit entry point.
6. Feishu sends a Feishu Search Summary and links to PWA for details.

### Offline and partial results

If a node is sleeping or offline, the VPS marks the task as waiting for that node. It immediately returns results from online nodes as a Partial Result, explicitly naming the unavailable node. When that node polls again, it executes the pending job; the task is supplemented and the user is notified.

### Indexing and reconciliation

- Indexing and reconciliation are explicit PA0 operations; no filesystem watcher is used.
- A node reconciles after startup or wake, then every six hours while it remains online.
- Reconciliation compares metadata first and computes content hashes only for candidate changes.
- Added, modified, renamed/moved where confidently recognized, and deleted documents update the local index. Deleted documents must cease appearing as current hits.

### PA0 acceptance criteria

PA0 is complete only when all of the following are demonstrated:

1. The active Mac node indexes an isolated synthetic Markdown fixture. ROG is optional under the user's revised scope.
2. Searches return stable document identities and current evidence locations from the active node.
3. Identical content groups by version and preserves separate document identities. Real Mac/ROG same-version aggregation was already verified; reactivating ROG is not a current acceptance condition.
4. When an enabled node is offline, PWA and Feishu show waiting/partial state and resume the same task after recovery. Disabled ROG must never cause waiting or expose its old results. Real multi-node offline/recovery is retained as prior evidence.
5. Automated fixture tests create, modify, and delete Markdown files and verify reconciliation behavior.
6. A read-only manual search is performed against `/Users/corleone/Documents/test_for_asis`; it must not mutate that source.
7. Feishu and PWA expose only the information each channel is permitted to show.

## 7. PA1 — contextual exploration

PA1 follows a passing PA0. It adds local hybrid retrieval, Context Bundles, and model-based analysis.

Implementation status (2026-10-15): the Mac CLI provides FTS5 plus real offline multilingual-e5-small retrieval, paragraph-window vector caching, independent source/provider/private grants, fresh minimal Context Bundles, transactional token reservations, a MiMo adapter, and citation validation. The user-selected model is `mimo-v2.6-flash`, with 100,000 tokens/day, 1,000,000/month, ordinary maximum completion 512 and research maximum completion 3,072. The user confirmed root-scoped standing access to Study/Life, including future files, journals and health records; separate local PA1 policy applies to approved providers and synthetic-only mode is disabled. Credentials and explicit exclusions are checked locally before indexing and use. Private owner-channel disclosure and attributable automatic memory are authorized under ADR 0033; their implementation status is distinct from permission. Owner PWA/Feishu analysis and bounded on-demand public research now have separate endpoints. Real private HTTPS analysis and the first owner Feishu analysis with a successful platform-send receipt have passed; manual browser reading of a successful report and unattended sleep/reboot recovery for the new analysis worker remain unverified. See [PA1 acceptance](docs/pa1-acceptance.md). General Agent runtime, continuing delegations and remote permission management remain separate unimplemented work. See [PA1 implementation and live evidence](docs/pa1-local.md).

The future Personal Agent is intended to plan within bounded permissions, select tools, and adapt to execution results, supporting user requests, explicitly delegated continuing work, and Proactive Preparation within agreed topics, sources, and budgets. The assistant owns work, data, permissions, and results while integrating a replaceable agent runtime; Pi is a candidate for validation. See [Agent architecture discussion](docs/agent-architecture.md), [runtime boundary ADR](docs/adr/0019-keep-assistant-authority-outside-the-agent-runtime.md), and [proactive preparation ADR](docs/adr/0020-allow-bounded-proactive-preparation.md). Concrete triggers, limits, notification and stop conditions, and delivery stages remain under design. This direction does not enable new subscriptions or alter existing source-policy, model-disclosure, external-write, or PA0 restrictions; the Agent runtime has not been selected or implemented.

Continuing work is managed as an independent Work Delegation with associated Delegation Runs; chat is an entry point rather than the sole progress record. The chosen agent organization is one Supervising Agent with three continuing Specialist Agent roles: knowledge research, applications and career, and life records and review. Each specialist keeps separate Domain Working Context; the supervisor receives necessary results and cross-domain sharing is policy-filtered. See [delegation lifecycle ADR](docs/adr/0021-track-continuing-delegations-outside-chat-sessions.md), [agent organization ADR](docs/adr/0022-organize-agents-as-a-supervisor-and-persistent-specialists.md), and [specialist context ADR](docs/adr/0023-separate-specialist-contexts-and-filter-cross-domain-sharing.md). These roles do not change PA1's current single-online-node execution boundary or the private-source model restrictions.

Specialist context combines confirmed domain goals and constraints with independent delegation work records and relevant historical retrieval, rather than one indefinitely growing domain conversation. Role, delegation, and runtime-session identities remain distinct; tentative analyses do not automatically become confirmed personal facts. See [delegation context ADR](docs/adr/0029-organize-specialist-context-around-delegations.md).

Supported capabilities include domain tools, scripts/commands, and browser operations. Scripts write code and artifacts in dedicated workspaces; original sources remain read-only, and existing-file modification, software installation, and system changes need separately defined permission. Browser reading and content preparation may use explicitly approved authenticated sites; remote changes remain subject to confirmation. Independent specialist work may execute with bounded parallelism under a shared budget, while browser operations using the same account are queued separately. See [general automation boundary ADR](docs/adr/0024-bound-general-automation-to-workspaces-and-approved-sites.md). Parallelism limits, concrete schedules, retention, execution isolation, site/account configurations, and credential/session integration remain undecided; the capability choices do not authorize unrestricted machine or account access.

Cross-domain specialist requests are routed and consolidated by the supervisor. A delegation may adjust its check frequency within user-set bounds and budget, with visible reasons and next-check time and a user override. Ordinary results are digested; required user intervention, impending deadlines, and persistent failures prompt timely policy-filtered notifications. The first version waits for the original execution node after an interruption, with no automatic in-flight cross-node takeover. See [supervisor routing ADR](docs/adr/0025-route-specialist-collaboration-through-the-supervisor.md) and [owning-node recovery ADR](docs/adr/0026-resume-interrupted-runs-on-the-owning-node.md). Exact triggers, thresholds, schedules, checkpoint mechanisms, and unknown-result handling remain to be designed.

Stopping a continuing delegation defaults to pausing it and its child work, retaining results and awaiting explicit resumption; stopping only the current run and cancelling the delegation are separate explicit actions. Active user requests receive an early acknowledgement/plan and state entry point, then preliminary evidence-aware results as available before background completion. They receive priority and reserved capacity over ordinary background work, subject to total budget limits and configured deadline exceptions.

Reading inputs use separate Subscription Discovery and Personal Selection entry paths. WUCAI directly adapts its official read interfaces; Folo includes all existing subscriptions screened for delegation topics; WeChat initially uses existing clips, shared links, and available subscriptions. Zhihu uses its official CLI, with followed-content coverage still to be verified; Xiaohongshu uses the user-selected `xpzouying/xiaohongshu-mcp` behind a controlled read adapter for keyword searches, shared notes, visible favorites, and the home recommendation feed. Personal selections remain searchable, while subscription bodies are retrieved and cached when relevant rather than fully archived. Ordinary articles and nonsensitive user annotations may enter minimal MiMo Context Bundles; ungranted private/health material remains restricted and uncertain sensitivity must be resolved locally before disclosure. Current Study/Life private files have a separate MiMo Flash grant under [ADR 0032](docs/adr/0032-allow-private-model-context-with-explicit-provider-grants.md). See [information-source investigation and design choices](docs/information-sources.md), [reading-retention ADR](docs/adr/0027-retain-personal-selections-and-cache-relevant-subscription-content.md), and [reading-disclosure ADR](docs/adr/0028-allow-minimal-mimo-context-for-nonsensitive-reading-content.md). Obsidian remains optional. Cache-expiry mechanics, account/history coverage, concrete policy classification, budgets, and connector implementation remain pending; none has been enabled, and reading-platform connectors remain unimplemented; current indexing uses locally configured Markdown and explicitly enabled PDF/Office text.

Personal selections use best-effort backfill of all accessible history with explicit coverage limits; subscription streams are mainly incremental from activation. Ordinary body caches expire after 30 days, while selected content follows its own retention rules and cited minimal evidence follows audit policy. The Agent may automatically promote bodies under user-approved rules, with explicit Agent Selection provenance, reasons, and revocation. Removing a local selection does not automatically exclude future rule-based selection; source deletion, permission revocation, and fresh policy checks still apply. Exact rules, expiry calculation, and evidence-retention mechanics remain to be implemented. Local promotion does not write favorites back to platforms or imply user endorsement. See [selection-rule ADR](docs/adr/0030-promote-reading-cache-under-approved-selection-rules.md).

Successful temporary scripts and workflows may generate Capability Proposals containing purpose, dependencies, permissions, validation, and rollback. User confirmation of a specific version is required before registration as a long-term tool or skill; registration does not expand data permissions or authorize future external writes. Material capability-version or permission changes require renewed review. See [capability-registration ADR](docs/adr/0031-review-capability-proposals-before-registration.md); this capability remains unimplemented and its delivery slice is not yet assigned.

### Retrieval and model execution

- Hybrid retrieval combines exact/full-text search with local semantic vector retrieval. Either path may degrade independently.
- One online Local Node is selected for each PA1 analysis. It builds the minimal Context Bundle and calls the model provider directly.
- The VPS does not aggregate source text. Cross-node model synthesis is deliberately deferred.
- The first provider is Xiaomi MiMo through a documented OpenAI-compatible API adapter. API endpoint, model ID, and pricing plan are deployment configuration, not business rules.
- The current Mac-only PA1 plan stores MiMo credentials only in Mac's system credential store. ROG receives no credential or model work. The earlier shared-key decision applies only if another inference node is explicitly restored; rotation then updates all holders.
- Each node enforces configurable daily/monthly Token or cost limits, warns near the threshold, and stops new model jobs at the threshold. Local search remains available.

### Owner channel execution

The PWA now submits PA1 queries through authenticated, CSRF-checked routes. A separate Mac semantic worker executes calls without blocking PA0 heartbeats. The VPS holds requests and encrypted results only in bounded RAM; outputs bind request identity, nonce and channel using RSA-OAEP/AES-GCM. Feishu decrypts only inside the bound-owner adapter before sending; plaintext output never enters the coordinator database or ordinary logs. Completed ciphertext expires after 30 seconds, transport requests after 15 minutes. Local durable model records retain idempotency and accounting independently; unknown or invalid calls are never automatically paid again. Page/server restart recovery limits and deployment evidence are documented in [PA1 acceptance](docs/pa1-acceptance.md).

### External research

In the initial on-demand PA1 flow, external research starts only for questions explicitly requesting current information, trends, research, or lookup. Later, an activated continuing-work or proactive-preparation scope may also trigger external research when that scope explicitly permits it. Research strategy must record question decomposition, source routes, citation tracing, cross-checks, fallback paths, and remaining evidence gaps.

Primary vendor material, papers, standards bodies, and independent benchmarks may support a conclusion. Media, forums, and social discussions are Signal Sources only: they may surface claims or disagreement but cannot alone substantiate a key conclusion.

Every time-sensitive external conclusion records publication date, retrieval time, and freshness policy. Product, financial, and market claims refresh faster than durable technical foundations.

This PA1 flow remains On-Demand Research. Later Opportunity Subscriptions are a separate opt-in workflow: each subscription defines its topic, sources, schedule, budget, expiry, and pause control before background research starts. A product specification does not authorize any live subscription.

### AI-chip exploration acceptance case

Input: the user asks about the current AI-chip landscape and future trends, states that they have deep-learning and inference-engine material, and asks for a direction worth pursuing.

The Exploration Report must contain:

1. evidence-linked account of relevant existing knowledge and its limits;
2. dated current external evidence, clearly separated from Signal Sources;
3. identified knowledge gaps;
4. two or three Direction Hypotheses, each with a connection to existing knowledge, capability gap, opportunity/risk, and next validation step;
5. uncertainty, disagreement, and any unretrieved evidence caused by source or backend failure.

The report offers direction hypotheses; it does not automatically create a learning task or calendar event.

## 8. Later phases

| Phase | Capability | Required guardrail |
|---|---|---|
| PA2 | Extract Task Candidates from user-provided material | Candidate is not a Task until user confirms it |
| PA3 | Project time-bound confirmed tasks to Google Calendar | Service-owned OAuth; exact, expiring Confirmation Scope; no bidirectional sync |
| PA4 | Memory Ledger and Reusable Rules | Layered readable Markdown; rule proposals show scope, counterexamples, and impact before confirmation |
| PA5 | Email Adapter | Provider-neutral adapter; continuous receipt, history association, draft only before explicit send confirmation, and duplicate prevention |

The assistant owns Task Authority. Google Calendar is only a projection for confirmed, time-bound arrangements.

### Domain delivery alongside the infrastructure phases

The phase numbers describe infrastructure, not an order in which life domains become important. Wellbeing records, weekly reviews, and career comparison may start immediately as user-owned Markdown and manual actions. PA0 can retrieve permitted text; PA1 can analyze permitted career evidence, while restricted wellbeing data stays local. Simple local summaries must preserve missing-data information and require no model. PA2/PA3 later connect reviewed actions to tasks and calendar projections; PA4 retains reviewed goals and corrections. PA5 email is not a prerequisite for these workflows.

Wearable integrations, nutrient/portion estimation beyond visible food recognition, scheduled opportunity collection, and additional model adapters are separate enhancements. None is required for the first development review. Free consumer models may be used manually only with deliberately selected, policy-permitted context; they are not assumed to provide free APIs or automatic background execution. Model Cross-Review uses a fixed evidence snapshot, provider-specific disclosure controls, a combined review budget, and visible disagreement; it never promotes consensus into evidence.

Health workflows organize observations and prepare user-reviewed questions for professionals. They do not diagnose, prescribe, recommend medication changes, or turn a device estimate into a medical fact. Career briefs present scenarios and validation steps rather than guaranteed employment or income predictions.

### First domain pilot — graduate applications and low-burden wellbeing capture

The first domain pilot combines a Graduate Application Decision Brief with Meal Capture, Sleep Check-Ins, and Journal Reflection. The target scenario is a third-year microelectronics undergraduate exploring computer systems design, hardware/software co-design, and high-performance computing, prioritizing mainland China and then Hong Kong. Outreach starts in 2026, recommendation-based admission is the primary route, and September 2027 is the user's offer target, not an assumed official deadline or guaranteed result. The dietary goal is healthy eating with fat loss; it does not imply a preset weight target or calorie deficit.

Food recognition is a narrowly scoped photo workflow, not a relaxation of PA0's text-only indexing gate. It requires a verified vision-capable adapter and a source-specific permission for any image sent to that provider; the existing MiMo adapter is not assumed to support it. If vision is unavailable or disallowed, the photo remains a user-owned record with an optional short description.

Sleep events retain user/message time, timezone, corrections, and unpaired states. A bedtime/wake interval is reported as a self-reported schedule interval, not actual sleep duration. The user has authorized full local read-only access to Obsidian `daily` for journal reflection; the actual vault path is still deployment configuration. Reviews use relevant recent entries and retrieve older evidence when needed rather than injecting the entire corpus. Reading, model processing, memory and disclosure remain distinct permission axes. The user has now explicitly granted those axes for Study/Life under the standing policy, including attributable automatic memory; PA4 memory implementation is still pending.

Feishu is the selected capture channel and an explicit source-specific extension of the current search-only interface: submitted wellbeing messages and photos reach Feishu and transit its event handler. The VPS must not persist their plaintext payloads or log them. It may forward an encrypted payload for the owning Local Node with finite retention, deduplication, and a delivery receipt; transient event-handler plaintext exposure and Feishu's own storage are part of the disclosed boundary. Capture replies may show food-recognition candidates from the submitted photo, correction prompts, and the user's own recorded check-in time. The later standing authorization separately permits relevant private analysis and excerpts in bound owner replies and already-enabled notifications. These paths still require owner identity, fresh policy checks, finite retention and transport that avoids VPS plaintext persistence; expanded Feishu analysis is not yet implemented.

Until this capture path has passed its offline and privacy checks, direct recording into an authorized user-owned source is the available fallback. A model or node failure must not be reported as successful recognition or successful local recording. Automatic meal identification may remain provisional; user corrections and explicit unknowns are retained.

## 9. Audit, retention, and recovery

Operation Records capture the trigger, evidence used, result, confirmation, external-write result, and failures. Evidence Snapshots retain the original location, excerpt, content hash, index version, and read time required to explain a past conclusion.

The confirmed retention rules are:

- attributable self-reports, preferences and experiences: continuing retention, reviewed every 90 days;
- tentative interpretations: require review after 30 days before further use;
- complete model Q&A and temporary context payloads: 30 days;
- ordinary audit records without source bodies: 180 days;
- necessary billing, request-idempotency and external-write confirmation markers: minimal records, never retaining withdrawn body content solely for audit.

Source originals follow their own source-system retention and remain read-only. Deletion or revocation stops further use, purges associated caches and invalidates memory whose only support was withdrawn; other authorized evidence may continue to support a statement. External provider/Feishu history and offline or backup copies have separately reported cleanup coverage, never a claimed automatic recall. Current implementation covers PA1 response expiry and local cache cleanup; automatic long-term memory and its reviews are not implemented.

Within the existing project Mac/VPS environment, dependency installation, configuration changes, tests, tested deployment, existing-service restart and rollback have standing authorization with target checks, rollback preparation and audit. New servers/providers/roots, increased budgets, deleting originals and third-party/public/calendar writes require separate scoped authorization. Trusted owner replies and already-enabled notifications use their existing approved scope. Project-specific Codex review supplements express these grants without replacing host-enforced rules.

Code, specifications, reusable rules, and sanitized fixtures are versioned in a private Git repository. Originals, indexes, context bundles, operation records, and personal memory are excluded.

## 10. Deferred deployment choices

The following are intentionally not decided until deployment, and must not be silently assumed:

- independent backup placement and recovery-key preparation, explicitly deferred by the user on 2026-10-14; the old ROG F-drive target is historical;
- MiMo endpoint, model ID, plan, and current quotas;
- future PWA passkey/provider migration, if requested; the current static-password method was explicitly selected;
- calendar OAuth account configuration;
- email provider and protocol;
- future derived-cache enablement;
- cross-node model synthesis;
- general OCR/multimodal ingestion beyond the scoped meal-photo pilot, additional model providers, and additional Local Nodes;
- the implementation of Feishu capture and private remote display, including offline behavior, ciphertext queue retention, and transport that prevents VPS plaintext persistence/logging and limits Feishu disclosure to its approved capture scope;
- wearable/health-app integrations and per-provider permission for any sensitive model context;
- topics, schedules, sources, expiry, and aggregate budget for Opportunity Subscriptions and Model Cross-Review.

Any choice that changes data residency, source policy, credentials, or external-write authority requires a new documented decision before implementation.
