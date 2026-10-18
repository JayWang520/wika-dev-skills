---
name: wika-build
description: 编译 WIKA 显示器 Qt 工程（SDC190H、SDC150e、SDC170_X12、UL100E 等 /home/ubuntu/Displayer 下的项目），交叉编译出 ARM 程序。当用户说"编译一下"、"构建程序"、"重新编译"、"build 一下"、"编译报错了帮我看看"，或涉及 qmake/make/wika-display SDK 交叉编译时使用。涵盖：SDK 位置（/opt/wika-display）、增量编译（直接 make）、全新构建（qmake 配置）、产物输出路径（工程 BIN/）、常见编译问题。
---

# WIKA 显示器 Qt 工程交叉编译

主机上交叉编译 WIKA 显示器（i.MX6 Cortex-A9）Qt 程序，产物落到工程 `BIN/` 目录。

## 工程与 SDK 布局

- 工程根：`/home/ubuntu/Displayer/<厂商>/<型号>/`，如 `/home/ubuntu/Displayer/LGMRT/SDC190H/`
  - `Program/` — 源码（.cpp/.h/.qml + `<型号>.pro`）
  - `build-<型号>-IMX6-Release/` — 构建目录（含已生成 Makefile）
  - `BIN/` — 产物输出（.pro 里 `DESTDIR = ../BIN` 硬编码，命令行覆盖无效）
- SDK：`/opt/wika-display/<版本>/`（SDC190H 用 2.8.13；另有 2.9.1）
  - qmake：`/opt/wika-display/2.8.13/sysroots/x86_64-pokysdk-linux/usr/bin/qmake`
  - 交叉 g++：`.../usr/bin/arm-poky-linux-gnueabi/arm-poky-linux-gnueabi-g++`
  - 目标 sysroot：`.../sysroots/cortexa9t2hf-neon-poky-linux-gnueabi`

## 编译流程

跨工程优先使用已确认的 `wika-project.json`，按 [工程配置与产物冻结](../wika-dev-flow/references/project-and-release.md) 发现构建入口、读取既有 Makefile/Qt Creator Kit 并预检查。多个工程或 SDK 候选须先选定，不按目录名猜测。已适配脚本入口：

```bash
python3 /path/to/wika-build/scripts/build.py <工程根> --profile <工程根>/wika-project.json
```

配置里的 `build.sdk_env` 在每条构建命令前加载，适用于 PKGCONFIG/PATH 依赖；完整日志与真实退出码写入所选构建目录的 `build.log`、`build-result.json`。配置构建入口需要同批提供 `wika-dev-flow/scripts/flow_artifacts.py`。

### 增量编译（日常，首选）

先检查 Makefile 的工具链路径及当前 PATH；CC/CXX 等使用裸命令名且 PATH 未包含 SDK，或工程有 PKGCONFIG 依赖时，先加载对应 SDK 环境。已确认工具链可用时执行：

```bash
cd /home/ubuntu/Displayer/LGMRT/SDC190H/build-SDC190H-IMX6-Release
make -j$(nproc) >build.log 2>&1
task_build_rc=$?
tail -30 build.log
test "$task_build_rc" -eq 0
```

- 若 `.pro` 里有 `PKGCONFIG = ...`（如 D170H 的 `gstreamer-1.0`），**必须先 source SDK 环境**再跑 qmake/make——主机没装 pkg-config，qmake 会报 `Project ERROR: gstreamer-1.0 development package not found`（库其实都在 SDK sysroot 里）：

```bash
source /opt/wika-display/2.8.13/environment-setup-cortexa9t2hf-neon-poky-linux-gnueabi
```

- 使用脚本配置入口时将 `build.sdk_env` 指向实际 SDK 环境脚本；旧的无配置入口仍需先手动加载所需 SDK 环境。

- 保存完整输出后查看尾部及错误位置；构建通过以 qmake/make 真实退出码为准，错误文字计数仅作诊断。采用管道时显式保留构建命令状态，避免取得 tail/tee 的退出码。
- 编译成功后再跑一次 `make`，提示 `对 "first" 无需做任何事` 即干净收尾。
- 产物：`BIN/SDC190H`（ARM 32-bit ELF）。**每次链接二进制都会变**（BuildID/debug_info），即使代码未改——不要用整个文件 md5 判断是否为同一份代码。

### 全新构建（构建目录不存在 / .pro 改了 / 清理后）

```bash
mkdir -p /home/ubuntu/Displayer/LGMRT/SDC190H/build-SDC190H-IMX6-Release
cd /home/ubuntu/Displayer/LGMRT/SDC190H/build-SDC190H-IMX6-Release
/opt/wika-display/2.8.13/sysroots/x86_64-pokysdk-linux/usr/bin/qmake -o Makefile \
    ../Program/SDC190H.pro -spec devices/linux-oe-generic-g++ "CONFIG+=qtquickcompiler"
make -j$(nproc) >build.log 2>&1
task_build_rc=$?
tail -30 build.log
test "$task_build_rc" -eq 0
```

或直接用现成脚本（自动找 .pro、选 SDK、增量/全新自适应）：

```bash
python3 ~/.agents/skills/wika-build/scripts/build.py /home/ubuntu/Displayer/LGMRT/SDC190H
# 可选: --clean 全新配置; --sdk 2.9.1 指定其他 SDK 版本
```

注意：qmake 需在构建目录里执行，`.pro` 用相对路径 `../Program/SDC190H.pro` 引用；脚本内部已按此处理。全新构建约 3~5 分钟（几百个编译单元，-j 并行）。

### 编译后验证（必做）

1. 产物存在且是 ARM：`file BIN/SDC190H` → `ELF 32-bit LSB pie executable, ARM`
2. 版本串编入：`strings -e l -a BIN/SDC190H | grep LGMRT_SDC190H`（版本号在 `Program/DTForm/Form_Ver.qml` 硬编码，改版本号见 [[sdc190h-display-version-string]]）
3. qmake/make 的真实退出码均为 0；收尾重跑 make 也检查退出码。旧产物存在或没有 `error:` 字样不替代成功构建。
4. 最终版本在编译前确定。最终运行文件若需 strip 等处理，在冻结前完成并重新记录该文件哈希；按主流程保存候选快照，测试与打包复用同一文件。

## 常见问题

| 现象 | 处理 |
|---|---|
| `qmake: command not found` | 用绝对路径调 qmake，不要依赖 PATH |
| 改了 .pro / .qrc 但 make 没反应 | 重新跑 qmake 命令重新生成 Makefile（或 build.py --clean） |
| `DESTDIR+=...` 不生效 | `.pro` 内 `DESTDIR = ../BIN` 是赋值，产物固定写工程 `BIN/`，在临时目录构建也会写到那里 |
| 大量 warning | 区分已有与新增警告，检查与本轮改动相关的警告；构建状态以真实退出码判定 |
| `cannot find -lhsm` 等 SDK 库缺失 | 确认 SDK 版本目录存在（`ls /opt/wika-display/`），SDC190H 用 2.8.13 |
| `Project ERROR: xxx development package not found`（如 gstreamer-1.0） | `.pro` 有 `PKGCONFIG` 依赖且主机无 pkg-config：source SDK 环境脚本后重新 qmake + make（2026-09-10 D170H4_10inch 实测解决） |
| qmake WARNING: `Failure to find: xxx.h` | .pro HEADERS 列表引用了不存在的文件（常见：大小写不符——Windows 不分大小写 Linux 分；文件名带空格；文件已删除）。只是警告不阻断编译，除非 .cpp 真 include 了它 |
| 部署/烧录 | 见 [[wika-app-package]]（打 .app 升级包）或 [[wika-displayer-online]]（SSH 到设备直接运行） |

## 编译 + 打包一条龙

编译通过后接着打升级包：

```bash
python3 ~/.agents/skills/wika-build/scripts/build.py <工程根> && \
python3 ~/.agents/skills/wika-app-package/scripts/make_userapp_zip.py <载荷目录> <zip> && \
python3 ~/.agents/skills/wika-app-package/scripts/build_app.py --zip <zip> --date YYYYMMDD \
    -o <输出.app>
```

上例仅是构建/制包命令串；交付仍须先通过同一候选的完整需求验收，再运行 `verify_app.py --manifest <候选>/manifest.json` 校验载荷，不能用命令串替代测试门禁。

## 已验证实例

2026-09-02 SDC190H：增量编译与全新构建（临时目录）均通过，产物为 ARM ELF 且含 `LGMRT_SDC190H_v1.01_Build20260902` 版本串；build.py 增量与 --clean 两路径实测通过。

2026-09-10 D170H4_10inch（`/home/ubuntu/Displayer/XGZZL/D170H_PROJ_V1.62`）：.pro 含 `PKGCONFIG = gstreamer-1.0`，source SDK 2.8.13 环境后 qmake + make -j 全新构建通过（~530 个编译单元），0 error，产物 `BIN/D170H4_10inch` ARM ELF；重跑 make `Nothing to be done` 干净收尾。.pro 中 4 条失效 HEADERS 引用（Form_VibrationTest.h / button 大小写 / Can1HeadRegrist 带空格 / BData_LubSystemParam.h）仅产生 WARNING，不影响编译。
