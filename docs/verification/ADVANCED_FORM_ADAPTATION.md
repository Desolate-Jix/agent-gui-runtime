# Advanced Form Adaptation / 复杂表单适配记录

> 本记录描述本批适配与验收边界，不代表已支持所有复杂表单。真实验收证据保存在本机 `D:\AgentReviewAcceptance\20260923-advanced-form-01`、`-02`、`-03`；不复制或外传原图。
>
> This record covers only the current adaptation slice; it does not claim support for all complex forms. Raw acceptance evidence remains local under `D:\AgentReviewAcceptance\20260923-advanced-form-01`, `-02`, and `-03`; screenshots are not copied or shared.

## Scope and verified outcomes / 范围与已验证结果

- `form_fill.py` and its MCP description add `kind=date` with `field_goal`, `value`, and explicit `format`. Supported format identifiers are exactly `YYYY-MM-DD`, `DD/MM/YYYY`, and `MM/DD/YYYY`. The value must be a real ISO calendar date (not merely a shape-matching string). Date entry does not press Enter.
- `form_fill.py` 及 MCP 描述新增 `kind=date`，字段为 `field_goal`、`value` 和显式 `format`。格式标识仅为 `YYYY-MM-DD`、`DD/MM/YYYY`、`MM/DD/YYYY`；日期值须为真实日历日期，不能只通过字符串形状检查。录入不按 Enter。
- W3C date page: `09/30/2026` was entered/read back successfully; `root02 adv-1790125808715`, 52.971 s.
- W3C 日期页：`09/30/2026` 已成功录入并读回；`root02 adv-1790125808715`，52.971 秒。
- External dropdown options are accepted only when `CurrentControllerFor` establishes a unique `List` belonging to the same window/PID and its runtime identity; the complete bounded tree scan and ambiguity checks remain required. Scan budget is 1024 and does not permit early success or skipping full-tree/ambiguity validation.
- 外置下拉选项仅在 `CurrentControllerFor` 证明其唯一所属 `List`，且 List 与目标同窗口/PID并通过 runtime identity 校验时接受；仍要求完整有界树扫描和歧义检查。扫描预算为1024，不可提前成功或跳过全树/歧义校验。
- Dropdown evidence: first attempt `root01 a-1790125427234` failed at the former 512-edge limit (`form_control_scan_limit`), 7.570 s. `root02 adv-1790125694142` did not find the external option, 35.090 s. `root03 adv-1790126289445` selected `Apple` successfully, 58.071 s.
- 下拉证据：首次 `root01 a-1790125427234` 因原512边预算失败（`form_control_scan_limit`），7.570秒；`root02 adv-1790125694142` 未找到外置选项，35.090秒；`root03 adv-1790126289445` 成功选择 `Apple`，58.071秒。
- Current unit-test result reported for this candidate: 1608 passed, 32.41 s. Continuous-use evidence is recorded below; unit tests alone are not live acceptance.
- 当前候选单元测试结果：1608 passed，32.41秒。连续使用证据见下文；单元测试本身不能代替实机验收。
- Runs `advanced-form-01`, `advanced-form-02`, and `advanced-form-03` finished with `cleanup_verified=true`, no live host and no pending commands; all windows created in these runs were closed.
- `advanced-form-01`、`advanced-form-02`、`advanced-form-03` 均已 `cleanup_verified=true`，宿主退出、pending 为空；本批新建窗口已关闭。
- Native file selection using a native dialog and a harmless file was verified in the previous batch. This is not a general drag-and-drop upload capability.
- 上一批已用原生对话框和无害文件验证原生文件选择；这不等于通用拖拽上传能力。

## Failure and invariant review / 失败与不变量审查

| Failure / failure evidence | Root invariant / 根不变量 | Fix location / 修复位置 | Why not app-only / 不限于单应用的原因 | Regression / 回归 | Safety impact / 安全影响 |
|---|---|---|---|---|---|
| The first W3C dropdown attempt stopped at 512 scanned edges despite one label match; the second attempt could not find the external option. | A control may be acted on only after complete bounded ownership/identity enumeration and ambiguity checks; a partial tree is not proof. | Shared `windows_form_control_reader.py` scan/ownership logic; 1024 remains a hard budget, not a partial-success threshold. | External popup/list ownership is a reusable UIA contract across browsers and desktop apps. | Preserve the 512-limit first failure and missing-option failure as historical evidence; verify full-scan ownership and successful `Apple` selection in `root03`. | No weakening: ambiguous or unowned options still stop; action remains gated and read-back verified. |
| Quill rich-text attempt `adv-1790126080513` failed after 10.624 s: only focus was achieved, no text was entered. After click, layout reordered; the old point landed on a video, actual focus was `ql-editor` reported as `Group`, with no explicit writable marker. | Candidate geometry must remain fresh through dispatch; a focus event alone does not prove editable/writable content. | Common candidate freshness and editable-field capability contract; no app-specific success workaround. | Stale geometry and missing editability proof can affect any dynamic document/editor UI. | Keep this attempt as a failure; require fresh capture/target identity plus explicit writable semantics and post-input text read-back before a future rich-text claim. | Do not retry a stale point or type into an unverified editor; no text side effect was confirmed. |

## Not yet adapted / 尚待适配

- Searchable multi-select requires set-valued selection/read-back and explicit add/remove semantics.
- 搜索型多选仍需集合型选择/读回及明确的增删语义。
- Calendar navigation (beyond date text entry) is not covered.
- 日历控件导航（超出日期文本录入范围）尚未覆盖。
- The earlier Quill attempt failed as recorded above. A later full-form slice verified plain text entry/replacement in explicitly writable rich-text content; formatting and mixed readonly/editable media remain unverified.
- 早先 Quill 尝试按上文保留失败；后续整表批次已验证明确可写富文本内的纯文字填写/替换。格式工具及混合只读内容仍未验收。
- General drag-and-drop upload is not covered; only native file-dialog selection was verified.
- 通用拖拽上传尚未覆盖；仅验证了原生文件对话框选文件。

## Acceptance boundary / 验收边界

No final submit was performed. The protected pre-existing job-search page was not touched. No packaging or push was performed. The dropdown/date source slice passed the continuous checks below; this is not complete advanced-form or release acceptance.

未执行最终提交，未触碰受保护的既有求职页面，未打包或推送。下拉/日期源码子集已完成下述连续检查，不等于复杂表单全部完成或发布验收完成。

## Source-only date request / 未发布日期请求

```json
{"kind":"form_fill","request":{"fields":[{"kind":"date","field_goal":"Date input field","value":"2028-02-29","format":"MM/DD/YYYY"}]}}
```

Choose the format from the actual visible field hint; do not guess locale. All three formats have contract tests; real GUI checks in this slice exercised MM/DD/YYYY only. Readback proves field contents, not server acceptance. / 按真实字段提示选择格式，不猜测地区；三种格式有契约测试，本轮真实页面仅验证 MM/DD/YYYY。读回证明字段内容，不证明服务端接受。

## Same-session live checks / 同会话连续实测

Source root03, using the framework MCP and original screenshots on real W3C component pages; not a locally constructed test UI. / root03 使用框架 MCP 和原图在真实 W3C 组件页面实测，不是自写测试界面。

| Case / 项目 | Request | Seconds / 秒 | Result / 结果 |
|---|---|---:|---|
| Initial Apple / 首次选择 | adv-1790126289445 | 58.071 | UIA matched + visible Apple / 读回及原图一致 |
| Change to Banana / 改选 | adv-1790126363303 | 54.470 | matched |
| Repeat Banana / 重复状态 | adv-1790126418869 | 5.103 | already_satisfied; zero input / 零输入 |
| Missing option / 不存在选项 | adv-1790126424882 | 29.511 | expected form_option_not_visible; opened only / 仅展开后预期中断 |
| Recover Apple / 从展开状态恢复 | adv-1790126455450 | 35.661 | matched |
| Date 09/30/2026 / 日期 | adv-1790126518791 | 27.117 | exact uia_value readback / 精确读回 |
| Replace with leap day 02/29/2028 / 改为闰日 | adv-1790126547355 | 28.226 | exact uia_value + screenshot / 精确读回与原图 |
| Invalid 2026-02-30 / 非法日期 | adv-1790126594506 | 0.002 client / 客户端 | validation_rejected; not queued, zero input / 未入队、零输入 |

The figures are individual command times, not claimed universal latency or success rates. Full-page UIA work is still slow; this slice prioritized correctness and continuous behavior. / 数字为各命令耗时，不代表普遍速度或成功率；全页 UIA 读取仍偏慢，本轮优先修通行为。

Root03 cleanup: both created windows closed via exact framework handles; cleanup.json records host_alive=false, pending_ids=[], cleanup_verified=true, cleanup_errors=[]. First failures in roots01/02 remain preserved, not relabelled as first-pass successes. / root03 两个新窗口经框架确切句柄关闭，宿主/队列/清理已核验；roots01/02 首次失败保留，不改记首次成功。


## 2026-09-23 full-form source update / 整表源码更新

Eight-field Selenium journeys passed twice (107.186 s / 107.442 s), plus native test-file selection, repeated-state checks and failure recovery. Quill Chinese rich-text entry/replacement passed. Select2 keyboard selection retained two values; visual Alaska option localization remains unreliable. / 两轮八项整表、原生测试附件、重复状态和恢复通过；中文富文本替换通过；多选键盘路径保留两值，视觉选项仍有失败，不记为通用多选完成。

Source tests: 1633 passed in 34.57 s. No final submit, private CV upload, package, push or AionUi delegation. test.6 download unchanged. / 未最终提交、上传私人简历、打包或推送，未派独立验收，下载包不变。

See docs/verification/FULL_FORM_SOURCE_ACCEPTANCE.md.
