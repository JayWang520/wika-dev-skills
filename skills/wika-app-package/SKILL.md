---
name: wika-app-package
description: 把 WIKA 显示器（ICM7100/ICM7110/D3、SDC190H 等）编译好的 Qt 程序打包为 .app 升级包（HIRSCHMANNIMAGE 格式）。当用户说"打包程序"、"打个包"、"打包成 app"、"生成升级包"、"用 ServicesTool 打包"、"出个升级文件"，或涉及 mgmt-tool / ServicesTool / HIRSCHMANNIMAGE / .app 升级文件时使用。涵盖：mgmt-tool CLI 参数（可能挂 GUI，也可能不写产物）、userapp.zip 载荷制作（带 / 前缀文件名）、TLV 头格式细节（含已逆向验证的 MD5 算法）、产物结构校验。
---

# WIKA 显示器 .app 升级包打包

把主机上编译好的 Qt 程序 + 配置文件打包成 `.app` 升级文件（HIRSCHMANNIMAGE 格式），可用 ServicesTool 或设备端升级流程烧录。

## 工具位置

```
/home/ubuntu/桌面/921342-X603_SBP_ServicesTool_V1.5.11_linux/mgmt-tool
```

（`~/桌面/package` 是它的符号链接。工具是 Qt GUI 程序，只有 xcb 平台插件，需要 `DISPLAY=:0`。）

## 关键经验（先读这个，能少走弯路）

1. **首选 `build_app.py` 脚本制包**，再校验结构与载荷。mgmt-tool 作为对照或设备特定需求的辅助路径；其 GUI 事件循环可能不退出，也可能不写产物，不能仅凭超时判定成功或失败，不反复等待 GUI。
2. **`-v`/`-V` 校验模式同样挂 GUI**，无法脚本化；校验用 `scripts/verify_app.py`（完整解析 TLV + zip CRC + 载荷比对）。
3. **zip 载荷内的文件名必须带前导 `/`**（如 `/myapp`、`/app.info`，设备端按绝对路径解压）。python `zipfile.write()` 会自动剥掉前导 `/`，必须用 `ZipInfo` 手工写（scripts/make_userapp_zip.py 已处理）。
4. **`.app` 格式已完全逆向**（magic + TLV 链 + zip + MD5 算法，见下），工具不可用时可用 `scripts/build_app.py` 直接构造。**build_app.py 产物已被设备端实机验证**（2026-09-03 V1.03 包正常烧录），自算 MD5 算法正确，可放心作为首选打包路径。
5. **BIN/SDC190H 每次重新链接二进制都会变**（构建 ID/debug_info），打包前确认用的是最新编译产物，校验时 `--bin-dir` 指向当时的 BIN。

## .app 文件格式（HIRSCHMANNIMAGE）

```
偏移 0x00: magic 16B  "HIRSCHMANNIMAGE\0"
偏移 0x10: MD5 record（固定在这里）: tag(16B) + len(16B, ASCII 十进制) + value(32B hex 字符串)
偏移 0x50: 后续 record 链，每条: tag(16B, \0 填充) + len(16B, ASCII 十进制 \0 填充) + value(len 字节)
           无对齐 padding，record 紧密相连，链走到 EOF。
```

SDC190H 实际 record 集合（V1.00/V1.01 包实测一致）：

| tag | value 示例 | 说明 |
|---|---|---|
| MD5 | `e7474b86...`（32B hex） | **算法已逆向且实机验证（2026-09-03，V1.03 包设备端烧录通过）：`MD5 = md5(magic[0x00..0x10] + 偏移 0x50 起到 EOF 的全部字节)`**，即 MD5 值本身不参与摘要。build_app.py 已自算，无需复制旧包值 |
| PRODUCT | `*\0` | 型号通配 |
| MODEL | `*\0` | |
| BOARD | `*\0` | |
| APP_VER | `1.0.0\0` | 包格式版本，不是产品版本号，保持 1.0.0 |
| DATE | `20260902\0` | 构建日期 YYYYMMDD |
| OEM | `XCMG\0` | |
| USERAPP | zip 原始字节 | 升级载荷，延伸到文件尾 |

解析参考实现（也是 verify_app.py 的逻辑）：

```python
assert data[:16] == b'HIRSCHMANNIMAGE\x00'
md5 = data[0x30:0x50]           # MD5 record value 固定位置
pos = 0x50
while pos < len(data):
    tag = data[pos:pos+16].split(b'\0')[0].decode()
    ln  = int(data[pos+16:pos+32].replace(b'\0', b''))
    val = data[pos+32:pos+32+ln]
    pos += 32 + ln              # tag16 + len16 + value
    if tag == 'USERAPP': break
```

## USERAPP zip 内容清单（SDC190H）

| zip 内文件名 | 来源 | 说明 |
|---|---|---|
| `/myapp` | `BIN/SDC190H` | 新编译的主程序（ARM） |
| `/Database.db` | `BIN/Database.db` | 数据库 |
| `/can0.eds` `/can0.h` `/can0.var` | `BIN/` | CAN 配置 |
| `/logo.bin` | `BIN/logo.bin` | 开机 logo |
| `/app.info` | 手工生成 | 4 行见下 |

`/app.info` 内容（appdate 同 .app 头的 DATE）：

```
appname=myapp
appversion=1.0.0
appdate=20260902
enable_cursor=0
```

## 标准流程

### 1. 准备载荷目录

从通过验收的候选快照准备载荷，保持程序和配置字节不变。`BIN` 与快照逐文件核对，最终版本串已在编译前确定；若重编或改最终版本，回编译/测试阶段。多工程的程序名与启用通道来自工程配置，下面的 SDC190H 文件名仅为案例。默认数据库与现场运行数据库按保留/迁移/初始化策略分别处理。

```bash
mkdir -p /tmp/sdc190h_pkg
cp BIN/SDC190H /tmp/sdc190h_pkg/myapp
cp BIN/Database.db BIN/can0.eds BIN/can0.h BIN/can0.var BIN/logo.bin /tmp/sdc190h_pkg/
printf 'appname=myapp\nappversion=1.0.0\nappdate=20260902\nenable_cursor=0\n' > /tmp/sdc190h_pkg/app.info
```

### 2. 制作 zip（文件名自动带 `/` 前缀）

```bash
python3 ~/.agents/skills/wika-app-package/scripts/make_userapp_zip.py \
    /tmp/sdc190h_pkg /tmp/sdc190h_userapp.zip
```

### 3a. 首选：脚本制包

```bash
python3 /path/to/wika-app-package/scripts/build_app.py \
    --zip /tmp/sdc190h_userapp.zip --date 20260902 \
    -o SDC190H_V1.01.app
```

脚本按已验证算法自算 MD5。普通新版本无需提供参考包；`--check-md5` 仅适用于预期载荷相同的对照包，不复制旧包摘要。脚本默认元数据为 SDC190H 惯例，其他产品先核对 PRODUCT/MODEL/BOARD/OEM 要求。

### 3b. 可选：mgmt-tool 对照

```bash
export DISPLAY=:0
timeout 20 /path/to/mgmt-tool \
    -P '*' -M '*' -B '*' -A 1.0.0 -D 20260902 -O XCMG \
    -a /tmp/sdc190h_userapp.zip -o /tmp/SDC190H_V1.01.app >log.txt 2>&1
```

不论 GUI 是否退出，都检查输出文件并执行下述校验。未生成产物时回到脚本路径。

### 4. 校验产物（必做，两个路径产物都校验）

```bash
python3 /path/to/wika-app-package/scripts/verify_app.py \
    SDC190H_V1.01.app --bin-dir <候选目录>/payload --program myapp \
    --manifest <候选目录>/manifest.json
```

校验项：magic、实际 MD5 摘要、TLV 边界/必需记录、ZIP CRC/重复成员、app.info 名称/日期，以及全部候选文件哈希和本地载荷字节，最后打印 `VERIFY PASS`。缺文件不跳过，程序名有歧义时显式指定 `--program`。没有冻结清单时结构检查不等于交付验收；任何一步失败都不要交付。

### 5. 命名与发布

产品包命名 `SDC190H_V<pkg_ver>.app` 或 `LGMRT_SDC190H_V<pkg_ver>_Build<date>.app`（跟随用户要求）。按需拷贝到 `/media/sf_Share/SDC190H/`（注意：共享目录文件会被亿赛通加密，见 [[esafenet-share-decrypt]]，主机侧先留一份明文）。

## 已验证实例

2026-09-02 `SDC190H_V1.01.app`（V1.01_Build20260902 程序，10.3 MB）：mgmt-tool 打包产物与 build_app.py 直构产物逐字节一致，verify 全过。

2026-09-03 V1.02 重打包：mgmt-tool 本次完全不写产物（两次 20s/60s/90s 均无输出文件，日志止于 GUI 初始化），build_app.py 自算 MD5（`md5(magic+0x50..EOF)`，对 V1.00/V1.01/SDC190H_V1.01 三个工具包回验全命中）产出 `LGMRT_SDC190H_V1.02_Build20260903.app`，verify PASS。

2026-09-03 **实机验证通过**：`LGMRT_SDC190H_V1.03_Build20260903.app`（build_app.py 直构、自算 MD5）在设备端正常烧录安装。打包环节（含 MD5 算法）自此确认无误；build_app.py 为可信首选路径。
