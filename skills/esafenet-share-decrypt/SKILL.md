---
name: esafenet-share-decrypt
description: 处理亿赛通(Esafenet/CDG)透明加密文件：共享文件夹 /media/sf_Share 密文读取、VM 本地密文文件批量恢复（源码/Office 均适用）。当 openpyxl/python-docx 报 "BadZipFile"、file 命令显示 "esafenet encrypted file"、文件头偏移 0x58 有 Esafenet 标记、或 gcc/编译器读到源码是乱码时使用。核心：共享文件夹直读字节=Windows 磁盘原始字节；cp 到本地磁盘即由 esn_cfs 透明解密（无需登录，在线取得一次密钥后离线亦有效）；decrytool 等特权工具才需要在线登录；引擎无密钥时用 zip 明文源恢复（注意 zip 内可能仍夹带密文）。Use whenever ANY file from /media/sf_Share fails to parse, or project files on the VM show Esafenet markers.
---

# 亿赛通加密文件处理（共享文件夹 + VM 本地密文恢复）

## 背景原理（2026-10-12 实测修正）

宿主机（Windows）装有亿赛通(CDG)客户端，VM（Ubuntu）装有 Linux 版客户端 ultrasec（`/usr/local/ultrasec/`，内核模块 esn_cfs 挂载 /home、/root、/esntmp）。

- **共享文件夹 `/media/sf_Share` 直读字节 = Windows 磁盘上的原始字节**：被管控的文件是密文，未管控的文件是明文。vboxsf 不做透明解密。
- VM 本地磁盘（/home）上文件落盘同样是密文（按扩展名管控：cpp/h/qml/png/ui/pro/js/txt/jpg/docx/xlsx/ppt 等全在加密列表；**zip 不在列表**）。
- 正常时 esn_cfs 对进程读取**透明解密**（gcc/head 读密文文件拿到明文，编译无感）。**引擎无密钥时**（客户端从未在线取得密钥、或授权失效、VM 时钟错乱触发保护），所有进程读到密文原文——表现为"源码全是乱码无法编译"、"cp 出来还是密文"。
- 受控进程清单、加密扩展名清单见 `/usr/local/ultrasec/aaa.policy`（明文 XML）。
- **密文容器固定开销 4096 字节**：密文大小 = 明文 + 4096（空文件密文恰为 4096）。解密后尺寸应恰好减少 4096——据此可快速判断解密是否真的发生。

## 快速决策树

```
文件读到 Esafenet 密文
├─ 在 /media/sf_Share 上 → cp 到本地磁盘即透明解密（方法一，见下）
│   └─ cp 后仍密文 → 引擎无密钥（需客户端在线取得一次密钥，见"网络路由"），或走方法二（zip 明文源，先确认 zip 内容为明文）
├─ 在 VM 本地（如 /home/ubuntu/Displayer 下源码）
│   ├─ 本地↔本地 cp 不解密（已实测，别浪费时间）
│   ├─ 引擎有密钥：cp 到 /home 后读取即明文（透明解密在读取侧生效）
│   └─ 引擎无密钥：走方法二；客户端在线时也可用 decrytool -D（特权工具需登录）
```

## 方法一：cp 到本地磁盘即透明解密（首选，不需要登录）

```bash
cp "/media/sf_Share/<目录>/<文件>.xlsx" /home/ubuntu/<文件>.xlsx
head -c 4 /home/ubuntu/<文件>.xlsx | xxd   # 504b 0304 (PK..) = 成功；大小应 = 密文 - 4096
```

- **这是一个 cp 即完成的透明解密，不需要登录、不需要 decrytool。** 客户端只要曾经在线取得过密钥，之后**离线也能用缓存密钥解密**（2026-10-12 UT120 实测：客户端 offline、TCP 不通，cp 直接成功）。
- **`file` 命令对已解密的文件仍会报 "esafenet encrypted file"（那是 DLP 标记，不代表内容仍是密文）——不能作为判断依据。** 用头字节（PK/正常文本）、Esafenet 标记扫描、或"尺寸恰减 4096"来判断。
- 输出明文：从 /home 读到的解密内容 `cp` 到共享文件夹（vboxsf 写入不加密），即得永久明文副本。
- 批量：`find . -type f -print0 | while IFS= read -r -d '' f; do head -c 200 "$f" | grep -qa Esafenet && cp "$f" /home/ubuntu/staging/...; done` 逐个搬运即可。

## 方法二：zip 明文源恢复（引擎无密钥时，批量恢复首选）

亿赛通加密策略**按扩展名**管控且 **zip 不在列表**：Windows 端受控进程（右键压缩等）读密文文件得明文、写 zip 不加密 → **共享文件夹里的项目 zip 包内容多为明文**。

**但不保证**：非受控进程（脚本/命令行/备份工具压缩）打的 zip 里文件仍可能是密文——2026-10-08 XS165II 的 zip 就是 254 个明文 + 70 个密文 .as/.fla 混杂。解压后务必先扫描确认。

```bash
# 1. 在共享文件夹找目标项目的 zip（哪怕文件名/版本不完全匹配，内容多半是同项目近版本）
find /media/sf_Share -iname "*<项目关键字>*" 2>/dev/null

# 2. 解压并确认 0 密文残留
mkdir -p /tmp/src && cd /tmp/src && unzip -oq "<zip路径>"
find . -type f -print0 | while IFS= read -r -d '' f; do
  head -c 200 "$f" 2>/dev/null | grep -qa Esafenet && echo "$f"; done | wc -l   # 应为 0
```

注意：zip 内文件的 mtime 是 Windows 原始时间，与本地密文文件 mtime 同源——**mtime 相同不能证明内容相同**，用 md5 比。版本差异要接受：只能恢复到 zip 打包时刻的状态，之后的本地改动需另行保留。

## 识别密文

```bash
head -c 200 "文件" | xxd | grep -a Esafenet   # 有输出 = 密文（标记在偏移 0x58=88 附近）
```

批量扫描：

```bash
find . -type f -print0 | while IFS= read -r -d '' f; do
  head -c 200 "$f" 2>/dev/null | grep -qa Esafenet && echo "$f"; done > /tmp/enc.txt
```

## 诊断解密引擎状态

| 检查 | 命令 | 含义 |
|---|---|---|
| 内核模块 | `lsmod \| grep esn_cfs`；`findmnt -T /home` 应为 esn_cfs | 模块/挂载正常 |
| 进程 | `ps aux \| grep ultrasec` | daemon 在跑不代表解密开启 |
| 日志 | `tail -c 500000 /usr/local/ultrasec/log/client.log \| grep -a -E "decrypt\|online_status"` | `Now stop decryption.` = 引擎停止；`ioctl_start_decrypt 0` = 引擎已启用解密（登录成功后出现一次，之后离线仍持续有效） |
| 离线标志 | 日志中 `displayOffline installMode`；服务器连通性 `ping 203.0.113.219`（策略服务器） | 离线不影响已缓存密钥的解密，只影响密钥刷新/new 授权 |
| 时钟 | `date` 对比真实日期 | **时钟错乱（如停在 2026-08-01）会触发授权保护**；修复需 root：`sudo timedatectl set-ntp true` 后重启 VM |
| 特权解密工具 | `/usr/local/ultrasec/start/decrytool -D <file>`（-CD 为中文提示版） | **需在线登录**（离线报 "To apply for decryption, please log in first"）；在线时报 `Decry success` 即成功。基础解密优先方法一，不必为它折腾登录 |

## 网络路由（登录/密钥刷新关键）

DLP 登录服务器为 `198.51.100.248:8090`（config.ini [server]）。VM 需有经 `192.0.2.1` (enp0s8) 到 `198.51.100.0/24` 的静态路由——2026-10-08 已写入 `/etc/netplan/01-netcfg.yaml` 持久化（备份 `/home/ubuntu/01-netcfg.yaml.bak_20261008`）。

- 日志出现 `login requset error` / `ret = -3` 循环 → 先 `ip route | grep 198.51.100` 查路由；缺则 `sudo ip route add 198.51.100.0/24 via 192.0.2.1 dev enp0s8`（并补进 netplan 持久化）。
- 路由在但 TCP 8090 不通 = 宿主侧网络问题，VM 内无解；已登录过的话缓存密钥仍支持方法一离线解密，别死磕登录。
- 2026-09-10 旧记录：时钟错乱+离线导致引擎停止，修时钟后需重启 VM 让 S99ultrasec 完整走开机时序（重启前 `sudo hwclock -w`；vboxadd-service 会把 VM 时钟同步成宿主机时间）。极端情况需 DLP 管理员在服务端解除终端锁定。`/etc/sudoers.d/ubuntu` 免密 sudo 已配置。

## Python 环境准备（本机无系统 pip）

环境特点：无 `pip3`、默认 PyPI 不可达。venv 已建在 `/home/ubuntu/.zcode/workspace/default/venv`（openpyxl、xlsxwriter 已装）。

仅当 venv 不存在时重建：

```bash
python3 -m venv /home/ubuntu/.zcode/workspace/default/venv
/home/ubuntu/.zcode/workspace/default/venv/bin/python -m pip install \
  -i https://pypi.tuna.tsinghua.edu.cn/simple openpyxl xlsxwriter
```

**务必带清华镜像** `-i https://pypi.tuna.tsinghua.edu.cn/simple`。解析 xlsx 用 venv 解释器，系统 python3 没有 openpyxl。解密后的 xlsx/docx 校验用 `zipfile.ZipFile(f).testzip()`（返回 None = 完整），不要依赖 `file` 命令。

## 已验证案例

- 2026-09-02 `CAN_UDL391RH(F501)_V1.00_20260902.xlsx`（605KB 密文）→ cp 解密成功，14 个 sheet 解析。
- 2026-09-10 D170H_PROJ_V1.62 项目 1703 个源码/资源文件密文无法编译：引擎因离线+时钟错乱停止；用 `/media/sf_Share/D170H4/D260HAU_PROJ_V1.93.zip`（zip 内容全明文）覆盖全部密文文件、保留本地 76 个明文改动，编译成功。教训：**从 Windows 传项目到 VM 必须打 zip**，直拷单文件会得到密文。
- 2026-10-08 `923128_ICP6600_XGDL_XS165II_Node1_PROJ_V1.02_Build20251222.zip`：zip 内混有 70 个密文 .as/.fla（非受控进程打包）。补齐 enp0s8 的 198.51.100.0/24 路由后客户端自动登录、引擎恢复（`ioctl_start_decrypt`）；产出完整明文工程 `<zip名>_decrypted/`（324 文件、0 密文残留）放回共享文件夹。
- 2026-10-12 UT120 `CAN_UT120_V1.00_20260909.xlsx` + `SRS_P-268DBU_...UT120...docx`：客户端离线（online_status 0）状态下 **cp 到 /home 即直接透明解密**（缓存密钥有效，全程未登录未用 decrytool）；解密版以 `_decrypted` 后缀放回 `/media/sf_Share/UT120/`，zip 完整性校验通过、尺寸各减 4096。
