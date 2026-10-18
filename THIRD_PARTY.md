# 第三方内容与外部依赖

## 文档技能

原本本机套件中的 `docx`、`pdf`、`xlsx` 属于第三方文档能力。PDF/Excel 本地版本标注专有许可；官方 DOCX/PDF/XLSX 许可正文均包含分发限制，因此本仓库仅列出官方来源，不复制原技能、示例、OOXML 资源或 node_modules，也不在 Release 中附带原来的本机完整 ZIP。

| 能力 | 官方来源 | 许可正文 |
| --- | --- | --- |
| docx | [官方目录](https://github.com/anthropics/skills/tree/main/skills/docx) | [LICENSE.txt](https://github.com/anthropics/skills/blob/main/skills/docx/LICENSE.txt) |
| pdf | [官方目录](https://github.com/anthropics/skills/tree/main/skills/pdf) | [LICENSE.txt](https://github.com/anthropics/skills/blob/main/skills/pdf/LICENSE.txt) |
| xlsx | [官方目录](https://github.com/anthropics/skills/tree/main/skills/xlsx) | [LICENSE.txt](https://github.com/anthropics/skills/blob/main/skills/xlsx/LICENSE.txt) |

使用者可在有相应授权的环境中使用这些能力，或配置已有的等效文档工具。WIKA 流程根据实际输入文件调用文档处理能力，不要求使用本仓库分发的副本。

## 其他来源

保留其余技能中现有的作者、来源与许可标记。本次发布未为整个集合追加统一开源许可，也未把第三方材料重新授权。`brainstorming` 为本机已使用的 Superpowers 工作流版本，包含对应配套脚本；它的可选 `writing-plans` 依赖未随本仓库收录。
