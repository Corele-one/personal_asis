# PA0 纯文本索引、加密阅读与备份

> 当前状态（2026-10-14）：用户选择只用 Mac 检索，ROG 已停用。下文索引和双设备验收是已完成的历史记录；本机资料、索引与备份保留，不继续日常维护。见 [Mac 单节点运行](pa0-mac-only.md)。

## 授权与范围（2026-10-14）

用户指定在 ROG 的四个 Windows 来源尝试 PDF／Office **文本**索引，再完成 PA0。原文件保持原位置；不提取图像、音视频或 OCR。用户随后明确允许非私密资料的最小摘录及 PWA“查看正文”，仅中转、不在 VPS 保存明文；这不开放私密正文或模型处理。

`formats` 按来源显式启用，默认仍为 `md`。支持 `pdf`、`docx/docm`、`xlsx/xlsm`、`pptx/pptm`、`doc/xls/ppt`；带宏的 OOXML 只读取 XML 文本，不执行宏。Word 保留段落位置，PDF 保留页码，PowerPoint 保留幻灯片顺序及文本备注，Excel 保留工作表／单元格位置、公式字符串及已有缓存值，不计算公式或获取外部链接。旧 Office 格式在禁网子进程中使用 LibreOffice／UNO 临时转换，原文件只读；不是原始排版预览。

## ROG 实际覆盖

| 格式 | 已索引文件 |
|---|---:|
| Markdown | 879 |
| PDF | 1,125 |
| Word DOC／DOCX | 257／540 |
| PowerPoint PPT／PPTX | 82／301 |
| Excel XLS／XLSX | 19／106 |
| 合计 | **3,309** |

3,616 个候选中跳过 307 个：无可提取文本 267、原文件超限 13、解析错误 16、PDF 解析错误 1、文本超限 2、加密 4、解压总量超限 1、旧格式转换失败 2、转换超时 1。无文本不自动等同于扫描件；这些文件不会以已全文覆盖报告。失败原因与相对路径仅存本机，远程只显示来源级跳过计数。

来源 `documents/google-download/qq-files/edge-download` 分别索引 786／62／634／1,827 个文件。七类 PDF／Office 均完成真实内容查询，验证页码、段落、幻灯片或单元格定位；查询正文和结果不进入仓库。先前 879 个 Markdown 的 UUID／内容哈希全部保留。22,031 个原文件的大小、mtime 和 Windows 创建时间在索引前后均不变。

ROG 仍只允许三个已选技术 Markdown 的远程元数据。新增 PDF／Office 均按未审阅条目留在本机私密索引；启用格式或阅读功能不扩大路径白名单。Mac Life 的私密元数据例外不授权正文。

## 限额与依赖

二进制单文件 128 MiB、ZIP 单成员 64 MiB、解压总量 256 MiB、文本 400 万字符、定位单元 20 万；解析进程 90 秒，旧 Office 转换 45 秒。Linux 额外限制虚拟地址空间与 CPU；LibreOffice 转换在独立网络命名空间执行，禁宏、禁外部更新。macOS 不设置不兼容的 `RLIMIT_AS`，仍执行输入、解压、文本、单元、CPU 和墙钟限额。未变化的失败签名缓存于本机，避免每次核对重复启动转换。

ROG 使用 `/home/corleone/.local/share/personal-asis-env/bin/python`（3.11.15），包含 `pypdf`、`cryptography`；PDF 优先使用 `pdftotext`。旧 Office 需要 Ubuntu `libreoffice-writer libreoffice-calc libreoffice-impress python3-uno` 及 `unshare`。合成 PDF 测试另需 `reportlab`。Python 可选依赖见 [pyproject.toml](../pyproject.toml)，`asis doctor` 报告实际后端；VPS 中转不需要安装这些解析包。

## PWA 按需阅读

本机来源配置 `remote_evidence: true` 后，只有同时通过远程元数据路径规则、当前非私密、当前 UUID／哈希核验的命中才有阅读入口。私密来源／路径／frontmatter 即使另获元数据许可，也不能输出正文。来源权限只能在所属本机修改。

浏览器每次阅读生成临时 RSA-OAEP 2048／SHA-256 密钥。本机以随机 AES-256-GCM 密钥加密文本及位置，再用浏览器公钥封装密钥；文档 ID、版本、模式、字符游标和客户端随机数绑定到认证数据。浏览器私钥和明文不发送到 VPS。服务端只在内存中保存公钥、任务元数据和密文，最多 32 项、90 秒有效，节点租约 45 秒；无 SQLite／outbox／文件落盘，重启或政策变更会使请求失效。

摘录最多 240 字符；“查看正文”每次最多 6,000 Unicode 字符，前后分段均重新检查文件版本。位置包含在密文中。浏览器通过 `textContent` 展示，关闭、退出或页面隐藏时清除文本，不写 Web Storage、IndexedDB 或服务 Worker 缓存。这里的清除是页面状态清除，不声称能擦除用户截屏或浏览器／系统内存的所有副本。飞书仍只接收元数据摘要，不能索取正文。

PWA 请求需要既有 owner Cookie、Origin／CSRF，并从已有搜索命中选择资料；没有任意路径读取接口。PWA 与协调进程通过权限 `0600` 的本机 Unix socket 连接，节点继续通过出站 SSH 隧道领取工作，没有新增公网本机端口。

真实 ROG 合成资料和一个已获白名单许可的真实条目，均通过生产 VPS 中转密文并在 ROG 解密，与本机读取结果一致。Mac 合成摘录也已完成相同的真实加密链路验证。合成测试覆盖 owner API、CSRF、密文完整性及版本绑定、私密元数据不变成正文许可、撤权、过期、容量限制和 WebCrypto 解密互通。浏览器点击验收单独记录，不以这些协议验证替代。

## 加密备份与恢复

用户指定 ROG 备份目标 `F:\Backup`，实际归档位于 `F:\Backup\PersonalAsis\ROG`。AES-256-GCM 认证加密在本机完成；32 字节随机密钥留在 Windows 凭据管理器，Mac 使用 Keychain。不在 VPS 保存备份或密钥。

备份仅包含来源配置、连接地址配置、权限记录、索引及节点任务库，不含原文件、系统凭据或解密密钥。SQLite 通过在线备份 API 创建一致快照；归档清单含逐文件 SHA-256。恢复到空的仓库外目录，认证成功后才解析归档，拒绝路径穿越、链接和未知成员，并校验 SQLite。实际 ROG 恢复演练已核对全部文档 UUID／哈希、来源配置及真实本机查询结果。

```sh
asis backup create --target /mnt/f/Backup/PersonalAsis/ROG
asis backup restore --archive /ABSOLUTE/FILE.asis-backup --target /ABSOLUTE/EMPTY/PRIVATE/DIR --node-id rog
# 在本机交互终端显示恢复密钥；应由用户另存于独立安全位置，不能发到聊天或 VPS
asis backup recovery-key --node-id rog
# 丢失系统凭据时，交互输入已另存的恢复密钥
asis backup restore --archive /ABSOLUTE/FILE.asis-backup --target /ABSOLUTE/EMPTY/PRIVATE/DIR --use-recovery-key
```

本次 ROG 演练使用现有系统凭据，未导出密钥；它不证明机器及凭据同时丢失后的灾难恢复。指定 F 盘是当前已授权目标，不冒充异地／离线冗余。Mac 更新脚本也创建本机加密备份并恢复核验，但 Mac 归档尚未复制至 ROG 的 F 盘；传输等待超时后已清理临时管道。用户随后停用 ROG，此复制不再作为当前检索交付的前提。

## 本机报告与 Mac 验收

详细清单、原文件比对、真实查询证明、加密中转及备份恢复报告留在 `D:\23644\PersonalAsis\reports\2026-10-14`，不进入 Git 或 VPS。既有分类／重复清单仍保留在前一天的本机报告中。

Mac 无直接 SSH 入口，由用户在 UU 的 Mac 终端运行 [更新脚本](../scripts/pa0-mac-finish)。脚本下载代码发布包、校验哈希、在本机隔离环境测试后切换 launchd；有旧配置／索引回退快照，不修改原资料或原 checkout。随后执行 [合成验收脚本](../scripts/pa0-mac-acceptance)，保持终端运行供真实双节点检索；Ctrl+C 只撤除自己的合成来源和未被修改的合成文件，并核对索引。
