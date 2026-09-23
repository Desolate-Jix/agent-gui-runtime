# 真实表单与文件选择调试 / Real-form and file-picker debugging

## 范围 / Scope

2026-09-23：在用户已有的真实求职表格上验证执行模式；只使用框架 MCP 派发输入，不提交申请。此文记录未发布源码修复，已发布 test.6 包未被覆盖。附件测试只使用明确标注测试用途、无个人信息的 PDF，不使用真实简历或求职信。

Source-only debugging on an existing real application form. All real input uses the runtime's MCP interface. No final submission is authorized. The published test.6 bundle is unchanged. Only a clearly marked, non-personal test PDF is used for attachment testing.

## 通用契约 / Common contracts

- **标签不是控件 Name。** 当前完整 UIA 快照中的唯一相邻可见标签可以关联 Edit、ComboBox 等控件，以及同时具有 Invoke/Value 的文件按钮。保留提供者原名称；关联证据另外绑定 control ID、runtime ID 和当前矩形。重复标签、一个标签下紧邻的多个控件、陈旧身份或矩形不自动猜测。
- **读取与定位使用同一身份规则。** 无名下拉读取成功后，定位生产者不能又只按 Name 丢弃该控件。主 ROI 从本帧确切 source ID 和矩形选择，不从旧截图取坐标。
- **主提示指向可操作区域。** 具有已验证标签关联的普通命名输入字段也进入同一主定位路径；不把浏览器工具栏同名项当作网页字段。文件按钮区分实际按钮名和旁边的字段标题，不能把标题当按钮。
- **测试实际模型边界。** VISTA 服务保留 Goal 与 Target constraints，不能只检查发送前文本。数字像素框不放入模型实际保留的别名说明，避免模型抄写像素值当作归一化坐标；框仍保留在诊断中，坐标校验不放宽。
- **选择文件不等于提交申请。** 新文件对话框需要重新发现、绑定、填写确切路径、核对后确认，再回到原表格检查附件名。选文件可能立即上传，必须事先确认文件内容与范围。

Visible labels and provider names remain distinct. Current label associations are identity- and geometry-bound, shared by readback and candidate generation, and rejected when ambiguous or stale. File-button prompts distinguish the actual widget from adjacent text. Regression tests cross the real model prompt adapter; pixel boxes remain diagnostic evidence rather than instructions that can be mistaken for normalized coordinates. File selection is separate from final submission and may upload immediately.

## 实测记录 / Live record

- 无名工作资格下拉：从未找到控件修复为展开、选择及读回成功，约 18.3 秒。
- 普通通知期输入：修复后定位、替换、读回约 8.0 秒；同会话邮箱、电话、通知期三字段连续填写约 27.6 秒。
- 薪资的两个 Select 均已真实展开检查选项并通过框架键盘选中；这不是 `form_fill` 同名多控件消歧通过的证据。
- 文件按钮从同名混淆、标题误定位修复为真正打开系统文件选择窗口，约 6.5 秒；文件名字段读回的 owned-window 身份误判已修复：原生 GA_ROOT 不沿 owner 链返回浏览器。实际路径填写、读回约 9.7 秒，确认选择后原表格显示测试 PDF。
- 保留了首次失败、提示修改引起的输入回归，以及修复后复验，不以最终重跑覆盖历史。没有最终提交。

The unnamed dropdown passed open/select/readback (~18.3 s); a repaired text field took ~8.0 s, and three-field continuous filling ~27.6 s. Both salary selectors were inspected and keyboard-selected, not claimed as automatic same-label disambiguation. The repaired file button opened the native picker (~6.5 s), and the owned-dialog field identity was corrected using native GA_ROOT rather than the browser owner. Exact path entry/readback took ~9.7 s and the original form displayed the chosen test PDF. First failures and intermediate regressions remain recorded. No final submission occurred.

## 后续连续复验 / Follow-up continuous checks

- 同会话三个文本字段及已满足下拉状态共 30.2 秒，全部实际读值 matched；新通知期值可见。
- 文件对话框重新打开成功，但重复文件名定位尚未稳定：一次泛目标模型点偏上，零输入拒绝；随后确切标签被错误的网页内容准备阻断。这是修复前的失败；后者已按窗口类型判别修复，不能归结为文字标签歧义。
- 中间测试驱动曾读到尚未写完的收件箱 JSON 后退出；这是验收客户端竞态，不是产品崩溃。客户端改为临时文件写完后原子改名，宿主退出报告保留。
- 正确 clean-desktop Python 环境完整回归 1572 passed / 32.40 s；另一次 uv 环境缺 MCP 导致 74 项依赖错误，不混记为源码路径回归。后续代码修改须重跑。

A same-session four-field sequence passed actual readback in ~30.2 s. Reopening the picker passed, but repeated filename focus exposed a refused off-target model point followed by a native dialog incorrectly entering browser-content preparation. These are retained pre-fix failures, not a claim of successful repeated selection. A separate acceptance-client partial-JSON race was fixed with atomic inbox publication; it was not a product crash. The proper clean-desktop interpreter passed 1572 checks before the remaining readiness fix; a missing-MCP uv environment was separately recorded.

## 最终源码复验 / Final source rerun

2026-09-23，本轮最终源码 **1574 passed / 32.49 s**，新增原生对话框身份与 browser readiness 回归；git diff --check 通过。未发布包，不覆盖 test.6。

| 验证 / Check | 实际结果 / Observed result |
|---|---|
| 两个不同 HWND/PID 的文件对话框，确切标签文件名输入 / Exact filename input in two distinct dialogs | 11.846s、11.854s；两次 uia_value 精确 matched，截图确认相同测试 PDF 绝对路径 |
| 取消 → 原表单恢复 → 再打开 / Cancel, restore, reopen | Escape 58ms；原附件、字段保留；再打开约6.07s，重新发现并绑定新对话框 |
| 确认选择测试文件 / Confirm selected test file | 9.238s；对话框关闭后显式回绑原浏览器并截图，表单显示测试 PDF；不是后台上传或最终申请提交成功的声明 |
| 返回表单后再连续填3个文本与核对下拉 / Text and dropdown after dialog recovery | 29.920s；4项全部 matched，下拉已是目标值，没有反向切换 |
| 最终清理 / Final cleanup | host_alive=false、pending_ids=[]、cleanup_verified=true；原浏览器保留 |

The final source passed 1574 tests. Two different native dialog instances accepted and read back the exact test-file path. Cancel/reopen recovery retained the form and attachment; confirming the chosen file closed the dialog and the original form displayed its name. This proves UI-level selection, not server-side upload completion or application submission. A following three-text-plus-dropdown sequence passed all four readbacks. The host stopped cleanly and the user's browser remains open.

### 故障到通用契约 / Failure-to-runtime closure

| 可见失败 / Failure | 通用不变量及修复位置 / Invariant and common fix | 回归 / Regression |
|---|---|---|
| 无名下拉找不到、文件按钮点到标题 | 可见标签≠原始Name；form_label_binding + provider/reader/control_target/vision 共用当前身份和真实框 | 唯一/重复/陈旧标签、同帧候选、实际模型提示边界 |
| 文件名框误报窗口变化 | UIA owner不是原生根窗口；windows_text_field_reader 使用 GA_ROOT，不跨对话框到owner | owned dialog读字段通过，其他根仍拒绝 |
| Edge文件框等待网页正文 | 进程名不能代替窗口类型；browser_content_readiness 只对完整当前 #32770 根标记不适用 | 原生对话框通过、未知根拒绝、真正浏览器准备原行为 |

这些修复面向共享 UIA、模型提示和原生窗口层，不硬编码此网站、控件坐标或用户文件路径。没有放宽模型落点边界、添加盲重试、绕过最终提交或增加真实输入授权；泛自然语言仍可能因模型点落在真实框外拒绝，不能据此声明任意表单都稳定。

These fixes apply to shared label, model-prompt and native-window contracts, without hard-coded site coordinates or personal paths. No coordinate tolerance, blind replay or submission authority is added. Generic model localization can still miss a small field and be refused; this is not universal form reliability.

## 证据与边界 / Evidence and limits

原始回执、截图和提示对照保留在本机隔离验收目录，不提交到仓库，因真实表格含个人信息和私有链接。不是发布验收、不是通用成功率；尚未打包或委托 AionUi 独立验收。本次不新增最终提交权限或自动重试。

Raw evidence stays local because the real form contains private data. This is not release acceptance or a universal success-rate claim. No new package, independent-agent acceptance, final-submit authority, or automatic replay is introduced.
