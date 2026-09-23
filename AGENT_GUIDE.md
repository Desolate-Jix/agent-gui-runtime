# Agent 接入与操作 / Agent usage — v0.1.0-test.7

**适用于 test.7 执行模式测试包。** 不要向旧包发送新增字段；先核对服务端版本。/ For the test.7 execution preview. Check server version before using new fields with older bundles.

## test.6：通用应用启动 / Installed applications

本节适用于 test.6；旧 test.5 包不包含新增接口，不需要为每个软件注册 MCP。 / Available in test.6, not older test.5 bundles. Apps do not need separate MCP registration.

`instant_run` 示例 / Examples:

```json
{"request_id":"app-01","command":{"kind":"launch","name":"Character Map"}}
{"request_id":"app-02","command":{"kind":"launch","path":"C:\\Tools\\Example.exe"}}
{"request_id":"app-03","command":{"kind":"launch","path":"C:\\Users\\YourName\\Desktop\\Example.lnk"}}
```

- `app_id/name/path` 三选一；名称先精确匹配（含别名），再部分匹配。有多个候选返回 `diagnostics.candidates`，明确选择 app_id，不取第一项猜测。 / Exactly one selector; choose an explicit candidate when ambiguous.
- `discover` 有界枚举用户/公共开始菜单、桌面快捷方式及 App Paths，不扫描整个磁盘；便携软件使用绝对路径。 / Bounded discovery, explicit paths for portable apps.
- `prefer_existing` 默认 true：无 URL/启动参数时复用唯一且身份匹配的现有窗口；多个窗口需 select。传 false 显式启动；带 URL/参数不会只聚焦而吞掉参数。 / Reuse unique identity-matched windows only for argument-free launches; preserve URL/argument semantics.
- `focused + reused_existing_window=true + launch_dispatched=false` 表示复用，用户原窗口不会因此获得会话清理所有权。不同 cwd 的快捷方式仍是不同候选，预览保留实际 cwd。 / Reuse does not grant cleanup ownership; distinct working directories remain distinct and visible in preview.
- `launched_window_ready` 只代表新窗口身份匹配。UWP 专用链接及转交不同 exe 的启动器暂不保证；unknown/unavailable 后先检查旧回执和 discover，不盲目重启。 / Dispatch is not readiness; inspect uncertain launcher outcomes without blind replay.
- 桌面可先 `desktop_capture`，再 `desktop_click`，request 包含 goal 和 `click_kind:"double"`。不用先 select，但内部仍绑定真实桌面宿主、新截图识别，不接受裸坐标。打开后 discover/select 新应用。 / Desktop commands resolve shell identity and use fresh recognition, not unbound raw coordinates.


**输入框聚焦行为 / Input-field focus behavior:** 普通“点击输入框”与结构化 input 目标现在也要求模型定位可编辑区内部，避免边框、占位文字字形或相邻搜索按钮；原目标标签保留。按钮/图标/框内单词不因此改成聚焦整个字段。仍须读图核对焦点、实际文字与跳转，派发不等于成功。仍须按回执与原图独立核验。/ Plain field-click goals and structured input targets now request interior focus without changing the original label or word/button/icon targets. Inspect actual focus, text and navigation; dispatch is not success. Verify the result independently from receipts and original images. [实测边界 / Limits](docs/verification/EXECUTION_INPUT_FOCUS.md).

test.6 的历史独立验收见 docs/verification/TEST6_CANDIDATE_ACCEPTANCE.md，不沿用为 test.7 通过证据。新表单源码实测见 [批量填写记录](docs/verification/BATCH_FORM_LIVE_ACCEPTANCE.md)。/ Historical test.6 acceptance does not validate this candidate; see the separate source batch-form evidence.

## 执行契约 / Execution contracts

- 精确网页链接可用 `Click the result link labelled "完整可见标题"`；唯一性按本帧范围核对，完全离屏同名项不冒充可点目标，部分可见重名仍参与消歧。点击后仍须读原图确认网址/正文变化。 / Exact quoted links use current-frame identity; inspect post-images for navigation rather than trusting dispatch. See docs/verification/EXECUTION_BROWSER_RETEST_20260921.md.

- 显式按钮标签可写 `Click the '不保存' (Don't save) button`；保留否定文字、角色和快捷键后缀。只有同帧完整 UIA 树的唯一精确按钮才约束首次模型 ROI，不能用此语法掩盖多个候选。 / Quoted labels preserve identity and role; unique exact current UIA buttons seed the initial model ROI. [定位边界 / Limits](docs/verification/EXECUTION_QUOTED_BUTTON_TARGET.md)。
- 后图缺失且 `recovery.status=process_not_running` 表示目标进程已不在，不代表正常关闭或任务成功。保留原回执、核对任务效果，不重放输入；权限错误或其他窗口的枚举错误不能解释为退出。 / Target process absence is an observation, not effect verification or authorization to replay.

- 23 种按键包括原有 15 种及 `Shift+Left/Right/Up/Down/Home/End`、`Ctrl+Home/End`。只作用于当前目标焦点，x/y 不会先点击。 / Eight selection/document-boundary chords augment the existing fifteen; coordinates do not focus the field.
- 排名是分数诊断，`recommended_candidate_id` 才是明确推荐身份，不要自行取 `candidates[0]` 替代。`current_control_ocr_text_center` 是本次真实 OCR 文字中心，原模型点另行保留；这不等于任务已成功。 / Preserve explicit selection and coordinate provenance; neither ranking nor dispatch proves task effect.
- 浏览器 `browser_document_observation` 的空正文状态不等于页面空白或加载完成；先读原图，不能按旧图坐标配新控件，也不自动重放。 / Empty UIA is not an empty/ready page; inspect current images without mixing observation generations.
- 窗口、词级与观察恢复契约已纳入 test.4；链接文档中的早期源码状态属于历史记录。 / Window, word and observation contracts shipped in test.4; earlier source-only entries in linked documents are historical.

**test.5 窗口观察 / Window observation：** `close_launched_window` 等待时增加 `close_observation` 和 `next_action`；收到 `inspect_owned_window` 后保持会话，读取并选择确切弹窗，解决已授权选项后再核验原窗口消失。动作关闭目标时，派发成功与事后图缺失必须分开判断，不根据外层 `operation_succeeded=false` 重放；先检查退出诊断；目标仍存在时才明确选窗补图，已退出时不要重新选择不存在的窗口。`instant_stop.cleanup_verified` 只代表宿主收尾。 / Pending closure now carries owned-window diagnostics; inspect the exact dialog, resolve an authorized choice and verify disappearance before stopping. Dispatch may succeed with unavailable post-images; inspect rather than replay. [详细契约 / Details](docs/verification/EXECUTION_WINDOW_TRANSITIONS.md)。

本包只提供即时操作，不是学习桥。按用户指定的低风险任务使用本包接口，不使用另一套鼠标工具冒充本包测试。快捷入口使用管理员宿主且自动风险拦截关闭；一次只允许一个 Agent 控制桌面。付款、发送、删除、最终提交等不可逆操作不在本次测试范围。

Instant-mode operations only, not learning. Use this framework for the user's supervised low-risk task; do not substitute another input backend and claim package coverage. Quick setup uses an administrator host with automatic risk interception disabled. Only one Agent may operate the desktop. Payments, sending, deletion and final submissions are outside trial scope.

## 撤销的判定 / Undo interpretation

`Ctrl+Z` 派发应用原生撤销键，不保证事务回滚或清空文档；按当前应用内容和选区核验效果。同样截图不代表同样撤销历史，不要把它当成测试环境重置，也不要因未清空自动重复按键。 / Ctrl+Z invokes native application undo, not guaranteed rollback or fixture reset. Inspect content and selection; identical screenshots do not imply identical undo history. Do not replay automatically.

**源码恢复契约 / Source recovery contract:** `keyboard_target_not_foreground` 携带拒绝当刻两个 HWND，`phase=not_dispatched` 只证明没有派发该按键；先处理/取消已识别的弹窗，再选择目标并看图，用新请求继续。取消关闭后可明确再次调用 `close_launched_window`；同一模态等待不重复关闭，`instant_result` 查询不产生关闭动作。 / Inspect and resolve the actual focus/modal state before a new request; a new explicit close can follow observed modal dismissal, while receipt reads and pending-modal checks never resend. [边界 / Limits](docs/verification/EXECUTION_FOCUS_RECOVERY.md)。

**明确单词目标 / Explicit word targets（test.5）：** `Double-click the word "East" at the end of the line` 会保持词级目标并使用独立词框；不要把整行框或模型点当作目标命中证据。双击可能包含尾随空格，替换前读取实际选区或原图，效果不明时不自动重放。 / Preserve word identity, inspect actual selection and trailing whitespace before replacement, and never infer success from dispatch. [实测边界 / Limits](docs/verification/EXECUTION_WORD_CONTEXT_FIX.md)。

**窗口观察恢复 / Window observation recovery：** `operation_success_scope=input_route_only` 时，`operation_succeeded` 只描述输入路由，仍须检查 `observation_status` 和 `agent_review`。旧窗口 after 缺失会返回 `evidence_incomplete` 和 `recovery.candidates`；按任务明确选窗再查看新请求的截图，不重放原输入，也不把同进程窗口自动当后继。 / Inspect input and observation separately; explicitly select and inspect a recovery candidate without replacing old evidence. [完整契约 / Contract](docs/verification/EXECUTION_OBSERVATION_RECOVERY.md)。

## 连接顺序 / Connection sequence

**解释器一致 / One interpreter:** MCP服务及OCR取证脚本都使用本包安装后的 `.venv\Scripts\python.exe`（Python3.11，`rapidocr-onnxruntime==1.4.4`）。不要使用PATH里的其他 `python`；旧OCR1.2.3不提供词级元数据。出现缺字符元数据错误时报告解释器路径和OCR版本，不跳过错误或改用整行框充当单词定位。 / Use the locked package venv for services and helpers; old OCR1.2.3 lacks word metadata. Report interpreter/version on this error instead of weakening geometry validation.

**客户端常见错误 / Client pitfalls:** `instant_submit` 返回 `pending` 不是操作失败或最终回执；只轮询原 request_id 的 `instant_result`，不要重复提交动作。已停止会话不会被默认 `instant_start()` 自动重开，需要显式 `new_session=true`。正常结束时，在断开 MCP 前用 `close_launched_window` 关闭本会话启动的测试窗口，再 stop 并轮询清理状态。 / Pending requires polling, not replay. Explicitly request a new session after stop; close session-owned test windows before stopping/disconnecting.

1. `instant_start(new_session=true)`，随后查询 `instant_status`，等 `phase=ready`。同一任务保持同一 MCP 连接；断连会触发宿主收尾。 / Start a fresh session, poll until ready, and keep one continuous MCP connection for the task. Disconnect initiates host cleanup.
2. `instant_submit` 提交 `discover`，使用同一个 request_id 轮询 `instant_result`，从回执读取真实窗口与应用目录。 / Discover real windows and app catalog; poll the submitted ID.
3. 按实际返回值 `launch` 或 `select`，再 `capture` 并取原图。`select` 会切前台，不猜 HWND/PID。 / Launch or select an observed target, capture, and inspect the original image. Selection changes foreground; never invent HWND/PID.

```json
{"request_id":"discover-001","command":{"kind":"discover"}}
```

`launch` 使用发现结果里的 app_id，可附 url；`select` 使用真实 handle、process_id；`maximize`、`capture` 针对已选窗口。`prepare_models` 可在连续任务前预热一次，`release_models` 释放模型。不要把每次冷启动耗时当成热启动点击耗时。

Launch uses an observed app_id with optional url; select requires real handle/process_id. Maximize/capture use the selected window. Prepare models once for a continuous task and release them when appropriate; cold-start timings are not warm-click timings.

## 组合动作 / Input sequences

**自 test.5 起提供 / Available since test.5.** test.5 提供第七个工具 `instant_run`，接受原命令和 `kind=input_sequence`；默认有限等待后一次返回精简回执与原始后图。836 项测试、真实 Google 连续搜索及只填写已验证；不是跨站点准确率或整体提速保证。完整示例、部分完成与超时读取契约见 [组合动作说明 / Input sequences](docs/verification/EXECUTION_INPUT_SEQUENCE.md)。test.5 provides this entrypoint; older six-tool packages do not. / The seventh tool bundles a bounded wait, compact receipt and original after image. 836 tests and bounded Google continuous/fill-only cases passed; this is not cross-site accuracy or end-to-end speed assurance. Earlier test.4 has only six tools and does not support this entrypoint.

组合仅限 Agent 已决定的“聚焦字段 → 输入 → 核对 → 可选 Enter 搜索”。不要把需要观察后重新决策的结果点击提前加入，不把 `completed` 当成搜索结果正确。`pending` 不等于取消；沿用原 ID 读取，保持 MCP 连接。 / Group only already-decided field input and optional search; inspect the result before choosing a result link. Completion is not task success, and pending is not cancellation. Keep the connection and read the same ID.

## 表单填写 / Form fill（test.7）

`kind=form_fill` 支持最多 32 项文本、日期文本、下拉选项、复选状态和单选，按声明顺序填写，不自动提交。一个批次应尽量包含当前已知字段，避免每字段一次 Agent 往返。失败看 `completed_fields`、`interrupted_at`、`remaining_fields` 和原图；不要重放已完成字段。/ Declare up to 32 known fields in one ordered batch to reduce agent round trips. Read partial progress and images on interruption; never replay completed fields. See [完整协议 / Contract](docs/verification/EXECUTION_FORM_FILL.md).

```json
{"request_id":"form-batch-01","command":{"kind":"form_fill","request":{"text_navigation":"tab_sequence","fields":[{"kind":"text","field_goal":"Customer name:","label":"Customer name:","text":"Test Person"},{"kind":"text","field_goal":"Telephone:","label":"Telephone:","text":"0000000000"},{"kind":"text","field_goal":"E-mail address:","label":"E-mail address:","text":"test@example.invalid"}]}},"images":"after","detail":"compact","wait_ms":25000}
```

此例为 `instant_run`，只适用于已观察到的相同标签与 Tab 顺序。默认 `text_navigation=recognize_each` 可混合字段；`tab_sequence` 只接受具名文本，首项定位后每次 Tab 复验下一标签，不对错误焦点继续输入。完整当前 UIA 唯一可写字段可在模型调用前提供真实中心；证据缺失保留视觉路径。/ This example uses `instant_run` and observed labels/order. Default recognize-each supports mixed fields. Tab mode accepts labelled text only, verifies each next focus, and stops on mismatch. Unique current writable-control geometry may be used before inference; missing evidence retains visual localization.

日期示例：`{"kind":"date","field_goal":"Click the input labelled \"Date picker\"","value":"2026-10-15","format":"MM/DD/YYYY"}`。仅日期文本录入与读回，不自动点击日历。文件选择仍是独立流程：按钮→发现并选择原生文件窗口→填写用户批准的确切测试路径→核对→打开→重新选择原表单检查附件名；可能即时上传，不等于最终提交。/ Dates are formatted text input/readback, not calendar navigation. File selection remains an explicit native-dialog journey and may upload immediately; it is not final form submission.

文件控件不是普通文本字段：不要对网页 `File input` 使用 `kind=text` 期待弹出文件窗口。先用 `execute_recognition_plan` 点击当前可见的选择文件按钮，再用 `discover` 取得新对话框的真实 `handle/process_id`，`select` 后才能填写对话框内的文件名。窗口关闭后重新选择原网页并截图核对附件名；无事后帧不等于没执行，禁止盲目重放。原生带助记字母的完整标签如 `打开(O)` 应保留，建议用引号明确标签；修复支持动作宾语中的未加引号助记标题，不将后置用途 `to confirm the file` 当作另一个目标。/ A browser file picker is not a text field. Recognition-click its visible button, discover and select the actual native dialog, then fill its filename. Rebind the web window and inspect the filename after closure. Missing post-action imagery is not proof of no action; do not replay blindly. Preserve full mnemonic captions such as `打开(O)`, preferably quoted. Bare mnemonic action objects are recognized without interpreting a trailing purpose as another target.

`select` 的 `handle`、`process_id` 与 `kind` 同层；`press_key` 的 `x/y` 必填，为当前绑定窗口原图像素。`launch` 不保证有图，后续用 `capture` 观察。/ Put select's handle/process_id beside kind, not inside request. press_key requires x/y in the bound window's current image pixels. launch need not include an image; capture afterward.

## 单步输入 / Single-step input

每次只提交一个动作，回执返回并看图后再决定下一步。以下坐标仅为示例，必须替换为当前原始窗口截图上的像素坐标，不是桌面坐标或缩略图坐标。

Submit one action at a time, await the receipt and inspect images before proceeding. Example coordinates must be replaced using the current original window image, not desktop or thumbnail pixels.

```json
{"request_id":"click-001","command":{"kind":"step","operation":"execute_recognition_plan","request":{"goal":"Click the button labelled Search","task":"click_target"},"observation_wait_ms":2000}}
```

```json
{"request_id":"type-001","command":{"kind":"step","operation":"type_text","request":{"text":"Google Maps","x":500,"y":300,"click_before_typing":true,"clear_existing":true}}}
```

```json
{"request_id":"enter-001","command":{"kind":"step","operation":"press_key","request":{"key":"Enter","x":500,"y":300},"observation_wait_ms":2000}}
```

```json
{"request_id":"scroll-001","command":{"kind":"step","operation":"scroll","request":{"direction":"down","wheel_clicks":3,"x":500,"y":400}}}
```

`type_text.clear_existing=true` 显式替换已有内容，默认 false；不会自动回车或提交。`press_key.key` 精确支持：

`Enter`, `Tab`, `Shift+Tab`, `Escape`, `Backspace`, `Delete`, `Left`, `Right`, `Up`, `Down`, `Home`, `End`, `Ctrl+A`, `Ctrl+Z`, `Ctrl+Y`。

test.5 支持 `Shift+Left/Right/Up/Down/Home/End`、`Ctrl+Home/End`，共 23 种支持键；旧 test.3 不支持新增的 8 种。单项与连续测试的覆盖不同，详见发布记录。 / test.5 supports 23 keys including these eight new chords; do not send the additions to test.3. See release notes for single-operation versus continuous coverage. See [selection keys](docs/verification/EXECUTION_SELECTION_KEYS.md).

按键发给当前焦点；其 x/y 只用于窗口点校验，**不会点击或重新聚焦**。先通过截图确认焦点；切字段用 Tab/Shift+Tab。应用可能不支持撤销/重做，不把按键派发当作生效。不支持任意组合键、shell 或隐式 submit。

Explicit clear_existing replaces text; default false, without implicit Enter/submit. Keys above go to current focus. Their x/y do not click or refocus. Confirm focus, use Tab/Shift+Tab to change fields, and inspect results. Undo/redo support depends on the app. Arbitrary chords and shell commands are unsupported.

## 右击、双击和读取 / Right-click, double-click and reading

`request.click_kind` 为 `single`（默认）、`right`、`double`。右键只是打开菜单；查看原图后另发单击菜单项。双击只选目标词的效果必须看图确认，不能只看点击次数。 / Use single (default), right or double. Inspect the menu before a separate item click; verify actual word selection from images.

```json
{"request_id":"right-001","command":{"kind":"step","operation":"execute_recognition_plan","request":{"goal":"Right click inside the search input box","click_kind":"right"}}}
```

```json
{"request_id":"double-001","command":{"kind":"step","operation":"execute_recognition_plan","request":{"goal":"Double click the word Rotorua inside the search input box","click_kind":"double"}}}
```

```json
{"request_id":"read-001","command":{"kind":"read_text","max_chars":10000}}
```

`read_text` 的文字在 `receipt.result.text`，行框在 `receipt.result.lines`，原图信息在 `receipt.result.capture`；不是输入动作的 `response.data.result`。用同一request_id调用 `instant_image`。只读当前可见像素，`read_complete=false`不表示调用失败。 / Read results use the direct result/text/lines/capture contract, not the input-action envelope; retrieve the same ID's image. Visible pixels only; read_complete=false is not a command failure.

## 可恢复错误 / Actionable errors

`step.observation_wait_ms`只允许0–2000毫秒。先按工具schema检查参数；MCP外层schema拒绝可能是`isError=true`的文本块，而不是JSON业务回执。保留原始文本及字段名，不用JSON解析异常覆盖它，也不要把未入队请求算作执行失败后的重放。 / The observation-wait range is0–2000ms. Transport/schema rejection may be a plain-text MCP error rather than a JSON operation receipt. Preserve the raw error and invalid field instead of replacing them with a JSON parsing exception.

- 非法字段返回 validation_rejected，包含字段位置/允许字段；原填写值不回显。修正参数后再提交，不退出连接或重复加载模型。
- 宿主未就绪、已有命令处理中或正在关闭时返回 state_rejected 和 next 查询指引，不把被拒请求写入执行队列。
- 多候选或无有效坐标会返回候选诊断；使用当前证据明确目标，不凭候选列表盲点。
- 已输入但后图采集失败时，回执保留 error_code 和 capture_current_state_without_replaying_input 指引；先单独 capture，不能假定尚未输入。

Runtime command validation returns structured errors without echoing input values. SDK-level outer schema or pre-start invocation errors may instead be generic tool errors; do not include sensitive values when reporting them. Lifecycle admission rejections return status/result guidance where available and do not enqueue input. Ambiguous targeting returns candidate diagnostics. A post-input capture error calls for a separate capture, not another input attempt.

## Agent 判断结果 / Judge the outcome

### 回执取值 / Parsing receipts

先解析 MCP 文本块中的 JSON，不把调用方日志包装的 `parsed`/`value` 当成服务端字段。等待 `status=returned` 后，完整单步识别回执的操作细节位于 `receipt.result.response.data.result`；错误或未完成回执可能没有这一层，先检查状态和错误。表单完整回执读取 `receipt.result.fields`、`receipt.result.completed_fields`、`receipt.result.interrupted_at`；默认精简回执对应 `receipt.form.fields`、`receipt.form.completed_fields`、`receipt.form.interrupted_at`，不经过单步的 `response.data.result`。识别点击的 `selected_click_point` 为 `{"x":333,"y":132}`；`resolved_click_point.bbox` 为 `{"x":310,"y":123,"w":47,"h":18}`，**不是数组**。按键名读取，不能用 `[int(v) for v in bbox]`；那会把 `x` 等键名当数字。示例数字仅说明结构，不可作为操作坐标。

Parse the MCP JSON text, not client-log wrappers such as `parsed`/`value`. Completed full single-recognition-step details live at `receipt.result.response.data.result`; failed/pending receipts may omit it. Full form receipts instead use `receipt.result.fields`, `receipt.result.completed_fields` and `receipt.result.interrupted_at`; default compact form receipts use `receipt.form.fields`, `receipt.form.completed_fields` and `receipt.form.interrupted_at`. Points and rectangles are named-key objects, not arrays. Never reuse these illustrative coordinates. For screenshots, prefer the top-level `receipt.agent_review.before/after` tool arguments; do not recursively pick the first matching diagnostic field.

### 自行裁剪和OCR取证 / Client-side crops and OCR

识别点击的上述矩形使用 `x,y,w,h`；`captured_text_v1.lines[].bbox` 则使用 `x,y,width,height`，按具体契约读取，不混用键名。例如 Pillow `Image.crop` 要求 `left,top,right,bottom`，将宽高转换为 `(x,y,x+w,y+h)`，并检查区域在当前原图内、宽高大于零。不能直接传 `(x,y,w,h)`，也不能把上一轮截图坐标用于新截图。 / Recognition rectangles above use `x,y,w,h`; captured-text line boxes use `x,y,width,height`. Follow the specific contract, then convert dimensions to Pillow `(x,y,x+w,y+h)`. Check positive dimensions and current-image bounds; do not reuse an older capture's coordinates.

外部OCR进程非零退出、缺输出或JSON解析失败是**取证工具错误**，必须保留退出码和stderr，不能转换为“未识别到文字”或产品操作失败。 / Nonzero exit, missing output or invalid JSON is an **evidence-tool error**, not empty OCR or a proven product failure.

判断文本选区时只看目标输入行；不要合并浏览器标题、正文中的同词框。右键菜单可能遮住原文字，菜单展开图不适合作为唯一选区基线：优先使用本次打开菜单前的原图和全选后的原图，菜单关闭仅作辅助证据。未确认选区就停止后续替换，但把原因准确区分为操作失败或证据不足。 / Scope selection checks to the input row. Use the current pre-menu image as the unobscured baseline, not solely the menu-open frame; separate action failure from insufficient evidence.

- `returned` / `operation_succeeded` 只说明命令与输入链状态，不证明任务成功。识别点击的 `verified=null` 与 `retry_reason=awaiting_agent_review` 表示等待你的判断，不自动重放。
- 读取 `instant_result.agent_review`，分别执行 before/after 中的 `instant_image` 参数。默认 `view=after` 兼容旧调用；原 PNG 不缩放且验证 SHA-256。
- 主证据对是 `before_input` / `after_settled`；内部诊断的 `before_immediate` / `after_immediate` 和 diff 是另一组帧，**不可混用**。主证据没有额外服务器 diff；等待后图不保证渲染结束。
- 根据目标和图像报告 success / failure / uncertain，并说明可见依据。没有变化可能是目标原本已选中；画面变化也不证明点中了目标。文字部分匹配不等于完整目标身份验证。
- `evidence_incomplete`、结果未知或图不可读时，不猜成功、不盲目重试；可单独提交新的 capture。Agent 结论保留在其会话，本版没有服务端判定写回工具。

Returned/operation_succeeded describes command/input handling, not task success. Retrieve both original frames via agent_review. Compare the primary before_input/after_settled pair against the goal and report success/failure/uncertain with evidence. Immediate diagnostic diffs belong to a different pair. No change can be valid; change alone is not success. Missing evidence requires inspection or a separate capture, not replay. Agent judgements remain in its conversation.

## 重连与结束 / Reconnect and stop

**test.6 修复 / Fix:** `cleanup_pending` 表示原宿主保留所有权、等待清理，不是已停止。读取清理诊断、解除阻塞后，再调用 `instant_stop` 只重试清理并轮询状态；不会重放输入。不要持续盲目调用 stop，也不要删除会话记录以绕过 `previous_session_not_resolved`。宿主日志可能记录 `cleanup_report_error` / `cleanup_signal_error`；日志写入失败时不能用旧 report 判断已结束。已卡死的旧版本宿主不因修改源码而恢复。

`cleanup_pending` retains the original owner until cleanup can be verified. Inspect diagnostics, resolve the blocker, then explicitly call `instant_stop` to retry cleanup only and poll status. Never replay input or delete session records. Report/signal I/O failures may leave a stale report; previously stranded old-version hosts are not retroactively repaired. See [lifecycle evidence and limitations](docs/verification/V5_MODEL_CLEANUP_FIXES.md).

请求 ID 在会话内唯一。同 ID、同命令读取原回执；不同命令不得复用 ID。`pending` 继续查询原 ID，`result_unknown` 先检查现场，不能当作没执行。

先提交 `command={"kind":"close_launched_window","handle":本次launch返回的handle,"process_id":本次launch返回的process_id}` 正常关闭自己的测试窗口；不要填写用户原有窗口。随后调用 `instant_stop`，轮询 `instant_status`，直到 `cleanup_verified=true`，最后断连。第一次返回 false 可能只是仍在清理，不是终态失败。重连先用 `instant_start()` 附着历史；确实需要新任务且旧会话清理完成后才用 new_session=true。

IDs are unique per session. Reusing an ID retrieves its original receipt and never authorizes replay with different content. Poll pending IDs; unknown results may already have affected the target. Stop and poll until cleanup_verified=true. A transient false is not a final cleanup failure. Reattach before requesting a fresh session.


### 读取实际执行结果 / Read the actual execution result

不要递归抓取第一个 `action_executed`：`recognition_plan.execution_path` 是 planning 快照，实际输入读 `response.data.result.execution_path`、`agent_step_result` 与 `click_result`。目标关闭后 after 不存在不是未派发，也不独自证明成功，需核对当前窗口状态。 / Planning snapshots are not execution receipts. Read the actual execution fields and independently check task effects and target exit.


**可选条件等待，自 test.5 起提供 / Optional conditional wait, available since test.5:** 在 `step` 或搜索型 `input_sequence` 的 command 中提供 `observation_condition={"text":"准确的可访问名称","control_type":"Text"}`，并设正数 `observation_wait_ms`（最高2000）。只接受明确名称和角色；不知道准确标志时省略，不猜名称。`condition_met` 不等于任务成功或全页渲染完成；`timed_out` 不代表输入没执行，不自动重放。同步 UIA/截图 I/O 不受轮询预算硬中断。 / Supply an exact accessible name and role only when known; otherwise omit the condition. Condition success is not task/full-page success, and timeout must not trigger input replay. Polling budgets do not hard-interrupt synchronous UIA/capture I/O. [完整契约与实测 / Contract and tests](docs/verification/EXECUTION_CONDITIONAL_WAIT.md)。


请求ID必须为1–80位小写ASCII字母/数字/下划线/连字符，首位为字母或数字；非法ID返回invalid_request_id，不入队，修正后沿用同一连接。条件应选稳定的正文标志，不选天气/轮换广告。 / IDs use 1–80 lowercase ASCII alphanumeric/dash/underscore characters, starting alphanumeric. Invalid IDs are rejected before admission; correct them on the same connection. Prefer stable content markers over weather/rotating ads. [独立实测及已知限制 / Acceptance and limits](docs/verification/EXECUTION_AIONUI_ACCEPTANCE_20260921.md)。

### 明确字段名称 / Explicit field labels

字段名称来自当前界面，不要把产品名当字段名。需要指定标签时用 Click the input field labelled "当前完整名称"；未指定名称时可用 Click the search input field。命名字段缺失返回 named_field_current_uia_missing，不能把合成按钮当成可写字段。核对本次截图与诊断后再提交明确的新指令，不自动重放。 / Use the current full field label, not the application brand. Explicit label goals preserve their literal identity; a missing named field is not replaced by a synthetic button. Inspect current evidence before a new instruction; never replay automatically.

### Field-reading details / 字段读值细节

Plain named field goals tolerate one terminal label separator (`Address` / `Address:`); full words and explicit structured target identities remain intact. Before typing, the original current UIA identity and bounds are checked. After typing, the same focused runtime identity may resize: the read-only check requires a current real box containing the original point and two stable reads, and records `input_check.geometry_change`. It does not authorize another click or reuse new coordinates.

普通命名字段可忽略标签末尾单个冒号，不裁剪标签正文。输入前仍核对原身份与框；输入后同身份字段可扩缩，通过当前焦点、真实框、原点命中与稳定双读核对值，并记录只读几何变化，不据此自动重试输入。

### 焦点字段输入 / Focus-bound keyboard input

组合输入会固定当次识别字段，再核对实际焦点与当前值。浏览器自动填充遮住旧鼠标落点不等于字段失焦；仅该内部已绑定字段的键盘派发使用焦点复核，不会自动点击建议项。窗口、字段身份或焦点变化会中断并返回部分结果，不自动重试。 / A compound input binds the recognized field and checks its live focus/value. Autofill overlapping the old pointer point is not focus loss; only the internally bound keyboard path uses field-based revalidation. Changed identity/focus stops with partial progress, never automatic replay.


明确的裸字段描述（例如 Search box at the top-left of the webpage）也会保留当前UIA字段身份；不要求必须以Click开头。链接在UIA中的完整名称可能同时含标题、站点和URL；发生名称冲突时读取完整诊断和当前图，明确消歧，不重复盲点。/ Bare field-role phrases preserve current UIA identity too. Link accessible names may combine title/site/URL; inspect diagnostics and the current image before explicitly resolving ambiguity.

### Closed file-picker target / 已关闭文件窗口

`打开(O)` 或取消关闭对话框后，原绑定 HWND 已失效；先 `select` 原浏览器再 `capture`。直接截取旧对话框当前会返回 `ValueError: Window handle is not valid`，尚无结构化重新绑定指引；这不代表之前点击未执行，不要重放。/ After Open or Cancel closes a picker, explicitly select the original browser before capture. Capturing the old handle currently returns a raw invalid-window ValueError without a structured rebind hint. This is not evidence that the prior click failed; do not replay it.
