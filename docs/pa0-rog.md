# PA0 ROG 历史部署记录（已停用）

> 当前状态（2026-10-14）：用户选择只用 Mac 检索，ROG 已停用。下文索引和双设备验收是已完成的历史记录；本机资料、索引与备份保留，不继续日常维护。见 [Mac 单节点运行](pa0-mac-only.md)。

## 现场状态（2026-10-13—14）

ROG 已接入现有 VPS 协调服务。WSL 发行版为 Ubuntu-22.04，用户 `corleone`；解释器由 Python 3.11.15 创建的 `/home/corleone/.local/share/personal-asis-env/bin/python` 承载，SQLite 3.50.4，FTS5 trigram 可用。扩展格式和加密依赖见 [文本说明](pa0-text.md)。

本机原文在 Windows，WSL 通过 `/mnt/d`、`/mnt/e` 只读打开获准的 Markdown／PDF／Office；运行配置、索引、权限记录与 outbox 存于 WSL 的 `~/.local/share/personal-asis/`，目录权限 `0700`、文件 `0600`，不进入仓库。源码仍使用本 checkout 的 `src/`；移动 checkout 或解释器后需重装用户服务。

用户授权四个 Windows 目录的本机只读索引，并允许其中**非私密**条目的标题、来源和相对路径进入 VPS／飞书／PWA。实际根路径和逐文件分类只记录在本机配置及私密盘点报告中；初始元数据许可不继承 Mac Life 的私密元数据例外。用户随后另行允许非私密最小摘录及按需正文，经加密中转供 PWA 查看；不开放私密正文或模型处理。

| 来源 ID | Markdown | 当前远程白名单 |
|---|---:|---:|
| `documents` | 278 | 0 |
| `google-download` | 37 | 0 |
| `qq-files` | 63 | 2 |
| `edge-download` | 501 | 1 |
| 合计 | 879 | 3 |

四个来源均 ready；当前 PDF／Office 跳过计数另见下文和 [文本说明](pa0-text.md)。以下为最初 Markdown 权限盘点：基于技术项目路径和 README／许可证等明确说明文件名保守选择 3 个非私密候选；frontmatter 的 private 标记仍优先。其余 876 个当前条目按未审阅私密路径配置，保持本机可检索。这不是逐篇内容审阅，不能据此认定其内容一定敏感或一定公开。后续放宽范围须在本机审阅及更新配置；新增路径不会自动进入远程白名单。

## 常驻与凭据

- `personal-asis.service`：systemd 用户服务，登录／WSL 启动后核对索引，在线每六小时核对，每 30 秒出站轮询，来源离线每分钟重试，无文件监听。
- `personal-asis-tunnel.service`：使用既有 WSL SSH 认证，以 `wzliao@35.209.202.207:22` 连接服务器；仅监听 `127.0.0.1:18765`，转发到服务器 `127.0.0.1:8765`，核验既有主机身份，失败后自动重试。
- 节点长期凭据通过标准输入／输出管道存取 **Windows 凭据管理器**，不进入命令参数、配置、Git 或日志；systemd 非交互环境也已实际验证。实现使用 [Microsoft CredWriteW](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credwritew) 与 [CREDENTIALW](https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw)。普通 Linux 继续使用 Secret Service，Mac 继续使用 Keychain。
- Windows 任务计划 `PersonalAsis-ROG` 在当前用户登录时隐藏启动 WSL 保活进程，允许电池供电，不设置运行时限；已手动启动并核验 Running。用户退出、关机、休眠或主动关闭 WSL 时节点仍可离线；真正重启电脑和休眠／唤醒尚未现场测试。

服务器已新增 `rog` 节点并配对；通过 systemd drop-in 将协调服务节点声明改为 `mac rog`。保留已有 PWA、AstrBot 和 Mac 认证状态。

## 使用与维护

在 WSL 中：

```sh
asis doctor
asis status
asis search "学习" --limit 5
asis search "STM32" --limit 5
asis reconcile
systemctl --user status personal-asis personal-asis-tunnel
journalctl --user -u personal-asis -n 50
```

在 Windows PowerShell 中也可直接调用：

```powershell
wsl -d Ubuntu-22.04 -- /home/corleone/.local/bin/asis status
wsl -d Ubuntu-22.04 -- /home/corleone/.local/bin/asis search "学习" --limit 5
Get-ScheduledTask -TaskName PersonalAsis-ROG
```

checkout 的脚本默认使用 `python3`；此 WSL 的系统 Python 为 3.10，因此用户命令 `~/.local/bin/asis` 显式选择已验证的 Python 3.11。手动从仓库执行扩展功能时使用 `ASIS_PYTHON=/home/corleone/.local/share/personal-asis-env/bin/python scripts/asis ...`。shell 脚本采用 LF，避免 Windows checkout 的 CRLF 破坏 Linux 入口。

卸载时分别执行 `asis service uninstall`、`asis tunnel uninstall`，再在 Windows 任务计划程序删除 `PersonalAsis-ROG`；索引和来源原文件保留。停止服务不会删除系统凭据，撤销节点需服务器管理员执行 `coordinator revoke --node-id rog`。

## 文件整理交付

用户选择只读分类与重复清单，保留所有原位置。四个根目录共 22,031 个文件、46,848,157,141 字节（43.63 GiB），包括 879 个 Markdown、1,385 个 PDF、1,352 个 Office 文件。原始报告包含按扩展名分类、可筛选原路径列表、重复组和处理建议；当时尚未提取 PDF／Office 正文，未移动或删除原文件。随后文本索引见下文。

9,178 个非零同大小候选全部完成 SHA-256 校验，读取约 1.15 GiB；确认 1,157 组重复，包含 2,959 个文件，重复副本合计 503,586,311 字节（约 480.26 MiB）。配置的单文件 128 MiB、总读取 4 GiB 上限未导致本次候选遗漏；零字节文件未参与。软件／工程内部的相同依赖不能仅凭此表删除。

HTML 报告、完整 JSON 清单、重复组、Markdown 分类、权限决策和只读复核结果只保存在用户 Windows 私密报告目录，未进 Git 或 VPS。索引／哈希读取后复核全部 22,031 个原文件的大小、mtime 和 Windows 创建时间，变化为零。随后按用户指令扩展纯文本索引：现有 3,309 个已索引文件、307 个明确跳过文件，逐格式数量、失败原因、阅读和备份详见 [文本说明](pa0-text.md)。

## 验证与剩余边界

隔离合成来源先验证本机搜索及私密标题过滤，再以实际 ROG 进程连接生产协调服务。真实 Mac 与 ROG 均完成同一协调任务；ROG 停止服务超过 90 秒后，PWA／飞书渠道任务显示 `partial: true`、`waiting_nodes: ["rog"]`，Mac 结果仍已完成；恢复 ROG 后两项任务自动 completed。此验证通过协调层的两种渠道序列化完成，未新增向飞书用户发送消息，也未代替真实手机界面操作。

随后真实 Windows 来源也分别完成 PWA／飞书渠道的协调任务，两项任务均由实际 Mac、ROG 节点完成，各返回一个 ROG 获准元数据命中。逐项核对文档身份／哈希均在本机白名单内，无正文、摘录、原文 URI 或行号字段；未向用户飞书发送测试消息。

WSL 测试命令为 `PYTHONPATH=src /home/corleone/.local/bin/python3.11 -m unittest discover -s tests -v`，共运行 70 项：67 项通过，3 项需 VPS AstrBot 解释器的既有专用测试跳过。新增测试覆盖 systemd 安装／卸载、回环隧道、凭据管道与错误脱敏、混杂来源路径分类，以及白名单变更后即时过滤并撤销协调缓存。项目文档相对链接、`git diff --check` 和本机 HTML／JSON 清单完整性检查通过。

2026-10-14 已验证真实同版本双副本、两端加密阅读及用户实际 PWA 摘录／正文显示，并完成 ROG 加密备份恢复。最终离线恢复复核、临时源清理及 Mac 密文备份复制状态见 [文本与恢复](pa0-text.md)。真正硬件重启／长时间休眠唤醒仍未现场测试；不启用 PA1 或模型调用。
