---
name: wika-ui-index
description: >-
  为 WIKA Qt/QML 工程从源码、资源图片和实机截图建立界面操作索引，按页面与控件名称查询触摸坐标、生成导航测试计划并记录实机验证。当用户要求计算按钮坐标、建立界面索引、自动生成切页测试，或在线测试需要反复定位控件时使用。当前适配已验证的静态 QML 布局；Widgets .ui 与复杂动态布局需另行适配。
---

# WIKA 界面操作索引

把代码中的控件、触摸区域、页面跳转和实机画面关联起来，供在线测试查询和生成计划。配置保存源码角色、截图与程序版本，坐标由工具计算。当前版本是经过 ICM7100/TZ956E 验证的 QML 子集，不是完整的 QML 布局引擎。

## 工作流程

1. 使用现有 CodeGraph 定位入口、页面、公共布局和按钮组件，核对触摸按下/松开回调。按已授权测试范围选择导航页面；包含业务操作的回调单独列测试项。
2. 核对源码与已编译程序版本，获取 framebuffer 实际尺寸，并为每页保留两张不同时间的原始 framebuffer PNG。首次配置或适配布局时读取 [配置与边界](references/profile-and-limits.md)，从 [TZ956E 配置示例](assets/tz956e-ui-index.json) 填入当前工程路径与版本。
3. 运行 `build`，确认准备测试的控件状态为 `image_confirmed`；检查 `unresolved` 的原因。此状态表示源码位置与参考图片相符，实机点击证据另记在 `live_verification`。
4. 按页面和名称查询控件，生成指定页面路线。工具会在已确认的页面关系中寻找中间页，并生成点击区域中心、每步控件检查及目标页特征。
5. 部署后核对运行 ELF 与计划的程序 SHA256，并核对 `source_sha256` 对应的源码/资源快照。调用 [设备端批量执行与页面就绪检测](../wika-dev-flow/references/ui-batch-test.md) 执行计划。使用包含控件 `guard` 检查的执行器；当前页或控件不匹配时停止后续点击并留图。
6. 核对截图与业务测试项。监督任务确认程序身份和收尾结果后，用 `record` 将**同一计划、同一程序**的实机结果回填索引。源码、资源、参考图、配置或索引器变化后重建；重建不继承旧的实机验收标记。

## 工具

[scripts/ui_index.py](scripts/ui_index.py) 在主机运行，需要 Python 3.8+ 和 Pillow；设备端执行器使用 Python 3.7 标准库。输入文件可位于 Linux 工程，或保留相对目录的本机镜像。首次运行前确认所选主机 Python 能 `import PIL`。

在工程根放置 `ui-index.json` 后，使用当前 skill 的脚本路径调用：

```bash
python3 /path/to/wika-ui-index/scripts/ui_index.py build /path/to/project
python3 /path/to/wika-ui-index/scripts/ui_index.py status /path/to/project
python3 /path/to/wika-ui-index/scripts/ui_index.py search /path/to/project --page menu --query 版本
python3 /path/to/wika-ui-index/scripts/ui_index.py plan /path/to/project --route main,menu,version,menu,main --output /path/to/project/generated-plan.json
python3 /path/to/wika-ui-index/scripts/ui_index.py record /path/to/project --plan /path/to/project/generated-plan.json --result /path/to/project/live-result.json
```

- 索引保存在 `<工程根>/.ui-index/index.json`。未变化时 `build` 复用缓存；变化后重建配置覆盖的页面。
- `search` 返回源码位置、控件区域、原始 framebuffer 点击坐标、跳转目标、图片匹配结果及已有实机证据。
- `status` 返回输入是否新鲜；过期时 `search/plan/record` 拒绝使用旧坐标。
- `plan` 输出兼容批量执行器的 JSON，并附带程序指纹、计划 ID、每步控件检查。当前只自动规划单个字面量 `iMainWindow.showpage(...)` 调用，含额外业务动作或动态参数的回调保留为 `unresolved`。
- `record` 的结果契约、局限与适配方法见 [配置与边界](references/profile-and-limits.md)。记录失败时保留原始证据，先解决版本/计划不一致。

## 执行边界

计算与查询阶段只读工程源码和资源，写入索引与指定计划文件。设备上的点击仍走真实触摸事件，覆盖按下与松开链路；页面识别成功只代表导航完成，CAN、业务读数、翻译和图形正确性按对应测试项验证。

`unresolved` 控件使用现有单步校准方法或另行适配运行时几何；不会为了生成路线而猜测坐标。当前未适配 Widgets、动态列表/Repeater、任意 JavaScript 布局、图像缩放、复杂裁剪或滑动。

实测范围及证据见 [TZ956E 验证记录](references/tz956e-validation.md)。
