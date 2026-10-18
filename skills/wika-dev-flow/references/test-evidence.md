# 测试用例、回归选择与统一证据

用于将可测量的 T 项转换为自动判断、生成测试报告及减少图片回传。主机工具 [flow_tests.py](../scripts/flow_tests.py) 使用 Python 3.8+；仅生成缩略图时需要 Pillow。执行仍复用现有 UI/CAN 工具和现场监督流程，本工具不新增设备启停、总线模式切换或任务调度。

## 用例和执行入口

从 [用例示例](../assets/test-suite.example.json) 按真实协议填写：每项有 `id/requirement/scope/paths/assertions`，基础冒烟项标记 `smoke=true`，公共模块/EDS/数据库等共享依赖列入 `shared_paths`。输入帧/周期、起始页、按下/松开、期望读数/输出帧、超时和恢复条件写入测试文档及执行计划。示例中的 ID/载荷只是已知案例，不能当作其他工程默认协议。

执行与测量的职责：

- UI 导航由 wika-ui-index 生成计划，设备端批量执行并保存每步 guard/目标页结果。导航完成只用于导航测试项；业务数值需实际页面读数、已验证的运行时值读取或人工确认，无法取得时保持未测。
- CAN 由 wika-can-debug 选择内部回环或物理收发。独立 SDK 探针与业务 Qt 程序分开运行，避免争用控制器；页面链路要求在业务程序中注入真实协议帧并检查实际页面。
- 首个项目适配先选择一个明确读数，验证“帧注入→SDK 值→页面值”；再测“真实按下/松开→原发送函数→接收端帧”。通用断言器不会自动推导任意工程的数据换算或执行高副作用按键。
- 采集器按已确认计划读取原始测量，写下面的证据契约；适配器字段映射经原始日志核对后复用。不能把预期值复制为观测值，也不补造缺少的时间戳。

支持三种断言：`equals` 精确比较 JSON 值；`near` 对有限数值按非负容差比较；`frame` 核对十六进制 ID、标准/扩展帧、方向、DLC、全部载荷、验证来源和本轮相对时间窗。`path` 是字典键/数组下标的点分路径，不执行表达式。其他断言需先实现并测试，不把未支持类型判为通过。

## 开发与交付回归

```bash
python3 /path/to/wika-dev-flow/scripts/flow_tests.py select --suite test-suite.json \
    --mode dev --changed Program/某页面.qml --impact Program/关联数据.cpp --output selection.json
python3 /path/to/wika-dev-flow/scripts/flow_tests.py select --suite test-suite.json \
    --mode release --output selection.json
```

开发模式选择依赖命中的项加冒烟；无变更清单、依赖映射不完整、未知变更或公共模块变化则选择完整集。CodeGraph 提供候选影响路径，另核对 qrc/图片、翻译、EDS 和数据库的作用范围。跨页资源与共享组件应加入共享规则，无法确定则扩大测试。

交付模式强制全部 T 项，覆盖本次全部 REQ；完整集指已确认的需求测试集，不自动表示整机所有功能均验收。模式、用例内容和选择结果参与核验；开发通过、历史回放或未测项不能进入交付。

## 证据契约

每轮 `evidence.json` 包含：

```json
{
  "run_id": "tz956e-20261016-01",
  "program_sha256": "实际运行文件的64位SHA256",
  "candidate_id": "本轮manifest.json中的候选ID",
  "suite_id": "flow_tests.canonical(完整suite对象)",
  "execution": "live",
  "sources": {"native": {"path": "native-result.json", "sha256": "原始证据文件SHA256"}},
  "cases": {
    "T-001": {
      "scope": "ui",
      "sources": ["native"],
      "observations": {"target": "menu"},
      "frames": []
    }
  },
  "timings_ms": {"device_execution": 0}
}
```

路径相对证据目录，原始文件和 SHA256 必须实际存在且匹配；同轮观测绑定用例、运行文件和候选。历史材料的执行模式写 `replay`，只验证断言器/回归数据，不产生交付通过标识。计时填实际测量值，未测阶段省略，示例中的 0 仅说明字段类型。

CAN 帧记录形如 `{"id":"18FFABE5","extended":true,"direction":"rx","origin":"sdk_loopback","dlc":8,"data":"1122334455667788","t_ms":200}`。`t_ms` 从同一设备/采集器本轮起点使用单调时钟计算，判定窗对应实际操作；`origin` 与测试 scope 一致。物理接收使用 `physical`，本机回环记录 SDK/原始 socket 来源，不能把本机帧改标为物理收发。缺少时间窗证据的旧记录只回放已有值，不能补造“本轮新帧”。

```bash
python3 /path/to/wika-dev-flow/scripts/flow_tests.py evaluate --suite test-suite.json \
    --selection selection.json --evidence evidence.json \
    --manifest <候选目录>/manifest.json --output test-result.json
python3 /path/to/wika-dev-flow/scripts/flow_tests.py report --result test-result.json \
    --output 自动测试记录.md --update-doc docs/测试文档_本轮.md
```

测试数据缺失为未测，断言失败为未通过；程序/候选、原始证据或用例不匹配则拒绝判定。`passed` 指所选自动项，`release_ready` 还要求绑定候选、live 模式和完整集全通过。人工验收项另留原始证据与明确结果，未接入采集器的项不能靠修改 JSON 标志放行。

报告回填当前模板的七列表格结果栏并保留人工备注，每个 run_id 追加一次记录；定制表格先适配，再检查文档结果。自动判定结果需与截图/业务读数核对，SDK 层通过不能代替页面或物理总线层通过。

## 图片与耗时

```bash
python3 /path/to/wika-dev-flow/scripts/flow_tests.py previews --evidence <原始证据目录> \
    --images 00-main.png 01-menu.png --output <新缩略图目录>
```

生成最大 320×320 JPEG 和 `index.json`，记录原图/缩略图哈希、字节数，不改原图。优先传回 JSON、报告和缩略图；关键验收及失败项通过现有传输工具取原图。界面颜色、字体或细节验收使用原图，不以有损预览替代。

分别计量构建、上传、启动、触摸、页面等待、编码、回传和人工/AI 阅读；设备端已有 `touch_ms/ready_wait_ms/capture_ms` 可直接引用。离线回放时间、图片字节减少比例与端到端现场时间分别报告，未实测不得宣称整体提速。
