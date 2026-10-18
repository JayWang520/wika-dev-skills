---
name: codegraph
description: 本地代码知识图谱（C++/QML/JS/Python）：读代码文件前若工程没有 .codegraph 索引就先 build 建图，之后用 search/defs/refs/impact 快速定位符号、调用关系与改动影响面（替代大范围盲 grep）；程序修改后用 status 判断是否需要 update 增量刷新。当用户说"读代码/找函数/这个符号在哪用/改了会影响到什么/建个代码索引/更新代码图谱/codegraph"时使用。
---

# codegraph — 轻量本地代码知识图谱

把工程的符号定义索引到 SQLite+FTS5，引用/影响面按需实时 grep——**引用永不因代码改动过期**，只有定义索引需要 build/update。

- **脚本**：`<技能安装目录>/codegraph/scripts/codegraph.py`（纯 python3 标准库，无依赖）
- **索引位置**：`<工程根>/.codegraph/codegraph.db`，按工程分别建，随工程走

## 什么时候用（流程约定）

1. **读代码文件前**：先看工程有没有 `.codegraph/codegraph.db`——
   - 没有 → `build` 建图（秒级：736 文件的 SDC190H 约 4s）
   - 已有 → `status` 确认新鲜（有源码改动先 `update`）；用 `search/defs/refs/impact` 定位后再只读命中的少量文件，不要大范围盲 grep。
2. **程序修改后**：`status` 查改动 → 动了被索引的源码就 `update` 增量刷新（只重扫变化文件，无改动时运行也安全）；只改文档/资源不需要。**新增或重命名符号后必须 update**，否则后续查询会漏。

## 命令

全部以 `python3 <技能安装目录>/codegraph/scripts/codegraph.py <命令> <工程根>` 调用：

| 命令 | 用途 |
|---|---|
| `build <root>` | 全量建索引（首次；重建也是它） |
| `update <root>` | 增量更新（改码后） |
| `status <root>` | 索引状态 + 待更新文件清单 |
| `search <root> <关键字...>` | FTS 前缀检索符号（多词 AND），不知道全名时先用它 |
| `defs <root> <名字>` | 符号定义位置（class/struct/enum/macro/fn/QML function/signal/property/id） |
| `refs <root> <名字>` | 全部引用（实时 grep；名字带 `::` 时按全名精确查） |
| `impact <root> <文件...>` | 改这个文件的影响面：文件内符号 → 哪些文件引用 |
| `explore <root> <词>` | 一个入口查完：文件名→影响面；符号→定义+引用 |

## 解析范围与局限

- 支持 C++（.cpp/.h/.hpp/.cc/.c）、QML、JS、Python、qmake；跳过 `build-*`、`.git`、`node_modules`、`moc_*/ui_*/qrc_*` 等生成文件。
- C++ 为行级正则提取（多行签名、宏内的函数、花式写法可能漏）——漏了就用 `search` 模糊兜底，`grep` 补充。
- 多类同名方法（各页面都有 `initialization` 等）：`impact` 自动按类名过滤并标注 `[同名方法已按类过滤]`；要精确列表用 `refs <Class>::method`。
- 工程源码若是亿赛通密文（读出乱码）先按 **esafenet-share-decrypt** 技能解密再 build，否则索引到的是密文噪声。

## 已验证

- 2026-10-13 SDC190H 建图：736 文件 / 6115 符号 / 4s；`impact Program/bdata_jishuqiinfor.cpp` 正确给出 3 个受影响文件（Form_JiShuQIInfor.qml、bdata_jishuqiinfor.h、main.cpp）；`refs set_drill_hole_depth` 命中 C++ 与 QML 两处。
