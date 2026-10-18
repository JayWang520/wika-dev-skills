# 工程配置、预检查与候选冻结

用于首次接入工程、换编译电脑/设备、冻结测试文件及交付前核对。工具 [flow_artifacts.py](../scripts/flow_artifacts.py) 使用主机 Python 3.8+ 标准库；在能读取源码、SDK 和构建目录的主机运行。当前自动发现适配 qmake 工程，CMake 等入口另行适配，不猜测构建命令。

## 首次配置

```bash
python3 /path/to/wika-dev-flow/scripts/flow_artifacts.py discover <工程根>
python3 /path/to/wika-dev-flow/scripts/flow_artifacts.py init <工程根> --output <工程根>/wika-project.json
```

多 `.pro` 时加 `--pro Program/目标.pro`；多构建目录或 SDK 时保留候选，结合既有 Makefile、Qt Creator Kit 及工程说明选定。初始化保留 `confirmed=false`，不覆盖已有文件。参考 [配置示例](../assets/project-profile.example.json) 核对后设为 true：

- `pro`、`build.directory` 和 `artifact.executable` 均相对工程根；SDK 的 qmake/环境脚本使用所选编译电脑的绝对路径。配置不包含密码或私钥内容。
- `artifact.version` 是本轮最终版本串，编译前在真实源码入口更新。`artifact.payload` 明确包内绝对文件名与 BIN 来源，`/myapp` 对应最终运行文件；启用通道各包含 EDS/H/VAR。仅列实际使用的资源。
- `source_roots` 覆盖源码、qrc/图片、协议/翻译等构建输入；目录扫描排除根目录 BIN/build-* 和运行记录。参与编译的生成头文件可显式列为文件项（如 `BIN/can0.h`），此时纳入构建输入核对。工程外依赖需要另外记录版本，当前工具不会自动发现所有编译依赖。
- `device.ssh` 是当前构建主机到显示器的 SSH 参数数组，引用已验证的主机密钥和本机密钥文件；不要禁用主机身份检查。`service/executable/resource_dir/touch` 用实机值，不跨工程照搬。
- `database_policy` 为 preserve/migrate/initialize，记录选择不等于执行迁移。迁移/初始化流程按本轮需求设计、备份并验收；现场运行数据库不与默认数据库做盲目哈希同步。

## 每轮只读预检查

```bash
python3 /path/to/wika-dev-flow/scripts/flow_artifacts.py preflight <工程根> --device --output preflight.json
```

检查配置确认状态、工程/构建目录、qmake、环境脚本、make、空间及 SSH；设备探测只读服务/MainPID、实际运行文件哈希、资源哈希、framebuffer 参数与触摸设备。先在 Windows 复用既有连接确认构建主机可达，再在构建主机运行此命令。离线只检查构建环境时省略 `--device`，报告不表示设备已验证。

可达与目标程序身份分开判断：设备当前运行旧版可能是正常基线，部署后须再次比较本轮候选。虚拟 framebuffer 高度可能包含双缓冲，实际画面尺寸取 ioctl 的可见分辨率。触摸、旋转和执行器 ABI 仍按 UI 技能校准，预检查不自动认定所有机型已适配。

## 构建和冻结

```bash
python3 /path/to/wika-build/scripts/build.py <工程根> --profile <工程根>/wika-project.json
python3 /path/to/wika-dev-flow/scripts/flow_artifacts.py freeze <工程根> \
    --build-result <构建目录>/build-result.json --snapshot <工程根>/.wika-flow/<本轮候选>
```

构建脚本记录真实命令退出码、完整日志、构建前后输入快照、配置、qmake/SDK 环境脚本和程序哈希。最终 ELF/版本检查通过才标成功。需要 strip 的工程先让已有构建规则完成处理，再将 `artifact.executable` 指向最终运行文件；未纳入构建规则的后处理先适配，不手改成功记录中的哈希。当前脚本不自动 strip，也不计算整个 sysroot 的指纹，编译器/系统库变更仍需记录 SDK 版本并重新构建验收。

冻结保存 `payload/` 和 `manifest.json`，候选 ID 绑定版本、源码、工程配置、程序及全部配套文件。失败构建、旧构建结果、构建后输入/SDK 配置变化、错误 ABI、缺少版本串和 EDS 配套文件均拒绝冻结；已有候选目录不覆盖。文件指纹用于本轮产物身份，另一次重链接产生不同指纹时建立新候选。

```bash
python3 /path/to/wika-dev-flow/scripts/flow_artifacts.py verify <工程根> \
    --snapshot <候选目录> --runtime runtime.json --test-result test-result.json
```

`runtime.json` 使用预检查输出中的 `runtime` 对象，或由测试现场采集等价字段：`program_sha256` 为实际 `/proc/<pid>/exe` 哈希，`resource_sha256` 以 `/can0.eds` 等包内名为键，值来自真实加载文件。测试期采集并保存，恢复原程序后的预检查不能充当候选运行证据。该命令比较候选、当前源码/配置、BIN、运行文件/EDS/资源，以及同一候选的完整 live 交付测试结果。省略 runtime 或 test-result 只能核对所提供部分，不能据此宣布可交付。

## 打包与最终核对

从候选 `payload/` 拷贝工作载荷，按产品要求生成 `app.info`；程序/EDS/默认数据库/logo 不变。默认使用脚本 `build_app.py`，按 [wika-app-package](../../wika-app-package/SKILL.md) 生成包，再执行：

```bash
python3 /path/to/wika-app-package/scripts/verify_app.py <测试包.app> \
    --bin-dir <候选目录>/payload --program myapp --manifest <候选目录>/manifest.json
```

核对包摘要、结构、全部冻结文件及本地载荷。候选清单和完整测试结果属于交付证据，`.app` 结构正确不替代安装/启动或业务验收。因升级方式、数据库结构变化而增加的安装/重启测试需列为 T 项。
