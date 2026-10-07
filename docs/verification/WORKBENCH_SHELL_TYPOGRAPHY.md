# 外框与字体验证 / Shell and typography verification

源码预览 v14 补齐 v13 遗漏的窗口外层：使用原生 Qt 无边框窗口、自绘 12px 圆角和统一标题栏，菜单及最小化/最大化/关闭按钮进入同一栏；最大化时取消圆角与边距。拖动/缩放接 Qt 系统接口，关闭仍调用原 closeEvent，未保存草稿不会被窗口按钮绕过。 / Source preview v14 completes the outer shell with a rounded Qt frameless window and unified title/menu/control row. Maximized windows have no radius or inset. Move/resize uses Qt system APIs and close retains existing draft guards.

工作台进程明确使用 Segoe UI 与 Microsoft YaHei UI，正文 14 个逻辑像素；标题保留层级，不安装字体或修改系统设置。实际 Windows 字形排版确认中文使用 Microsoft YaHei UI、英文使用 Segoe UI，无缺字。输入参数页补为滚动容器，增大字体后不再因隐藏页最低高度撑大窗口。 / The workbench process selects Segoe UI plus Microsoft YaHei UI at 14 logical pixels, without installing fonts or changing OS settings. Native glyph runs verify both scripts. A scrolling input-parameter page prevents hidden-page minimum height from enlarging the window.

Main 51 项源码/隔离/离屏检查通过；补充目标选中后的属性布局检查 3 passed，与主集合重叠。实际 Windows 平台自建窗口的最大化、还原、最小化、关闭状态通过程序化验证，新预览窗口正常响应并使用新字体。真实鼠标拖拽/边缘缩放未实测，只验证事件到系统接口的调用；未覆盖所有 DPI 和多屏组合。本轮未派发外部输入，未发布或改产品版本。 / Main passes 51 checks plus an overlapping three-test inspector rerun. Native window-state transitions and font shaping pass programmatic checks. Physical dragging/resizing and all DPI/multi-screen combinations remain unverified; no external input or release change.

详见 `docs/verification/WORKBENCH_SHELL_TYPOGRAPHY.md`。v14 只是源码预览标识，旧窗口未热更新。 / v14 is a source-preview label; old processes retain their original code.

## 失败、修复与范围 / Failure, repair and scope

v13 只改内部内容，原系统外框未改，字体仍依赖默认选择。本次在工作台公共外框和启动字体层修复，而非修改某个测试应用。Windows 10 build 19045 使用 Qt 自绘圆角，不依赖 Windows 11 DWM 特性。新增执行权限为零。 / v13 omitted chrome and explicit typography. This fixes the shared workbench presentation layer, using Qt on Windows 10 without relying on Windows 11 DWM features or expanding execution authority.

首轮主入口 1 failed / 9 passed：字号与标题栏增高后，隐藏的工作流输入页最小高度使 760px 请求变成约 790px。为该页增加内部滚动，保持原参数控件和回调；同一布局/保存重开回归 10 passed，后续主回归 51 passed。原失败文件保留。 / The first integrated run exposed a hidden input-page height constraint. Scrolling repairs the shared layout invariant and preserves parameter behavior; first failures are retained.

## 实际命令与证据 / Commands and evidence

证据根目录 / Evidence root: `D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261002-learning-mainline-01/ui-shell-font/`。

```text
python -m pytest tests/test_workbench_window.py tests/test_workbench_typography.py tests/test_workbench_presentation.py tests/test_workflow_user_journey.py tests/test_review_window_placement.py tests/test_workflow_steps_ui.py tests/test_interface_switch_responsiveness.py tests/test_interface_target_box_journey.py tests/test_workflow_run_journey.py -q --junitxml=.../main-final.xml
51 passed in 54.86s
python -m pytest tests/test_workbench_presentation.py -q --junitxml=.../selected-inspector.xml
3 passed in 3.46s
python .../ui-shell-font/native_check.py
Windows font runs and window-state transitions passed
```

- `font-red.xml` / `font-green.xml`：字体路径先红后绿；覆盖中英文无缺字和标签/按钮 14px 字体继承。
- `main-first.xml` / `main-rerun.xml` / `main-final.xml`：保留过高窗口失败与修复后结果。最终 51 项失败/错误/跳过均为零，各次集合有重叠，不相加。
- `selected-inspector.xml`：目标框选中后的属性高度、滚动与原定位入口复验；没有派发输入。
- `native-check.json`：真实 windows 平台，透明不激活的自建测试窗口程序化最大化/还原/最小化/关闭；实际文本排版为 Microsoft YaHei UI 与 Segoe UI，各 14px。未注入鼠标/键盘到桌面。
- `captures/`：1440×960、1100×760 三页、运行页滚动、选中目标的属性面板均已检查。`preview-native.png` 为新预览初次显示，属性面板刚展开，不能代替布局稳定后的离屏选中态检查。
- `preview-live-window.json`：新窗口 PID、句柄、字体、实际尺寸、在工作区内等记录；当前 P4 库只用于预览，源码/离屏验收使用新合成内容。

移动/缩放回归通过替身 QWindow 验证正确接口和边缘选择，不声称真实鼠标移动已完成。整条学习模式仍需原计划的外部软件连续验收，本次未打包、更新版本或推送。 / Move/resize tests validate dispatch to the correct QWindow APIs with a test double, not physical mouse movement. Full learning acceptance and packaging remain separate.
