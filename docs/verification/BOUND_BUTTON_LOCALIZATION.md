# 关联标签按钮定位 / Associated-label button localization

- **Failure / 故障**：test.7 candidate02 在选入附件后，两次重新打开文件选择器均返回 `local_recognition_invalid / local recognition point outside candidate`，未点击。模型点 `(1070,297)` 位于当前真实 UIA 控件框 `(998,308,416,38)` 上方。
- **Invariant / 通用契约**：辅助功能 Name 不等于可见按钮文案。Name 可以拼接字段标签和当前值；不能将其改写成“按钮上印着这些字”。/ Accessible names may concatenate labels and values and must not be asserted as printed captions.
- **Root / 根因**：提示词声称按钮印着 `File input: <filename>`，且 96 px 最小上下文包含上方非交互字段标签。仅澄清提示词后仍复现，保留该失败；不是坐标容差不足。/ The prompt invented a visible caption and the minimum-height crop included the external label. A prompt-only change did not resolve the live failure.
- **Fix / 修复位置**：共享 `app/api/vision.py` 保留原指令，并区分 accessibility name 与 visible label；只有当前 UIA 单一按钮、绑定标签和实际框一致、尺寸有界时，使用真实控件区域原图放大定位。其他候选、重复候选及无绑定按钮继续原路径。/ The shared prompt distinguishes accessibility metadata; only a unique current bound button uses a control-only pixel crop.
- **Why common / 通用性**：不依赖 URL、站点名称、字段名称、文件名、固定屏幕坐标或按钮语言。/ No site, filename, coordinate or language-specific rules.
- **Regression / 回归**：`tests/test_bound_button_accessible_name.py` 验证真实模型服务提示词边界、单候选裁图与映射，以及非当前/未绑定/重复候选负例。原真实候选 bbox 保留不变；框外模型点依旧拒绝，未添加自动重试或直接中心点击。/ Tests cover the effective server prompt and crop boundaries without weakening input validation.
- **Verification / 验证**：源码全套 **1759 passed / 36.27 s**。真实 Selenium 页面同连接连续验证：首次文件按钮 20.108 s（含冷模型启动），选择附件并原始目标点击打开 8.766 s；选后重开 7.930 s、识别取消 8.660 s、再次重开 7.444 s、再次原始目标点击打开 8.795 s，网页显示 `synthetic.txt`，未提交。两次新重开均首次成功，旧失败不改记。/ Real same-session first-open, attachment confirmation, reopen/cancel/reopen and second confirmation passed; the webpage displayed the synthetic attachment without submission. Repaired frozen-candidate independent acceptance remains pending.

原始失败和截图仅本机保存，不包含在公开包。/ Raw failure evidence remains local and is excluded from public artifacts.
