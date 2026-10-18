# 工作台外观验证 / Workbench presentation verification

学习源码预览 v13 统一三个页面的浅色圆角样式、按钮层级与线性图标；沿用截图、流程图和右侧修改布局。导航只对指示条做 160ms 动画，页面立即切换；“视图 → 减少动画”可关闭，启动时读取 Windows 客户区动画偏好，也可设置 `AGENT_REVIEW_REDUCED_MOTION=1`。运行页改为内部滚动，隐藏页面不再撑大整窗。 / Source preview v13 unifies rounded light surfaces, button hierarchy and line icons. Only the navigation indicator animates for 160ms; content switches immediately. Reduced motion follows the initial Windows preference or the environment override and can be toggled in View. The run page scrolls internally instead of forcing the whole window taller.

Main 84 项源码/隔离/离屏检查通过（47.99s），包含快速切页、键盘、减少动画、两种窗口尺寸、原编辑保存重开、目标框、后台读取及运行页恢复；已检查 1440×960 和 1100×760 的三个页面截图及小窗运行页滚动截图。首次缺图标、过高窗口和测试几何断言失败均保留，不算首次全部通过。 / The final main run passes 84 source/isolated/offscreen checks, including navigation, editing, target boxes, background selection and run recovery. Both window sizes and the scrolling run-page render were inspected; initial failures remain recorded.

本轮未派发外部输入、未做物理连续运行验收，未改产品版本、打包或发布；v13 只是源码预览标识。旧窗口不热更新。完整变化/中断/恢复与收尾验收继续作为学习试用版主线，收益验证仍后置。详见 `docs/verification/WORKBENCH_UI_POLISH.md`。 / No external input, physical continuous acceptance, product-version change, package or publication. v13 is only a source-preview label; existing processes retain old code. Physical continuity/recovery/cleanup remains the trial mainline, with benefits deferred.

## 变更与布局问题 / Changes and layout defect

- 外观：三页统一 7–10px 圆角、浅灰背景/白色内容面、蓝色主按钮、悬停/禁用/焦点反馈；图标由现有 PySide6 QtSvg 绘制，文字标签和操作含义保留。 / Scoped light theme and local vector icons retain labels and action semantics.
- 布局故障：全窗首轮仅检查宽度通过，截图却高达约 1100px。强化高度断言后失败；隐藏的运行页最小高度向上撑大 QTabWidget。修复在 `WorkflowRunPanel` 内容层增加滚动区，tab 身份/轮询/执行连接不变。小窗口和滚动底部回归通过。 / A hidden run-page minimum size propagated into the whole window. A content scroll area fixes the shared presentation invariant, without changing tab identity or execution.
- 通用性与安全：修复适用于工作台中任意任务内容；不调整窗口外输入、截图坐标、模型、版本引用或门控。 / The layout repair applies across task content and does not change desktop input, coordinates, models, pins or gates.

## 实际验证 / Executed checks

使用现有隔离 Python，`QT_QPA_PLATFORM=offscreen`，全新合成学习内容。 / Existing isolated Python, offscreen Qt, fresh synthetic learning content.

```text
python -m pytest tests/test_workbench_presentation.py tests/test_interface_switch_responsiveness.py tests/test_interface_target_box_journey.py tests/test_workflow_target_journey.py tests/test_workflow_user_journey.py tests/test_learning_membership_ui.py tests/test_workflow_run_panel.py tests/test_workflow_run_panel_recovery.py tests/test_workflow_run_panel_terminal_recovery.py tests/test_workflow_run_journey.py tests/test_review_window_placement.py -q --junitxml=.../ui-polish/main-final.xml
84 passed in 47.99s
```

原始证据 / Raw evidence: `D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261002-learning-mainline-01/ui-polish/`。

- `navigation-red.xml`：模块缺失的红阶段；`navigation-green.xml`：首次几何断言不正确；修正为 QRectF 几何后 `navigation-final.xml` 2 passed。
- `layout-first.xml`：1 failed / 6 passed，独立界面“保存修改”图标遗漏；补齐后 `layout-rerun.xml` 3 passed，仅宽度检查。
- `layout-height-red.xml`：1 failed / 2 passed，新增高度检查暴露窗口过高；`layout-height-rerun.xml` 3 passed。
- `main-final.xml`：84 passed，0 failures/errors/skips；包含高度、滚动可达性和原功能回归。以上集合有重叠，不相加。 / Overlapping runs are not additive.
- `captures/fresh-{1440,1100}-page-{0,1,2}.png` 和 `fresh-1100-run-scrolled.png`：已逐张目视检查，中文、按钮、目标框及页面边界可读。 / All seven renders inspected.

当前 P4 库仅用于向用户打开源码预览；不将旧内容当作本轮学习验收。现有正式版工作树保持干净。未测每种 DPI、主题和辅助技术，未声称完整视觉无障碍认证或真实执行稳定性验收。 / The existing P4 library is only a preview, not fresh-learning acceptance. The release checkout remains clean; all DPI/theme/assistive-technology combinations and physical execution are not certified here.
