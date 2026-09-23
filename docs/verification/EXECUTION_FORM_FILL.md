# 表单填写 / Form fill

## 范围 / Scope

日期字段与外置列表适配（未发布源码）见 [复杂表单适配 / Advanced form adaptation](ADVANCED_FORM_ADAPTATION.md)。其中明确区分日期文本录入和未实现的日历导航；这些改动不在 test.6 下载包中。 / Date fields and external-list support are source-only additions, not part of the test.6 bundle.

未发布源码的真实表单标签关联、输入与文件选择修复单独记录于 [调试记录 / Debug record](FORM_LABEL_FILE_PICKER_DEBUG.md)；下文 test.6 验收数字不覆盖这些新增改动。 / Unreleased real-form fixes have separate evidence; the test.6 results below do not validate new changes.

`test.6` 新增 `kind=form_fill`，仍通过既有 `instant_run` / `instant_submit` 使用，不新增 MCP 工具。本功能是网页和原生软件表单，不是 Excel 单元格编辑；学习模式不在此次发布范围。

The test.6 release adds form filling through existing MCP tools. It targets web/native forms, not spreadsheet cells, and does not ship learning. Source, frozen candidate06 and independent AionUi real-form acceptance passed, with retained first-attempt failures and explicit recovery listed below.

## 架构位置 / Architecture

- `app/instant_mcp.py` 的 `InstantCommand` 校验 `kind=form_fill`，复用 `instant_run` / `instant_submit` 与同 request ID 回执读取；会话须先选定目标窗口。
- `scripts/run_local_step_session.py` 分派到 `app/desktop_review/form_fill.py` 的 `FormFillRequest` / `run_form_fill`，按声明顺序执行、记录检查点，并在首个失败处保留部分结果。
- 文本复用 `app/desktop_review/input_sequence.py`，固定 `submit_search=False`；`app/agent/windows_text_field_reader.py` 提供同字段实际值和双读验证。状态控件使用 `app/agent/windows_form_control_reader.py`，在 coordinator 的串行 owner 内只读 UIA，绑定窗口／进程、runtime ID、几何与当前状态；动作仍走既有受控识别单步，不直接调用 UIA 修改模式。
- 未发布源码的显式文本 `label` 优先使用完整当前 UIA 中唯一可写控件的真实中心；身份、扫描完整性或标签不能确认时保留原视觉路径。此选择发生在模型请求前，不能在模型拒绝后改点重试。点击前复验身份，输入后仍须值读回。/ Unreleased explicit text labels may use unique current writable-control geometry before model inference. Incomplete or ambiguous evidence keeps the visual path; no coordinate substitution after model rejection. Live identity and value readback remain required.
- `app/core/local_control_target.py` 在原动作派发前复读当前控件身份、状态和真实边界，限定下拉选项归属；不扩大可点击目标。
- 标准下拉原生弹出层按当前同进程、同根 owner、唯一几何覆盖关系记录精确 HWND；识别前固定、点击前复验后，复用原输入器的 `expected_owned_popup_handle`。不把其他 owned 窗口一律视为目标，也不声称原生 popup 暴露了选项 UIA 子树。`native_popup.rect` 明确为屏幕像素 LTRB。
- `app/operation/screen_reading/uia_graph.py` 共用有限 UIA 图身份契约；仅 COM 身份、稳定属性和规范父边一致的重复节点视为别名。完整图不等于严格树，诊断分别给出 `graph_scan_complete` 与 `provider_tree_valid`。
- `app/api/vision.py` 对小型选择控件的首次裁图保留邻近标签并作最多 3 倍可逆放大，返回原图坐标。下拉选择与可编辑输入提示分开，不将 ComboBox 一律视为输入框。
- `app/instant_receipt.py` 处理 `form_fill_v1` 完整／精简回执；字段完成不等于业务任务成功。通用动作候选绑定及本轮真实表单验收已通过，不代表整批发布验收完成。

`InstantCommand` validates the command on existing tools; select a target window first. The session runner dispatches sequential strict fields to `form_fill.py`. Text reuses `input_sequence.py` without submitting. Read-only UIA runs on the serial owner; `local_control_target.py` rechecks identity, state, exact bounds and option ownership immediately before input. Small selection controls receive label-preserving initial crops and at most 3x reversible enlargement; dropdown selection is not rewritten as editable input. Existing gated recognition steps still dispatch input, never UIA mutation patterns. Receipt formatting separates declared field completion from agent-judged task success. Source live-form acceptance is recorded below; release acceptance is separate.

## 调用 / Request

```json
{
  "request_id": "form-001",
  "command": {
    "kind": "form_fill",
    "request": {
      "fields": [
        {
          "kind": "text",
          "field_goal": "Click the Address input field",
          "text": "https://example.com/"
        },
        {
          "kind": "dropdown",
          "label": "Character Encoding",
          "option": "utf-8 (Unicode, worldwide)"
        },
        {
          "kind": "checkbox",
          "label": "Show Source",
          "checked": true
        },
        {
          "kind": "radio",
          "label": "Group Error Messages by Type"
        }
      ]
    }
  },
  "images": "after",
  "detail": "compact",
  "wait_ms": 25000
}
```

标签和选项只是示例，必须来自当前实际界面／可访问性名称；不得照抄到无关页面。`fields` 已发布 test.6 为 1–12 项，未发布源码为 1–32 项，未知字段拒绝。文本默认替换现有内容，且不会按 Enter 提交。复选框设置 `checked=true/false`，单选框选择指定项；已满足状态不重复点击。下拉框展开后重新读取选项，必须可见且归属于该控件。

Labels/options above are examples, not universal selectors. Supply current accessible names. Released test.6 requests contain 1–12 fields; unreleased source accepts 1–32 strict fields. Text replaces by default without pressing Enter. Checkbox/radio operations set the requested state instead of blindly toggling; satisfied states are skipped. Dropdown choices must be visible and belong to the current control.

下拉展开状态由原始只读模式双读确认，已展开时直接选择，不再点击开关把它收起；未知、部分展开或模式不可用则中断。请求无效选项后，可在核对部分回执和当前状态后发出有效选项的新命令，不会自动重放前一次填写。

The raw read-only expansion pattern is checked twice. An already-open dropdown is selected directly, not toggled closed; unknown, partial or unavailable expansion interrupts. After an invalid option, inspect partial results and current state before issuing a new valid command; no previous input is automatically replayed. Shared `uia_graph.py` normalizes only COM-proven aliases with stable metadata and canonical parent identity; complete graphs and strict trees have distinct diagnostics.

示例是 `instant_run` 参数。`instant_submit` 只提交 `request_id` 和 `command`，不接收示例中的等待和取图参数。`form_fill` 的 command 只允许 `kind` 与 `request`，不接收 `observation_wait_ms` 或 `observation_condition`。文本 `clear_existing` 可显式设为布尔值（默认 `true`）；此请求没有 `submit_search`、提交按钮或任意动作字段。`field_goal` 上限 2000 字符，`text` 上限 20000 字符，`label`／`option` 上限 500 字符；字符串不能为空白，额外字段与类型强制转换均拒绝。

The example is an `instant_run` call. `instant_submit` accepts only `request_id` and `command`, not the example's waiting/image options. A `form_fill` command allows only `kind` and `request`, with no observation wait/condition fields. Text accepts an explicit boolean `clear_existing` (default `true`); no `submit_search`, submit-button or arbitrary-action field exists. Limits are 2000 characters for `field_goal`, 20000 for `text`, and 500 for `label`/`option`. Blank strings, extra fields and type coercion are rejected.

Native dropdown popups are associated by a unique current same-process/root-owner window covering the option geometry. Its exact HWND and metadata are fixed before recognition and rechecked before forwarding to the existing input controller; arbitrary owned windows are not accepted. This is native-owner/geometry evidence, not a claim that the popup exposes an option UIA subtree. Popup rectangles explicitly use screen-pixel LTRB coordinates.

首次 Chromium 内容树为空时，就绪采样预算从首个完整空观察后开始；首扫耗时和总耗时分别记录。后续采样启动预算为 1.5 秒、总观察最多 16 次，同步 COM 调用不可抢占，所以不承诺总墙钟 1.5 秒。只读采样不重放输入。

Initial empty Chromium content receives a 1.5-second budget for starting additional read-only samples, up to 16 observations total. Initial-scan and total elapsed time are reported separately. Synchronous COM calls cannot be preempted; this is not a 1.5-second total wall-clock guarantee and never replays input.

## 回执 / Results

- `completed_fields` 使用从 0 开始的索引；`interrupted_at` 标识停止字段。已执行字段不会自动回滚，后续字段不执行。
- 完整回执保留每个字段的读取与动作证据；精简回执省略嵌套大载荷。
- `completed` 只说明声明的字段检查完成；`task_effect_verified=null`，业务结果仍由 Agent 看原图判定。
- `pending` 不是取消：保持同一 MCP 连接，按返回的 `next` 读取同一个 request_id；不能重新提交整个表单。
- `automatic_retry_allowed=false`：失败不自动重试、跳过或重放；Agent 必须先检查部分执行和当前画面，再决定新的明确命令。`action_executed=null` 表示派发结果未知，不是未执行证明。
- 失败且无法获取当前状态时 after 不可用；历史单步图仍在完整证据中，不冒充最新截图。

Completed indexes are zero-based. Interruption preserves partial execution and does not roll back or run later fields. Full receipts retain per-field evidence; compact receipts omit nested payloads. Task success remains unjudged. Pending requests require reading the same ID on the same connection, never replaying the form. `automatic_retry_allowed=false` prohibits automatic retry, skipping or replay; inspect partial execution and the current image before issuing a new explicit command. `action_executed=null` means dispatch is unknown, not proof that no action occurred. Unavailable current evidence is not replaced with an older image.

## 边界 / Limits

不自动点击提交／发送／付款，不填密码，不承诺支持所有自绘控件、任意跨应用弹出选项、离屏选项或无法读取状态的字段。遇到缺失、重名、目标变化或读值冲突，返回明确错误和部分结果，不猜测是否已填写。文本字段、单选／复选与下拉的原生可访问性契约已在下述真实网站完成连续使用验收，不能用离屏测试数量替代。

No automatic final submission, password filling or universal support for custom/portaled/offscreen widgets. Missing, ambiguous, changed or unreadable controls interrupt with explicit partial results. Real website and continuous-use acceptance is required separately from unit tests.

## 首轮完整验收记录 / First complete acceptance record

表单实机验收时源码回归 **1245 项通过（29.46 秒）**。真实 W3C 表单在同一新建 Edge 会话完成文本、下拉、复选与单选的单项及混合连续填写；重复设置不反选，重名控件中断、无效选项部分中断及从已展开下拉恢复均符合预期。10 条表单命令中 8 条正常完成、2 条预期错误；这不是跨网站准确率。最终窗口关闭、宿主退出，cleanup_verified=true；未提交表单。

At the form live checkpoint, the source suite passed **1245 checks (29.46s)**. A fresh real W3C/Edge session completed individual and mixed continuous text/dropdown/checkbox/radio filling, idempotent state setting, ambiguity rejection, partial interruption and recovery from an open dropdown. Of 10 form commands, eight completed normally and two produced expected errors; this is not cross-site accuracy. The test window and host closed with verified cleanup. No form was submitted.

| 实机命令 / Live command | 耗时 / Wall time |
|---|---:|
| 文本填写 / Text | 10.3 s |
| 下拉展开并选择 / Open and select dropdown | 38.1 s |
| 复选 / Checkbox | 15.9 s |
| 单选 / Radio | 16.0 s |
| 四字段连续改填 / Four-field mixed refill | 84.0 s |
| 三控件状态已满足，无输入 / Three satisfied states, no input | 9.1 s |
| 无效选项后恢复 / Recovery after invalid option | 21.6 s |

数字为本轮 command_wall_ms，不含 Agent 调度；模型首次准备另耗 18.8 秒。此前失败与修复后结果分开保留，不抹成首次通过。当前优先稳定性，不作性能保证。

These command times exclude agent scheduling; initial model preparation took a separate 18.8s. Earlier failures remain distinct from repaired reruns. Stability is prioritized; these are not performance guarantees.

**test.6 尚未发布。** 本轮证明源码路径，不代替冻结包及 AionUi 独立验收。整批 Google/Maps 连续回归、正确冻结包依赖检查与同候选独立验收仍待完成。单个真实网站不证明所有自绘、离屏或不可读控件可用。

**test.6 remains unpublished.** Source acceptance does not replace frozen-package or independent AionUi acceptance. Batch-wide Google/Maps continuous regression, corrected isolated packaging and same-candidate independent acceptance remain pending. One real website does not establish universal widget support.

状态不可用包含供应方成功返回但 checked/expanded 未知：字段 check 标记 unavailable，顶层 after 撤除，嵌套历史保持。相关主代理回归101项通过。 / Unavailable state also includes successful provider reads with unknown checked/expanded: field check is unavailable and the top-level after is removed while nested history remains. Main-agent related regression: 101 passed.

文本组合沿用本次识别候选的 UIA runtime ID、类型、真实框和来源截图摘要进入读值；身份不完整不能退回未绑定猜测。读取失败在完整子步 error.diagnostic 标明有限阶段，不含字段原文。 / Text combinations preserve the selected UIA runtime ID, type, real bounds and source-capture digest for field reads. Incomplete declared identity cannot fall back to guessing. Full child error.diagnostic exposes bounded read stages without field contents.

### Shared text-field regression / 共用文本字段回归

The latest browser regression exposed three separate contracts: complete first UIA scans may lack a rendered page Document; a same-runtime field may widen after typing; plain field names may omit a terminal label colon. These are common runtime fixes, not site aliases. Post-input read-only geometry rebinding and colon normalization now have failure-first tests; a new complete live rerun remains required. A completed valid UIA sample is no longer rejected solely for exceeding a 250ms scheduling budget; that budget limits subsequent read starts and waits, not synchronous COM completion.

新回归发现首扫正文缺失、输入后同字段宽度变化、末尾冒号匹配不一致三类公共问题。只读几何复验与标签修复已补失败回归，仍需新宿主完整实测；250ms限制后续只读采样启动，不将同步调用已完成的正确身份样本误报超时。既有W3C成功保留为历史证据，不替代修复后验收。

## 2026-09-23 current source acceptance / 当前源码验收

Latest source suite: **1396 passed (33.38s)**. Source live-12 passed Google search → Maps → Auckland Museum → Auckland Art Gallery with separate content reads, then a new real W3C window passed text entry, four-field text/dropdown/checkbox/radio fill, repeated desired states with zero input, missing-option partial interruption and open-dropdown recovery. Both owned windows closed; host stopped, pending empty, cleanup_verified=true. This is the first complete rerun on the latest source, not proof that earlier attempts passed.

最新源码1396项通过；第十二轮完整谷歌到地图、两个地点查询读取，再到真实W3C表单四类控件连续填写、重复值无输入、中断恢复全部通过。两窗口与宿主已清理。输入后同身份字段扩宽453→533像素的读值复验通过，原绑定不改写；无自动输入重放或表单提交。此前失败记录保留。

Timings: Google search 14.092s; open Maps 15.487s; two queries 17.850s / 24.519s; W3C text 16.197s; four-field fill 91.862s; three no-op choices 8.022s; expected partial failure 35.506s; recovery 22.146s. These are command wall times, not universal performance claims.

Evidence stays local: 20260923-test6-browser-live-12/acceptance-report.json. Raw screenshots contain unrelated private notifications/history; do not publish. Next: freeze one corrected execution-only candidate, own isolated/package/live checks, then AionUi same-candidate independent acceptance. No release or shutdown yet; learning remains excluded. / 下一步冻结执行候选，完成同包检查与实机复验后才交AionUi；未发布或关机，学习不随包发布。


## 2026-09-23 焦点字段与非最大化窗口 / Focused fields and non-maximized windows

- 通用不变量：键盘输入属于当前焦点字段，不属于输入前的鼠标落点。自动填充弹窗遮住旧点击点时，已绑定字段通过新鲜 UIA 双读核对 HWND/PID、创建时间、runtime ID、类型、框、实际值和焦点；不点击弹窗、不选用自动填充。裸输入、点击前检查和学习 TextInputGuard 不变。 / Keyboard input belongs to the current focused field, not the preceding pointer hit. A private one-command owner scope revalidates the exact live field before select-all, paste and Enter; it does not choose autofill suggestions or alter unbound/click/learning checks.
- 修正原生屏幕窗口原点与截图内坐标的混用；有界完整 UIA canonical alias 扫描保留完整性证据。 / Keep native screen origin separate from capture-local bounds and retain complete canonical-alias evidence.
- 最新源码全量 1486 passed / 32.13s；新宿主非最大化 W3C Address 输入 example.net 为 12.115s，Google 输入/核对/Enter 为 13.905s，原图与回执确认，窗口和宿主 cleanup_verified=true。前两次失败均单独保留，不能记作首次成功。 / Latest source suite and fresh real repaired reruns passed; keep the original failures.
- 本地证据目录为 20260923-test6-bound-keyboard-live；原图含私人自动填充/通知，不发布、不外发。仍须修正冻结包与同包 AionUi 验收，不把源码通过标为已发布。 / Local evidence only; frozen-package and independent acceptance remain pending.

### 2026-09-23 candidate04：非最大化下拉裁剪 / Non-maximized dropdown clipping

1486 项包回归、隔离入口及 MCP 无输入 smoke 通过。Google→Maps 两地点完整链通过；800×1155 非最大化 Address 单项10.214s通过。混合字段24.933s中断：文本已改填、下拉已展开，但第30个 UIA 选项越过截图边界。只读探针证明 UIA 的 IsOffscreen=0 不等于 popup 可视：第21项已部分越过原生 popup，第30项再越 capture；不是目标 utf-8 缺失。后续复选/单选未执行，原图未提交，关闭和宿主 cleanup_verified=true。公共读取器修复中；candidate04 不交付、不交 AionUi。 / Package checks and Maps passed, but mixed forms exposed a generic option-viewport contract failure. Text/opening happened; later fields did not. Preserve failure and verified cleanup; no release or independent dispatch yet.

### 下拉视口公共修复与复验 / Generic dropdown viewport repair

完整遍历并核对归属后，仅向动作层提供当次唯一原生 popup 与捕获窗口共同包含的完整选项框。供应方误报 visible 的裁切／滚动外项不作为候选，不剪裁造点，不自动滚动；缺失或无效几何仍报错。窗口内普通非原生选项保留既有路径。 / Complete traversal now filters options by the verified native popup and capture viewport without synthetic clipping, guessed points or automatic scrolling; invalid geometry still fails.

1499 项源码回归 /32.20s。非最大化真实 W3C：单项下拉26.443s；四类混填64.191s；重复状态6.323s且零输入；预期缺选项中断25.112s；从已展开项恢复15.646s；清理true。首次失败仍保留，候选04已取代。 / Fresh real repaired rerun passed including expected partial failure and explicit recovery; the failed frozen candidate remains historical.


### candidate05：同包连续验收 / Same-package continuous acceptance

冻结包1499项回归 /33.79s，隔离入口与MCP smoke通过。真实800×1155非最大化W3C四类混填65.692s、重复状态6.302s且零输入、预期缺选项中断25.061s、已展开下拉恢复16.073s；Google搜索14.542s→Maps15.639s→两个地点17.088/25.067s及独立内容读取均通过。模型释放425ms→重新准备7.616s→再释放314ms，resident_model_count=0。两自建窗口关闭，宿主退出、pending为空、cleanup_verified=true。/ Frozen package regression, entrypoint, smoke, real continuous forms/searches and model reload/release passed; owned windows and host cleaned.

测试客户端曾给read_text多传request字段，结构化validation_rejected后在同一连接改正读取通过；非框架崩溃、未重放输入。首次候选失败仍保留。原始证据仅留本机，不公开私人通知/历史。/ A client-only extra read_text argument was rejected clearly and corrected without input replay. Preserve prior candidate failures and private evidence locally.

AionUi独立验收已投递：aion-test6-form-candidate05-20260923，尚未收到结论；test.6仍未发布，学习不随包发出。/ Same-candidate independent acceptance dispatched, not yet accepted or published; learning excluded.


### 独立复测后的公共修复 / Repairs after independent acceptance

1544项源码回归 /32.92s通过。小型唯一当前UIA listitem复用可逆上下文放大，不放宽目标框；真实ISO8859单项25.934s、四字段64.215s、无操作6.253s、预期中断24.481s、同ISO8859恢复16.120s通过。明确裸字段名词进入既有身份绑定；Aion原措辞的Maps两次input_sequence 9.045/10.470s通过，独立读取确认两个地点。/ Small-listitem context and bare-field identity fixes passed source regression and real single/continuous reruns.

搜索结果的短标题与泛化描述仍可能和搜索框/复合链接名称冲突；本轮两次无输入拒绝后，使用回执返回的完整链接身份成功。该记录不是首次通过，也不代表任意自然语言都能定位。源码窗口与宿主均清理true。候选06待同包与针对性独立复验，不将候选05总结的PASS当作新修复的证据。/ Two incomplete link goals were refused before explicit full-identity disambiguation succeeded; preserve them separately. Candidate06 acceptance remains pending.

## 最终验收摘要 / Final acceptance summary

2026-09-23：源码 **1544/1544**（32.92s）、冻结 candidate06 **1544/1544**（33.92s）、隔离入口与真实 MCP 无输入 smoke 通过。Codex 先完成真实单项与连续实测，AionUi 随后独立复验同一冻结运行时。

Source and frozen candidate06 each passed 1544 overlapping checks, isolated entrypoint and MCP smoke verification. Codex real single/continuous runs preceded independent AionUi retesting; no universal accuracy claim.

| 项目 / Case | Codex frozen candidate06 | AionUi independent candidate06 |
|---|---|---|
| W3C text + dropdown + checkbox + radio | 65.849s, completed | 76.267s, completed; independent UIA readback agrees |
| Already satisfied selection state | 6.386s, zero input | 7.022s, zero input; no toggle reversal |
| Missing option / recovery | Partial interruption 25.198s; valid option from open popup 15.643s | ISO8859 → UTF16 26.139s → ISO8859 26.832s; original failed option now passes |
| Google search → real Maps result | 10.525s + 7.802s | 7.924s + 9.626s, observed full link identity |
| Maps two-place input_sequence | 8.992s + 10.660s, result reads verified | First focus refused 4.442s, zero input; explicit identical retry 9.129s passes; second place 12.642s passes |
| Close created windows / stop | Host false, pending empty, cleanup true | Host false, pending empty, cleanup true |

**首次失败不能抹去。** 独立 Museum 首次模型点映射 (79,116)，真实字段 (84,103,206,24)，偏左5px；裸字段解析已生效，错误点仍被拒绝，没有输入。明确观察后重试通过，只算恢复成功，不算首轮命中，没有放宽框或添加盲重试。

**Retain the first failure.** The model point was 5px outside the actual field, not a coordinate transform/parser regression. Zero input followed; explicit agent-reviewed retry succeeded. No bounds relaxation or automatic replay was added.

Limits: current-visible dropdown options only; no final submission, Excel editing or learning. SDK outer schema/start-order errors can lack structured diagnostics. Browser launcher PID may differ from actual window PID; pair window.handle with window.process_id. Friend-machine cleanup remains a compatibility retest, not a universal fix.

边界：下拉仅选当前可见项，不自动滚动；不提交、不做Excel编辑、不发布学习。SDK外层参数/启动顺序错误可能只有工具错误；launch进程与窗口进程可不同，使用同层handle/PID。朋友电脑原始清理失败尚待同机复测。

Local evidence identifiers (raw images/logs not published):
- Codex source: 20260923-test6-form-model-correction; package: 20260923-test6-candidate06-live.
- Independent: 20260923-test6-aion-candidate06, report SHA-256 f4365e0d682525f20b0012620a95057585b15d86f153cfdcccd1fbe9368479f4.
- Stored field readbacks, original PNG, command receipts and final cleanup were checked, not only the agent summary.


## 2026-09-23 full-form source update / 整表源码更新

Eight-field Selenium journeys passed twice (107.186 s / 107.442 s), plus native test-file selection, repeated-state checks and failure recovery. Quill Chinese rich-text entry/replacement passed. Select2 keyboard selection retained two values; visual Alaska option localization remains unreliable. / 两轮八项整表、原生测试附件、重复状态和恢复通过；中文富文本替换通过；多选键盘路径保留两值，视觉选项仍有失败，不记为通用多选完成。

Source tests: 1633 passed in 34.57 s. No final submit, private CV upload, package, push or AionUi delegation. test.6 download unchanged. / 未最终提交、上传私人简历、打包或推送，未派独立验收，下载包不变。

See docs/verification/FULL_FORM_SOURCE_ACCEPTANCE.md.


未发布源码的 32 项组合、可选 Tab 连续输入及真实失败修复见 [批量修复 / Batch repairs](BATCH_FORM_REPAIRS.md)。实机已按用户要求暂停，不把离线通过写成实机通过。
Unreleased 32-field batches, optional Tab continuation and repair evidence are documented separately; live validation remains pending.
