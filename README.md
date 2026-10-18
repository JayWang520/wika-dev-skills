# WIKA Development Skills

面向 WIKA Qt/C++/QML 显示器的 AI 开发技能集：需求分析、代码定位、交叉编译、在线运行、界面与 CAN 测试、EDS 配置、翻译同步和升级包交付。

## 技能清单

仓库直接提供 **13 个技能**，完整工作流另外引用 **3 个文档处理技能**。

| 技能 | 用途 |
| --- | --- |
| [wika-dev-flow](skills/wika-dev-flow/SKILL.md) | 需求到交付的流程入口 |
| [wika-build](skills/wika-build/SKILL.md) | Qt/ARM 交叉编译、工程发现与构建检查 |
| [wika-displayer-online](skills/wika-displayer-online/SKILL.md) | 部署、在线运行、触摸操作与抓屏 |
| [wika-ui-index](skills/wika-ui-index/SKILL.md) | 从源码、资源和截图生成控件坐标与导航计划 |
| [wika-can-debug](skills/wika-can-debug/SKILL.md) | CAN 接收、发送、脚本模拟及回环测试 |
| [wika-eds-edit](skills/wika-eds-edit/SKILL.md) | EDS/PDO 配置修改、映射核对与同步 |
| [wika-translate-skill](skills/wika-translate-skill/SKILL.md) | LangStr 中文词条提取与多语言同步 |
| [wika-app-package](skills/wika-app-package/SKILL.md) | HIRSCHMANNIMAGE .app 升级包生成与校验 |
| [codegraph](skills/codegraph/SKILL.md) | 代码结构索引与符号查询 |
| [brainstorming](skills/brainstorming/SKILL.md) | 需求澄清与方案设计 |
| [karpathy-guidelines](skills/karpathy-guidelines/SKILL.md) | 控制修改范围与定义验证目标 |
| [esafenet-share-decrypt](skills/esafenet-share-decrypt/SKILL.md) | 共享目录中的亿赛通文件处理 |
| [esafenet-decrypt](skills/esafenet-decrypt/SKILL.md) | 已授权的亿赛通容器识别与恢复 |

`docx`、`pdf`、`xlsx` 作为外部依赖列于 [第三方内容说明](THIRD_PARTY.md)，仓库和发布包不复制它们的实现。原本本机 16 个技能中的其余内容及辅助脚本均保留。

## 安装与使用

按 [安装说明](docs/INSTALL.md) 将需要的技能目录放入当前用户的技能目录。在 Codex 中输入 `$wika-dev-flow`，或要求“按 WIKA 开发流程完成这个需求”。各技能也可单独调用。

编译机需自行准备 Qt 与对应 WIKA SDK；在线测试需有到设备的 SSH 连接。工程配置可以独立保存，多项目分别使用自己的 `wika-project.json`。

本仓库示例中的网络地址使用文档示例网段；设备地址、用户名和认证信息由使用者在本机配置。请按实际机型、协议与触摸校准生成测试计划。

## 验证范围

本次发布检查技能元数据、导出文件哈希、Python 语法及 ZIP 完整性。联机辅助脚本另有 15 项模拟认证/退出码检查。源技能记录的既往设备验证仅代表各自案例；安装到新电脑或新设备后需重新完成构建与实测。

源码界面索引、SDK/控制器内部回环与物理 CAN 总线验证的覆盖范围分别记录。界面导航成功不能作为业务数据或物理总线验收的依据。

发行文件和逐文件 SHA-256 清单可在 Releases 下载。
