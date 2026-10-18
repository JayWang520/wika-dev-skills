# WIKA 翻译术语约定（本项目备注，非强制默认）

> 以下为本次 WIKA **工程机械**项目的**已确认术语约定**，由用户拍板。
> 本文件是 **skill 的参考备注，不是强制默认**：遇到不同项目、或用户另有指定时，以用户为准。
> 翻译新词条时，先把候选译文与此表比对，可省去重复纠结；但凡用户改口，以最新口径为准。

## 1. 英文书写硬性规范

- 每条英文译文**首字母大写**（句首大写），不要以小写字母开头。
- 电气故障术语必须带连字符：`open-circuit` / `short-circuit`（**禁止**写成
  "open circuit" / "short circuit"）。
- 译文只翻中文字符，保留非中文令牌（`Pin209`、`B1P`、`Y334A`、`(加杆)`、`\(` 等）原样不动。

## 2. 已确认术语映射

| 中文 | 英文 | 备注 / 纠偏说明 |
|------|------|----------------|
| 从机组1故障 / 从机组1通讯故障 / 从机组2故障 / 从机组2通讯故障 | Slave Unit 1 Fault / Slave Unit 1 Communication Fault / Slave Unit 2 Fault / Slave Unit 2 Communication Fault | CAN 主从标准术语；用户确认用 Slave（去 slave 化时改 Secondary/Follower） |
| 防冻结传感器故障 / 防冻结传感器保护 | Freeze Protection Sensor Fault / Freeze Protection Sensor Protection | 用户指定（非 Anti-freeze）；注意 "Sensor Protection" 读起来略重复，可接受 |
| 手柄（左手柄/右手柄/转向手柄/铲斗手柄/动臂手柄/工作装置手柄/第三联手柄…） | Joystick | = 主控杆，见第 3 节 |
| 排气温度传感器故障/保护（与压缩机同组） | Discharge Temperature Sensor Fault / Protection | 压缩机冷媒**排温**，用 Discharge，**不是**发动机 Exhaust |
| 回油堵塞 | Return Line Blockage | 液压回油路堵塞，标准说法（非 "Return Oil Blockage"） |
| 液压油温高 | High Hydraulic Oil Temperature | 告警语序规范 |
| 硬线（输入） | Hard-wired Input | 形容词 hard-wired |
| 权限 | Permission | 原译 Jurisdiction（管辖权）错 |
| 注意 | Note | 原译 "Take care" 不规范 |
| 手刹 | handbrake | **注意：不是手柄**，勿被 Joystick 替换误伤 |

## 3. joystick vs handler 区分（重要）

- **joystick = 主控杆**：操作员主操控杆（左/右手柄、转向、铲斗/动臂、工作装置手柄等）
  → 译为 **Joystick**。
- **handler = 辅助控件**：紧急切换 / 模式切换的辅助控件。本项目当前（4181 条）**无明确
  handler 词条**；若后续出现对应中文词（如「切换杆」「模式旋钮」「模式切换手柄」等），
  应译为 **Handler**。
- **执行替换时的铁律**：只对有 `手柄` 二字的 key 做 Joystick 替换；**必须排除 `手刹`→
  handbrake**（不含「手柄」二字，不能被替换）。

## 4. 实战易错点（踩坑记录）

- **去重会破坏语言文件对齐**：对中文主文件去重（条目减少）后，已有的英文文件会失配；
  必须靠全量译文映射（如 `trans_en.json`，`{中文: 英文}`）+ `init-lang` **从头重建**
  英文文件，再 `check` 确认 1:1，不要直接 add-lang。
- **翻译映射 JSON 作真源**：维护一份全量 `trans_en.json`，重生成英文文件时统一从这里取，
  避免译文散落丢失、便于整体重对齐。
- **生成后务必重读实际文件再校验**：脚本输出有缓冲，验证对齐直接读刚生成的 cpp，
  不要依赖上一步内存变量，防止误判「还有残留 handle」之类的假阳性。
- **全局 blanket 替换是大忌**：任何字符串级替换（handle→joystick、lever→joystick 等）
  都要按中文 key 作用域收敛，并显式保护例外项（handbrake）。
