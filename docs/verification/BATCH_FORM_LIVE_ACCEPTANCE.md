# 组合填写实测 / Batched form live checks

2026-09-23，源码开发检查点，**未发布**。所有输入经过被测框架 MCP，使用公开网页和无个人信息的测试值；没有最终提交。/ Source development checkpoint, **not a release**. Inputs used the framework MCP against public pages with synthetic values; no final submission.

## 公共修复 / Shared fixes

1. 显式 `TextField.label` 必须作为完整标签传入定位提示，不能把名称中的 `input` 或 `field` 再切成语法。例如 `Text input` 不再变成 `Text`。/ Preserve the explicit field label as a quoted literal, including words that also occur in instruction syntax.
2. 唯一、本帧、真实 UIA 文本框或可编辑组合框，模型点在边界外至多 2 px 时可校正到真实框中心，并如实报告坐标来源；更远的点仍拒绝。曾试用 8 px，但完整回归发现会放过已记录的 Maps 框外点，因此收窄为已实测的 2 px。/ Reconcile at most 2 px of boundary disagreement for a unique current editable control, dispatching inside its real box with explicit provenance. An 8 px experiment failed the existing Maps negative regression and was narrowed; farther points remain rejected.
3. 真实 httpbin 的 178×21 文本框原先没有进入小控件放大路径，模型多次落在上边界外。现在 64–512 px 宽、16–32 px 高的唯一当前输入框复用有界标签上下文和最多 3 倍放大；保持目标框、逆变换和框外拒绝不变。38 px 高普通字段保留原路径，避免扩大改动范围。/ Small current text fields now reuse bounded label context and upscaling without changing target boxes or accepting outside points. Regular-height fields retain their original path.

以上修复位于公共表单编排和视觉预处理，不含网站名、预置坐标或自动重放。/ Changes are in shared orchestration and visual preprocessing, without site identifiers, fixed coordinates or automatic replay.

## 连续测试与速度 / Continuous checks and latency

| 路径 / Path | 结果 / Result | 工具耗时 / Tool time |
|---|---|---|
| Selenium 混合八项 / mixed eight fields | 较早源码两轮完成；标签与边界问题的首次失败保留 / Two earlier-source reruns completed; first failures retained | 78.38 / 78.96 s |
| 三个选择项重复状态 / three already-satisfied choices | 完成，零输入 / Complete, no input | 4.46 s |
| 不存在的下拉选项 / missing option | 返回四个可见选项及剩余索引，后续文本未填写 / Interrupted with choices and remaining indexes; later text untouched | 8.64 s |
| 展开下拉恢复 / recovery from open dropdown | 明确新命令选择 One 后完成 / Explicit new command selected One | 8.79 s |
| Tab 下一个标签错误 / unexpected next Tab label | 第一项完成，下一项输入前中断 / First field complete; stopped before typing into the unexpected field | 5.43 s |
| httpbin 三文本逐项识别 / three fields, recognize each | 同会话两轮，逐值读回和截图一致 / Two same-session rounds with readback and image checks | 16.30 / 16.02 s |
| httpbin 同三文本 Tab 组合 / same fields, Tab group | 与上项交替执行，两轮完成 / Two successful alternating rounds | 7.03 / 6.97 s |

最后四轮为同一代码、模型已驻留、同一窗口的 A/B/A/B 对比。平均工具耗时从 16.16 s 到 7.00 s，约减少 **57%**；不包含约 8.63 s 冷启动或 Agent 往返时间，不代表所有表格都能同幅提速。只适用于已知 Tab 顺序的连续、具名、可写文本控件。/ The same-session warm-model comparison reduced mean tool time by about **57%**. Cold preparation and agent round trips are excluded; this is not a universal speedup claim.

首次逐项 Telephone 定位失败、早期 Tab 第二轮首项失败，以及扩大预处理到常规高度字段后的拒绝，均保留，不改记为首次成功。/ Original localization failures and the regular-height preprocessing regression remain recorded; successful reruns do not erase them.

## 当前验收边界 / Acceptance boundary

- 发布前追加修复：带引号的结构化标签经 JSON 转义后被公共标签解析器提前截断，可能选择同前缀的另一字段；现在统一按 JSON 字符串边界与解码处理，保留自然引号兼容。回归先出现 8 failed / 6 passed，修复后相关 155 项通过；包含原标签和截断名同时存在时正确选取与错误候选拒绝。没有放宽动作检查，不是网站特例。最新完整源码回归 **1727 passed / 33.26 s**；独立代码复核 51 项通过。/ The shared parser now preserves JSON-escaped labels instead of targeting a truncated-name field. Red-first regression, 155 related checks and 1727 full-source checks passed; independent code review passed 51 checks. No action checks were loosened. These offline results do not replace live or independent-agent acceptance.

- 最新源码完整离线回归：`python -m pytest -q`，1711 passed in 33.07 s；当前具名字段主路径集成及相邻测试 105 passed。/ Latest full source regression passed, including the named-field primary-route integration and adjacent checks.
- 修复前混合八项复验：两项完成，第 3 项 datalist 的模型点 (510,233) 比真实框 (461,238,356,38) 上沿高 5 px，被拒绝；剩余六项未执行。该失败保留，不能用后续成功抹去。/ The pre-fix run rejected the datalist point 5 px above its real box after two fields; the original failure remains recorded.
- 下述主定位修复后，同会话八项连续两轮全部读回且截图一致：116.010 s / 104.409 s。Textarea 和可写 datalist 使用真实当前控件中心，日期与其他状态控件保留原识别流程；首个 Text input 的当帧 UIA 只有浏览器栏、无页面字段，明确使用原视觉路径，不伪报 UIA 命中。/ Two post-fix eight-field rounds passed all readbacks and image review. Named textarea/datalist used current geometry; absent page UIA correctly retained visual localization. These whole-batch timings are not a speedup claim.
- 同会话非法下拉选项在 11.107 s 中断并返回实际选项，后续文本未改；明确新命令从展开状态选择 One，12.139 s 完成。/ Invalid option interrupted with available choices and untouched subsequent text; a new reviewed command recovered the open dropdown.
- 两个不同原生文件对话框分别填入同一虚构附件绝对路径并读回，10.930 s / 9.556 s；取消、回绑、重开和确认选择后，原表单显示 synthetic-attachment.txt。未最终提交，不能据此宣称服务端上传完成。/ Two native dialogs accepted the synthetic path, with cancel/reopen recovery and the final filename visible on the original form. No final submission or server-upload claim.
- 最新源码 httpbin 三字段 Tab 组合两轮读回和截图一致：9.618 s / 9.715 s。本轮没有同版本逐项对照，不与前批 57% 数字混算。两个本轮新窗口均通过确切身份关闭，宿主 stopped、pending 为空、cleanup_verified=true。/ Two final-source Tab rounds passed. No new A/B speedup claim; both owned test windows closed and host cleanup verified.
- 仍需隔离候选及独立验收；未发布。/ Isolated bundle and independent acceptance remain; no release.
- AionUi 桥在线但后端拒绝连接；没有投递测试，也没有提前发布。/ Bridge alive, backend unreachable; no independent task dispatched and no release claimed.
- 原始回执和截图只保存在本地验收目录，公开文档不包含用户求职 URL、个人数据或凭证。/ Raw artifacts stay local; no private application URL, personal data or credentials in this document.

## 具名文本字段主定位修复 / Named-text primary localization

- 失败契约：完整当前 UIA 已唯一识别可写字段，仍强制让模型重新猜焦点，导致真实框外的点阻断整批。不是通过扩大容差解决。/ The broken contract forced model focus proposals even when a complete current UIA snapshot already uniquely identified a writable field; no tolerance widening is used.
- 显式 `TextField.label` 在模型调用之前可选择当前控件中心；要求同图、同尺寸、完整未截断的窗口树、唯一标签、可写且可见控件及匹配的真实边界。过滤后的清单只须保留选中原始控件，不能错误要求整个过滤清单等于原始树。/ An explicit text label may select current control geometry before inference, requiring current complete evidence and unchanged selected-control membership in the filtered inventory.
- 继续经过原识别点击入口、实时控件身份/焦点与填写读回；其他请求维持原路径，模型拒绝后不换坐标重试。回执明确 `current_uia_named_text_center`、模型未调用和待 Agent 判断结果。/ The same action API, live identity/focus checks and readback remain; other requests keep their existing route. No post-rejection coordinate fallback or automatic replay. Provenance explicitly reports the geometry source and skipped inference.
- 回归覆盖：真实过滤结构、重复/缺失/变更控件、错误帧和尺寸、截断/错误扫描范围、不可写/受保护字段、原生 Edit 与可写 ComboBox 集成。无新提交能力。/ Regression covers filtered trees, conflicting identities, stale frames, incomplete scans, protected controls, and Edit/ComboBox integration. No submission capability is added.
