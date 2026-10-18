---
name: wika-translate-skill
description: "Extract Chinese UI terms from source files and synchronize them into WIKA LangStr-based translation cpp files such as FUNC_ChineseSimp.cpp and its per-language counterparts. Use when the user needs to pull new Chinese strings out of C++ or UI source, keep the Chinese master catalog up to date, or create and update translated language cpp files while preserving index-aligned entries. Trigger phrases include 提取中文词条, 翻译同步, 多语言cpp, WIKA 翻译, LangStr 同步."
metadata:
  agent_created: true
---

# WIKA_translate_skill

## Overview

WIKA 的界面多语言方案用一个 `.cpp` 文件保存全部 UI 文本：类构造函数把每条文本
`LangStr.append("...")` 进一个列表，UI 按**索引**取词。中文文件（如
`FUNC_ChineseSimp.cpp`）是主目录（master），每种语言一个同名结构的文件。本 skill
负责把源文件里新增的中文词条提取出来，同步进中文主文件，并生成/更新对应的多语言
cpp 文件，且**始终保持各语言文件与主文件的条目数、顺序一致（按索引对齐）**。

完整的文件格式、命名约定、提取规则与转义处理见 `references/format.md`，务必在动手前
通读。核心脚本为 `scripts/wika_i18n.py`（仅依赖 Python 标准库）。已确认的术语约定与
实战易错点见 `references/glossary.md`。

## 何时使用

- 用户要求“从某几个文件提取中文词条并翻译到多语言文件”。
- 用户提到 WIKA、LangStr、`FUNC_*.cpp`、`FUNC_ChineseSimp` 等。
- 用户要做界面文案的国际化同步、补译、或新建某种语言文件。

## 工作流（三步）

### 步骤 1 — 明确目标文件（不确定就问）

在动手前，必须向用户确认以下信息；**任一不明确都应主动提问，不要猜测**：

1. **从哪些源文件提取中文词条**：具体文件路径 / 目录。若用户没说清“哪几个文件”，
   立即用 AskUserQuestion 或直接在对话中追问，并说明默认只扫描
   `.cpp/.cc/.cxx/.c/.h/.hpp/.hxx/.ui`。
2. **中文主文件路径**：即当前的 `FUNC_ChineseSimp.cpp`（或等价文件）。
3. **要生成/更新哪些语言**：语言在每次使用时指定（不写死）。需要语言文件列表，
   以及它们的路径。若某语言文件尚不存在，本 skill 会在步骤 3 自动生成。

关键不变量：所有语言文件必须与中文主文件**条目数相同、顺序一致**。任何新增词条
都要“先加中文主文件、再按相同顺序加各语言文件”。详见 `references/format.md`。

### 步骤 2 — 提取有效中文词条

“有效的中文词条”需同时满足：在双引号字符串内、所在行未被注释（`//` 行注释与
`/* */` 块注释都排除，但字符串内的 `//` 不排）、且**未出现在中文主文件**中。

运行扫描（输出为 JSON 数组，便于下一步翻译）：

```bash
python scripts/wika_i18n.py scan \
  --master 中文主文件.cpp \
  --sources 源文件1 源文件2 [目录...] \
  --out new_terms.json
```

- 脚本会自动跳过注释行、跳过主文件里已有的词条、去重，并按首次出现顺序输出。
- 若只是想看结果也可不带 `--out`，直接打印到 stdout。
- 把 `new_terms.json` 交给下一步翻译使用。

### 步骤 3 — 同步中文主文件与多语言文件

对每个目标语言，按“主文件优先、语言文件随后”的顺序操作：

**(a) 先把新增词条写回中文主文件**（保持主文件为唯一真源，避免下次重复提取）：

```bash
python scripts/wika_i18n.py apply-master \
  --master 中文主文件.cpp \
  --terms new_terms.json
```

该操作幂等：已存在的词条不会重复追加。

**(b) 对每个目标语言文件：**

- **文件不存在** → 用更新后的主文件生成全新语言 cpp，需要该语言的**全量译文**
  （JSON：`{中文词条: 译文}`）。未提供译文的词条回退为中文并标 `// UNTRANSLATED`：

  ```bash
  python scripts/wika_i18n.py init-lang \
  --master 中文主文件.cpp \
  --output 语言文件.cpp \
  --translations 该语言全量译文.json
  ```

- **文件已存在** → 只把主文件尾部新增的条目（即本次 new_terms）以译文追加到末尾，
  需要的是**仅本次新增词条**的译文 JSON：

  ```bash
  python scripts/wika_i18n.py add-lang \
    --master 中文主文件.cpp \
    --lang 语言文件.cpp \
    --translations 本次新增词条译文.json
  ```

  `add-lang` 通过“主文件条目数 − 语言文件条目数”确定尾部新增部分，按索引对齐追加，
  幂等；若语言文件条目数反而多于主文件会报错以保护对齐。

**翻译由本 agent 完成**：把 `new_terms.json` 里的中文逐条译成目标语言，写成译文
JSON。翻译时**只翻中文字符**，保留非中文令牌（如 `B1P`、`Y334A`、`(加杆)`、
`\(` 等）原样。领域术语（液压、凿岩、空压机等）尽量准确；不确定处保留中文并加
`// UNTRANSLATED`，便于人工复核。

**英文书写质量规范（硬性，出错会被打回）**：
- 每条英文译文**首字母大写**（句首大写），不得以小写字母开头。
- 电气故障术语必须带连字符：`open-circuit` / `short-circuit`（**禁止** "open circuit" /
  "short circuit"）。
- 译文须符合工程机械专业用词；建议对照已确认的术语表 `references/glossary.md`
  （**本项目备注，非强制默认**）核对，避免译错或不规范。
- 不确定处保留中文并加 `// UNTRANSLATED`，便于人工复核。

**(c) 校验对齐**：所有语言文件处理完后，统一核对条目数：

```bash
python scripts/wika_i18n.py check \
  --master 中文主文件.cpp \
  --langs 语言文件1.cpp 语言文件2.cpp ...
```

任一语言报告 `MISMATCH` 都必须回到对应 `add-lang`/`init-lang` 修正，直至全部 `OK`。

## 注意事项

- 不要在源文件中间插入词条；新增一律追加到各自文件**末尾**，以维护索引对齐。
- 中文主文件路径在步骤 1 必须确认；脚本不会自行猜测主文件。
- 生成的译文 JSON 键必须与主文件里的原始字符串**逐字一致**（含反斜杠等转义），
  否则 `init-lang`/`add-lang` 无法匹配，会回退为中文 + `// UNTRANSLATED`。
- 修改前建议对中文主文件与各语言文件做备份（如复制到副本），本 skill 会直接原地改写。

## 经验教训（实战踩坑）

- **严禁全局 blanket 替换**：如把 `handle` → `joystick` 时，必须**只在中文 key 含
  `手柄` 的条目内**执行，且**保护 `手刹`→handbrake**（不含「手柄」二字，勿误改）。
  `joystick` 与 `handler` 是不同概念：joystick = 主控杆；handler = 紧急/模式切换辅助
  控件（当前项目无明确 handler 词条，见 `references/glossary.md`）。任何字符串级替换都要
  按中文 key 作用域收敛并显式保护例外项。
- **去重会破坏语言文件对齐**：若对中文主文件去重（条目减少），已有的英文文件将失配；
  须用全量译文映射（如 `trans_en.json`，`{中文: 英文}`）配合 `init-lang` **从头重建**
  英文文件，再 `check` 确认 1:1，不要直接 `add-lang`。
- **翻译映射 JSON 本身即真源**：维护一份全量 `trans_en.json`（中文→英文），重生成英文
  文件时统一从这里取，避免译文散落丢失、便于整体重对齐。
- **生成后务必重读实际文件再校验**：脚本输出有缓冲，验证对齐时直接读取刚生成的 cpp
  文件，不要依赖上一步的内存变量，防止误判（如假阳性「仍有残留 handle」）。
- **始终保持 1:1**：任何新增都先加中文主文件、再按相同顺序加语言文件；改完跑 `check`
  直到全部 `OK`。
- 已确认的术语约定与易错点汇总见 `references/glossary.md`。
