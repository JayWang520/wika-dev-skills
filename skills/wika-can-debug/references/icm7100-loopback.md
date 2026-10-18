# ICM7100 本机 CAN 模拟方法与实测案例

在不接外部 CAN 节点进行调试，或需要理解 SocketCAN → SDK → Qt 的消息路径时阅读。以下方法已在 TZ956E/ICM7100 上实际运行；其他型号先核对控制器、SDK ABI、通道和变量定义。

## 两层接收路径

TZ956E 工程中，CAN 帧与页面消息不是同一层：

```text
脚本 PF_CAN/CAN_RAW → can0 内部回环 → libhsm 接收 / EDS 映射 → SDK 对象变量
SDK 本地消息 → my_msg_local_recv → messageRecv → ProcessCanBus → OnCanRecv → 页面
```

源码定位结果：

| 位置 | 行为 |
| --- | --- |
| `Framework/applicationruntime.cpp:73` | 启动 CAN1；第 75 行启动 CAN2，并设置工程使用的扩展帧模式。 |
| `Framework/responseinteriormessage.cpp:36` | 设置波特率、加载 EDS、启动节点与消息轮询定时器。 |
| `Framework/wikalib.cpp:283` | `RunInDevice` 分支调用真实 `canopen_start()`。 |
| `Framework/wikalib.cpp:100` | `canopen_read_var_int()` 读取 SDK 对象变量。 |
| `Framework/wikalib.cpp:361` | `my_msg_local_recv()` 调用 SDK 的 `msg_local_recv()`。 |
| `Framework/responseinteriormessage.cpp:183` | 消费本地消息，`my_MSG_CAN_OD` 经 `CanDataProcess::ProcessCanBus()` 发出 `OnCanRecv`。 |
| `Framework/formbase.cpp:105` | 页面调用 `processCanBus()`；QML 也能通过 `QmlWikalib.cpp:24` 直接读变量。 |

行号和文件名属于本次案例；在当前工程重新定位。项目没有 SDK 底层接收函数的源码，CAN 接入以实际帧注入和 SDK 解码结果验证，没有把二进制字符串检查当作源码阅读。

SDK `message.h` 提供 `MSG_CAN_OD`、`msg_can_t`、`msg_local_send()`。这些是进一步做上层消息模拟的入口，但必须核对 ABI、目标接收通道和分发机制后另行测试。项目的 `simulate_msg_local_recv()`、`AddSimulateValue()` 处于 `#ifndef RunInDevice`，不能直接当成实机注入接口。

## 检测可用的本机通道

本次设备允许创建独立网络命名空间，但创建 `vcan` 返回 `Operation not supported`，所以没有安装或强行替换驱动。随后在原本关闭的 CAN1 上测试控制器 `loopback on/off`，成功并恢复原状态；实际 SDK 试验使用 CAN0。

硬件无外部节点时，普通 SocketCAN 本地回显与控制器内部回环分开检查。[Linux SocketCAN 文档](https://docs.kernel.org/networking/can.html#local-loopback-of-sent-frames) 说明普通回显在成功发送后发生。该案例显式开启了控制器的 `LOOPBACK`，并在 SDK 初始化后再次确认该模式仍有效。

## 实施顺序

1. 保存当前程序服务、实际可执行文件及哈希；保存 `/sbin/ip -details link show can0` 的 UP 状态、位时序、restart-ms、txqueuelen 和模式。备份原配置，使用临时目录中的 EDS 三件套。
2. **SDK 探针模式**：暂停当前界面，避免测试程序和业务程序各自管理同一控制器。用显示器本机监督进程启动有时限的探针，并在退出路径恢复接口与服务。
3. 开启内部回环。以下命令假定已保存配置、接口支持该模式且当前允许切换；通道按工程调整：

   ```sh
   /sbin/ip link set can0 down
   /sbin/ip link set can0 type can loopback on
   /sbin/ip link set can0 up
   /sbin/ip -details link show can0
   ```

4. 通过目标机 `/usr/lib/libhsm.so` 调用实际 SDK，并核对返回值与 `LOOPBACK` 状态。本次依次调用 `canopen_baud_rate`、`canopen_start`、`canopen_j1939_mode`、`canopen_start_node`；帧模式的含义按对应版本头文件确认。
5. Python 用 `socket(PF_CAN, SOCK_RAW, CAN_RAW)` 绑定 `can0` 发送载荷，另一个 socket 观测帧。扩展帧使用 `CAN_EFF_FLAG`，经典八字节帧布局为 `struct.pack('=IB3x8s', id | 0x80000000, 8, payload)`。数据从帧入口进入，接收对象值由 SDK 读取。
6. 完成下表的旧 ID 对照和两组收发检查。`recvmsg()` 的 `MSG_DONTROUTE`（本案例数值 4）标识本机来源；保留原始标志，报告为内部回环帧。
7. 关闭回环，恢复原位时序、队列、接口 UP/DOWN 状态和先前服务；核对恢复结果与文件哈希。该 SDK 探针不修改数据库、logo 或正式 BIN。

若测试目标是业务界面，运行原业务程序并仅注入原始帧，按实际接收协议检查页面；不要同时再启动独占通道的 SDK 探针。本案例已验证 SDK 收发，Qt 消息路径经过源码检查，但尚未逐页执行 UI 验收。

## 实测配置和结果

独立 EDS 副本的 RX PDO1 为 `18FFAAE5`、TX PDO1 为 `18FFABE5`；250000 bit/s、扩展帧。RX 变量 `0–7` 对应 `0x2000:1–8`，TX 变量 `129–136` 对应 `0x206C:1–8`。

| 检查 | 实际结果 |
| --- | --- |
| 初始化 | baud/start/extended/start_node 返回值全部为 0。 |
| 旧 ID `18FA10EF / A1A2A3A4A5A6A7A8` | 帧可见，SDK 变量和对象保持初值。 |
| RX `18FFAAE5 / 1122334455667788` | 八个变量和对象均为 `[17,34,51,68,85,102,119,136]`。 |
| RX `18FFAAE5 / DEADBEEF01234567` | 均为 `[222,173,190,239,1,35,69,103]`。 |
| TX | 写八个 TX 变量后调用 `send_pdo(0,1)`，所有返回值为 0，观测到 `18FFABE5` 与各自相同的八字节。 |
| 恢复 | 原服务恢复运行，控制器回环关闭；原程序、EDS/.h/.var、数据库、logo 哈希不变。 |

试验未调用外部 CAN 盒工具；五条相关帧为本机观测记录。本方法不验收外部接线、收发器、终端电阻或其他节点，也不把接口重置后暂时清零的错误计数当作故障修复。

## 已运行过的案例脚本

- [can_internal_sdk_probe.py](../scripts/can_internal_sdk_probe.py)：帧注入、SDK 对象/变量核对、PDO 发送及 JSON 结果。
- [can_internal_supervisor.py](../scripts/can_internal_supervisor.py)：保存当前配置，暂停服务，监督探针并恢复接口/服务。

探针与本次实机运行脚本一致；监督脚本在实测版本上补充了命令超时/执行错误的记录，使单条恢复命令失败后仍继续尝试其余步骤。脚本固定使用该案例的通道、ID、变量和服务名。其他工程先按代码和 SDK 适配；它们不是对所有 WIKA 型号通用的自动配置程序。监督脚本的入口为 `python3 can_internal_supervisor.py <临时目录>`，临时目录须包含两个脚本及匹配的 `can0.eds/.h/.var`，并以具备当前设备操作权限的用户运行。

编写或适配监督程序时，保证探针超时会结束，且任一恢复步骤失败后仍尝试其余恢复操作并保存结果。仅重复运行探针而遗漏恢复，不构成完成测试。
