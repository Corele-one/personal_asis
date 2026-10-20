# 原生 Pi 入口

2026-10-20：`pi`／`scripts/asis-pi` 启动固定安装的 `@earendil-works/pi-coding-agent` 1.2.0。Pi 管理模型、原生工具、会话、压缩与 MCP；Study／Life 直接按需读原库，SQLite 仅作可选发现。私密资料说明与 MCP 配置位于忽略目录 `.local/pi-agent`，或显式 `PI_CODING_AGENT_DIR`。

本轮增加两个独立步骤：交互启动前进行[日记同步确认](daily-sync.md)；加载 `runtime/pi-terminal/source-write.ts` 窄写入扩展，以 Pi UI 确认[平台写入](source-writes.md)。它们不接管普通问答／检索／会话，不引入旧 Core 的回答裁剪和强制 JSON。`--plain` 跳过个人配置、同步和写入扩展。

```sh
pi --check
pi --version
pi --continue
pi --model xiaomi/mimo-v2.6-flash
pi mcp list
pi --setup-sources
pi --plain
```

`--check` 不读取凭据、不调用模型；`--setup-sources` 只生成私密定位说明。帮助／版本／MCP管理不触发同步；JSON／RPC／print 模式不弹终端同步问题。正常交互会话先通过 SSH 拉取，未确认的记录不写入来源。同步文本不附加给模型。

原生 profile 生成文件0600／目录0700。MiMo Key 和小红书 MCP 鉴权仅在实际会话中从既有 Keychain 临时注入子进程环境，不进参数、Git 或日志。WUCAI 凭据由调用接口时读取。现有模型设置不覆盖；首次默认 MiMo Flash、关闭自动重试与缓存预热。

原生 Pi 和 AstrBot 各走自己的调用／计费，不经过旧 Asis 账本。旧每日／每月额度、未知结果防重与撤权清理不能声称约束原生历史。更换提供商前明确个人资料许可，必要时新建会话；不会自动授予新提供商旧正文权限。

这是原生工具使用约定与窄接口保护，不是 OS 沙箱。Pi 的 shell／文件工具仍有本机进程权限。真实问答、提供商可用性和资料分析质量按独立场景验收；[早期来源抽查](native-source-status.md)保留原日期。

旧会话使用 `--engine conversation`／`--engine legacy`，不迁移已付费状态。Finder 旧固定包的处理见[运维](operations.md)。
