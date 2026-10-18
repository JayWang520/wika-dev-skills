---
name: wika-displayer-online
description: >-
  向 WIKA 显示器设备（ICM7100 / ICM7110 / D3 等嵌入式 Linux 显示控制器）在线运行 Qt 程序。当用户说"向显示器在线运行程序"、"在线运行 Qt"、"部署并运行 CoreApp"、"把程序跑到设备上"、"连设备跑一下" 等，只要涉及把编译好的 Qt 程序（通常是 CoreApp）部署到 WIKA 显示屏并让它显示出来，就用本技能。涵盖：SSH 登录（含 pexpect 处理密码）、按设备型号停止系统自带显示程序（ICM7100/ICM7110: systemctl stop wika*；D3: stop_app.sh）、上传程序、以 eglfs 平台启动、抓帧验证显示。也适用于排查"程序没显示/黑屏/设备重启后程序丢了"等场景。
---

# WIKA 显示器在线运行 Qt 程序

把主机上编译好的 Qt 程序（`CoreApp`）部署到 WIKA 显示设备（i.MX6 平台，armv7l，BusyBox + systemd 嵌入式 Linux）并在其屏幕上运行，带显示验证。

## 设备连接信息（已验证案例）

以下是原现场设备的连接示例。跨工程或换设备时，先读取本工程的 `wika-project.json` 并做 [只读预检查](../wika-dev-flow/references/project-and-release.md)，使用已确认的地址/SSH 配置、服务、运行文件及资源路径。凭据保留在本机 SSH 配置或凭据管理中，工程配置只引用连接入口。

| 项 | 值 |
|---|---|
| 设备地址 | 默认使用本机 SSH 别名 `display`；可用 `WIKA_SSH_HOST` 覆盖 |
| 用户名 | 取 SSH 配置；可用 `WIKA_SSH_USER` 覆盖 |
| 认证 | 优先 SSH 密钥；需要密码时仅在本机设置 `WIKA_SSH_PASSWORD` |
| 部署路径 | `/tmp/CoreApp` |
| 显示平台 | `eglfs`（QPA 插件只有 libqeglfs.so） |
| 主机侧辅助 | 无 sshpass/expect，用 `scripts/ssh_cmd.py`（pexpect）执行远程命令，`scripts/scp_put.py` / `scripts/scp_get.py` 传文件 |

连接信息若失效（密码被改、IP 变动），优先查这台主机 Qt Creator 的 `~/.config/QtProject/qtcreator/devices.xml`（设备名 ICM7100/ICM7110）。

## 识别设备型号（第一步）

登录 banner / `uname -a` / `/etc/hostname` 会给出型号（ICM7100、ICM7110、或 D3 相关）。**停止系统程序的命令按型号分支**：

| 设备 | 停止系统显示程序 | 备注 |
|---|---|---|
| ICM7100（WIKA Display 2.8.x） | `systemctl stop 'wika*'` | wika-app.service / wika-userhelper.service，已验证 |
| ICM7110 | `systemctl stop 'wika*'` | 与 ICM7100 完全相同（用户已确认），未单独实测 |
| D3（wika-d3 SDK 2.9.x） | `stop_app.sh` | 连接参数（IP/密码/部署路径/显示平台）与 ICM7100 相同，仅停止命令不同（用户已确认） |

## 标准流程（以 ICM7100 为例）

### 1. 测试登录

```bash
python3 ~/.agents/skills/wika-displayer-online/scripts/ssh_cmd.py "uname -a"
```
预期输出包含 `armv7l`。失败检查：网络 ping、本机 SSH 配置、主机指纹及认证是否正确。

### 2. 停止系统自带显示程序（每次都要做）

先完成连接/SDK/空间检查，记录原服务和实际运行文件；根据当前设备确认要停止的服务，再执行下列案例命令。

设备重启后 `wika-app.service` 会自启动并占用显示，不先停掉会抢占屏幕。

```bash
python3 ~/.agents/skills/wika-displayer-online/scripts/ssh_cmd.py "systemctl stop 'wika*'; systemctl list-units | grep -iE 'wika-app|wika-userhelper'"
```
确认目标服务已停止且原显示进程退出；正常停止通常为 `inactive`，`failed` 应检查原因。D3 设备用 `stop_app.sh` 替代。

### 3. 检查并上传程序

使用本轮冻结候选中的最终运行文件；EDS/.h/.var 按启用通道与实际加载路径逐文件核对，缺失或不匹配时备份后成套同步，匹配时保留。数据库按配置中的保留/迁移/初始化策略处理，logo 等资源按需求同步。程序、EDS 和默认数据库的处理策略分别判断。

`/tmp` 是内存盘（tmpfs），**设备一重启程序文件就没了**，必须重新上传。流程：

```bash
# 3a. 看设备上有没有、md5 对不对（本机 BIN/CoreApp 与设备 /tmp/CoreApp 比较）
md5sum ~/Displayer/*/*/*/BIN/CoreApp   # 按实际项目路径
python3 ~/.agents/skills/wika-displayer-online/scripts/ssh_cmd.py "md5sum /tmp/CoreApp 2>/dev/null; ls -la /tmp/CoreApp 2>/dev/null"

# 3b. 不一致或不存在 → 上传
python3 ~/.agents/skills/wika-displayer-online/scripts/scp_put.py <本机BIN/CoreApp绝对路径> /tmp/CoreApp
python3 ~/.agents/skills/wika-displayer-online/scripts/ssh_cmd.py "chmod +x /tmp/CoreApp; md5sum /tmp/CoreApp"
```

先找本机的程序文件：项目 `Program` 目录的上一级 `BIN/`（qmake 的 `DESTDIR=../BIN`，最终产物 `CoreApp`，约 35MB）。

### 4. 启动程序

必须在 `/apps` 目录下运行（程序按绝对路径读 `/apps/msyh.ttc` 等资源，但日志/数据库依赖工作目录）：

```bash
python3 ~/.agents/skills/wika-displayer-online/scripts/ssh_cmd.py "cd /apps && QT_QPA_PLATFORM=eglfs setsid nohup /tmp/CoreApp >/tmp/coreapp.log 2>&1 < /dev/null & sleep 12; ps aux | grep -iE 'coreapp' | grep -v grep; tail -5 /tmp/coreapp.log"
```

要点（都是踩过坑验证过的）：
- 平台必须 `QT_QPA_PLATFORM=eglfs`：设备 QPA 插件只有 `libqeglfs.so`（Vivante GPU），无 linuxfb。渲染走 `/dev/galcore`，`/dev/fb0` 是最终画面。
- `setsid nohup ... &` 保证 SSH 断开后进程继续跑。
- 程序内 `WikaLib::my_sys_lcd_rotation(270)` 已处理旋转，不要在命令行重复设。
- 日志里 `qrc:...: Unable to assign [undefined] to ...`、`FindUSBandParseXlsx 452` 是程序固有无害警告，不是启动失败。

### 5. 验证显示（抓帧）

先检测 framebuffer 实际宽高、stride、通道和触摸节点；下方是历史 `1280×960 BGRA` 案例，不能直接套用于其他设备。ICM7100 的已适配 ABI 可复用 [批量测试读取器](../wika-dev-flow/references/ui-batch-test.md) 获取实际参数和原始 PNG。非黑比例只作启动粗查，验收须核对预期页面、内容及运行程序身份。

```bash
# 5a. 设备端抓 framebuffer
python3 ~/.agents/skills/wika-displayer-online/scripts/ssh_cmd.py "dd if=/dev/fb0 of=/tmp/fb0.raw bs=4096 count=1200 2>/dev/null"
# 5b. 拉回本机
python3 ~/.agents/skills/wika-displayer-online/scripts/scp_get.py /tmp/fb0.raw /tmp/fb0.raw
# 5c. 分析（见下面 python 片段）：非黑比例高 + ASCII 预览有结构 = 界面已显示
```

分析 snippet（PIL 把 raw 转预览）：

```python
from PIL import Image
data = open('/tmp/fb0.raw','rb').read()          # 1280x960 BGRA, 4915200 字节
img = Image.frombytes('RGBA', (1280,960), data, 'raw', 'BGRA').convert('RGB')
nz = sum(1 for p in list(img.resize((256,192)).getdata()) if p != (0,0,0))
print(f'非黑像素比例: {nz/(256*192)*100:.1f}%')   # UI 正常时约 60%，全黑=0%
small = img.resize((100,45)); px = small.load()
chars = ' .:-=+*#%@'
for y in range(45):
    print(''.join(chars[min((px[x,y][0]*299+px[x,y][1]*587+px[x,y][2]*114)//1000*len(chars)//256, len(chars)-1)] for x in range(100)))
```

界面结构特征（判别用）：顶部一行文字 + 中部对称仪表盘/图标区 + 底部一条状态栏/按钮带。纯噪声（花屏）没有这种规律结构。

### 6. 连续界面操作与验证

需要从源码计算触摸区域、按名称查找按钮或生成页面导航路线时，先调用 [wika-ui-index](../wika-ui-index/SKILL.md)。已有计划先检查版本和索引新鲜度，再进入下述设备端执行。

已知导航路径的切页、按键与抓屏测试，读取 [设备端批量操作与页面就绪检测](../wika-dev-flow/references/ui-batch-test.md)，复用其中的设备端脚本。将操作序列一次下发到设备，每步检查目标页就绪后继续，按测试项保存截图与结果；未知页面先单步确认。页面识别成功后，业务读数和 CAN 结果仍按各自测试项验证。

## 注意事项（血泪教训）

- **现场数据单独处理**：`/apps/Database.db`、`/apps/data/*.dat` 按保留/迁移/初始化策略执行，迁移或初始化前备份；运行数据库与默认数据库不要求字节相同。EDS/.h/.var 按上述一致性检查成套同步，不能用保留现场数据作为保留过期 EDS 的理由。
- 字体、logo 等资源按当前候选清单核对，未变且匹配时复用；资源目录由当前工程确认。
- 二次启动前确认旧进程已死：`killall -9 CoreApp`。
- 程序动态依赖（libhsm.so、Qt5、libGAL/libVSC）都在设备 `/usr/lib`，`LD_LIBRARY_PATH` 系统已配好，不需要额外处理；异常时用 `ldd /tmp/CoreApp` 排查。
- 设备重启后：wika 服务自启动 + /tmp 程序丢失，两步都要重做（第 2、3 步）。
- 若 `systemctl stop 'wika*'` 报错或服务名不同，先 `systemctl list-units | grep -iE 'wika|app'` 看实际服务名再停，别盲停 dev-mgmt / otaupdate（系统管理服务，停错了设备管理会挂）。

## 参考脚本

- `scripts/ssh_cmd.py <命令>` — pexpect SSH 执行远程命令（从本机 SSH 配置/环境读取认证，不内置密码）
- `scripts/scp_put.py <本地路径> <设备路径>` — 上传
- `scripts/scp_get.py <设备路径> <本地路径>` — 下载

## 导出包配置

本包的联机脚本默认使用 SSH 别名 `display`，主机和用户名可由 `WIKA_SSH_HOST`、`WIKA_SSH_USER` 覆盖。优先使用已核对主机指纹的 SSH 密钥连接；密码只通过本机环境变量提供，不写入技能。主机身份校验已启用，SSH/SCP 非零状态和超时会返回失败。安装方式和通用依赖见压缩包根目录的安装说明。
