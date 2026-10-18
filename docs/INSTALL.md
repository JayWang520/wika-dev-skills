# 安装与环境配置

## 安装技能

从仓库下载源码或从 Releases 下载 GitHub 版 ZIP。将 `skills` 内需要的技能文件夹复制到当前用户的技能目录，每个目录应直接包含 `SKILL.md`。

- Windows：`C:\Users\<用户名>\.agents\skills\`
- Linux：`~/.agents/skills/`

同名技能已存在时，先比较和备份；避免在 `.agents/skills` 与旧 `.codex/skills` 中放置同名副本。Codex 未识别变更时重新打开应用。安装目录依据 [OpenAI 官方说明](https://learn.chatgpt.com/docs/build-skills)。

## 配套能力

本仓库含 8 个 WIKA 技能及 5 个开发/文件处理配套技能。流程涉及 Word、PDF 或 Excel 时，按 [外部依赖说明](../THIRD_PARTY.md) 在目标环境准备对应文档能力。`brainstorming` 的架构级分支可能调用本仓库未包含的 `writing-plans`；使用该分支时另行准备。

## 运行环境

- AI 所在电脑安装技能。构建脚本在已配置 SDK 的 Ubuntu 运行，设备端脚本在相应显示器执行。
- 主机 Python 工具需 Python 3.8+；截图分析和缩略图功能需 Pillow。SSH/SCP 辅助脚本需 OpenSSH 和 Python pexpect。
- Qt/交叉 SDK、C++ 编译环境、Node.js 以及文档处理依赖不随包分发；根据所用技能安装。
- ARMv7/Python 3.7 触摸执行器与静态 QML 索引已有案例验证；其他机型、触摸 ABI、Widgets 或动态布局先按对应技能适配和校准。

## 连接设备

优先在实际执行脚本的主机配置 SSH 别名 `display`，核对设备主机指纹并配置所需认证。脚本默认读取该 SSH 配置。

可使用 `WIKA_SSH_HOST`、`WIKA_SSH_USER` 覆盖地址和用户名。确需密码时，仅在本机通过 `WIKA_SSH_PASSWORD` 提供；仓库不提供密码、SSH 私钥或 known_hosts。

网络地址 `192.0.2.0/24`、`198.51.100.0/24` 和 `203.0.113.0/24` 均为文档示例，请换成实际地址。源码路径、SDK 路径、设备服务名及工程配置同样需要按本机确定。

## 多工程

先按 [工程配置与产物冻结](../skills/wika-dev-flow/references/project-and-release.md) 发现并确认当前工程的 `wika-project.json`。每个工程保存自己的构建入口、SDK、BIN、EDS 组和设备配置，测试与打包使用同一轮冻结的候选产物。
