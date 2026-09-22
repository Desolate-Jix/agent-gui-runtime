# test.6 当前验收 / Current acceptance

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

以下为按发生顺序保留的历史记录，旧候选及“待完成”描述不代表当前状态。/ Chronological history follows; old candidate statuses are not the current release status.

# test.6 候选验收 / Candidate acceptance

Date: 2026-09-22. **Pending; not a release approval. / 尚未完成，不是发布批准。**

本次只配送执行模式。学习桥、工作台启动入口不配送；仍被执行链使用的共用模块保留。 / Execution only: exclude learning/workbench startup entrypoints, retain shared runtime dependencies.

## 包验证 / Package validation

- Source suite: 932 passed. Frozen candidate 02: 932 passed, 29.98 s, isolated Python from outside the source directory.
- Isolated entrypoint checks cover real input handlers plus desktop, application discovery/launch and lifecycle dependencies. They do not dispatch input.
- Candidate 02 MCP stdio smoke passed: seven tools/version, malformed-input recovery on the same connection, idempotent receipt reading, stopped-session rejection, reconnection and verified cleanup.
- First candidate: 931 passed / 1 failed. The real-shortcut subprocess test assumed the caller's working directory; fixed the test's explicit cwd and reran the complete isolated suite. Do not rewrite the first result as a pass.

源码与冻结包各 932 项通过不代表 GUI 通用成功率。首次包的测试工作目录错误已保留；握手和导入验证不能代替实机验收。 / Test counts are not a general GUI success rate; retain the first failure and separate imports/connectivity from real input.

## 实机与连续使用 / Real and continuous use

All task inputs used the candidate MCP runtime. Original images were inspected locally; raw desktop captures are not published because they may include unrelated notifications. / 操作通过候选 MCP 执行，原图在本机核验；不公开可能夹带通知的原图。

| Scope / 范围 | Observed result / 结果 |
|---|---|
| Notepad + Character Map | Launch by path/name, switch away and reuse the unique Notepad window, replace selection, undo, close → cancel → close → discard only this run's text; final owned-window cleanup passed. / 启动、切换复用、替换撤销、取消及不保存收尾通过。 |
| Models | Prepare/release/reprepare/release, stop with verified cleanup, explicit new session and second stop passed. / 连续模型生命周期与重开通过。 |
| Desktop shortcut | No prior caller binding: desktop capture, grounded double-click and discover/select opened the created Character Map shortcut. Escape did not close Character Map; a separate exact-process CloseMainWindow cleanup succeeded. This is not a framework-owned-close pass. / 无预绑定桌面启动成功；Escape 未关闭，独立清理不算框架关窗通过。 |
| Google → Maps | Search and organic Maps link navigation passed. Maps input_sequence stopped at check_focus (text_field_target_not_writable), without typing/Enter. After independent focus observation, basic input/Enter reached Auckland Museum, read and pane scroll worked. This is not a completed Maps combination sequence. / 地图字段核对中断，基础动作后续成功不冒充组合动作通过。 |
| Second Maps place | Model point was above the field; the observer then wrongly continued with current-focus input. Second-place search failed. Dispatch success did not establish focus or task success. / 模型误定位且观察者未确认焦点便续输，第二地点失败。 |
| Repeated Google search | Initial Auckland Museum query passed, including pending → same-ID result/image retrieval. Replacement query stopped in focus before typing; the real ComboBox was downranked as non-typeable. Exact-label follow-up also failed. / 首次搜索通过，重复搜索在定位阶段失败，确切标签复验亦失败。 |

All created windows and hosts are now closed; both sessions report cleanup_verified=true. The test shortcut was deleted only after exact path and SHA-256 verification. / 本轮窗口与宿主均已关闭，两会话清理验证通过；仅删除已核对路径和摘要的自建快捷方式。

## Failure classification / 故障分类

1. **Maps field check:** specific UIA rejection predicate remains unknown; do not assert the provider is truly read-only, nor remove checks simply because basic typing once worked. / 字段拒绝的具体谓词未知。
2. **Model/observer:** normalized and dispatched coordinates agree. There is evidence of wrong localization, not a coordinate-transform defect. Do not continue input merely because action_executed is true. / 模型误定位，不是已证实坐标转换错误。
3. **Google repeat:** compound input-role parsing and Value/Text ComboBox classification omitted the exact-field primary path. The non-typeable reason downranked the field; final refusal came from model/UIA identity conflict. A common source fix now recognizes explicit compound field labels, requires current Value+Text for ComboBox, and routes a unique named field through the existing initial control ROI path. Twenty new tests include duplicate/disabled/incomplete/read-only/selection-only controls and outside points. Sanitized 060/061 geometry replay preserves rejection of the original wrong points; no website-specific coordinates or model override were added. Real rerun remains pending. / 已修通用角色解析与首次字段定位路径，新增 20 项回归；原错误点依然拒绝，尚待实机复验。
4. **Driver:** an initial duplicate request ID was a tester mistake; preserve it separately from product operation results. / 首次重复请求 ID 属测试驱动错误。

## Remaining gates / 剩余验收

- 2026-09-22 scope addition: form filling with dropdown/options must be implemented and tested in this release. Working interpretation is web/native forms (text, dropdown, radio, checkbox); spreadsheet-cell scope awaits clarification. This is a requirement, not shipped functionality. / 用户新增本版表单填写与下拉选项；暂按网页/原生表单理解，Excel 单元格范围待确认，已接通源码，实机验收中。
- Reuse the existing execution chain: explicit field and desired value/state, reopen/reobserve dropdown options, do not blindly toggle an already selected choice, return partial progress and current images on interruption. No final submission. Test individual controls and repeated form editing on real interfaces before same-candidate AionUi acceptance. / 复用执行链、每项核对、避免重复反选、失败保留部分结果；真实单项和连续填写验收，不做最终提交。
- Finish the generic input classification fix, relevant regression and real single/continuous rerun. / 完成通用修复与复测。
- Freeze the corrected runtime once; validate isolated dependencies and tests. / 冻结修正候选并验包。
- AionUi bridge/backend recovered, but no independent task has been dispatched: Codex continuous acceptance is not yet complete. / AionUi 已恢复，尚未派单，不外包未完成的 Codex 验收。
- Friend's elevated cleanup failure was not reproduced; new diagnostic/recovery contracts are tested, but cross-machine root cause remains unconfirmed. / 朋友机器原始根因仍未复现。

Local evidence index (not shipped): `20260922-test6-package-01`, `20260922-test6-live-01`. The latter retains request 030 (field check), 036–038 (mislocalization/observer), 057–059 (successful pending search), 060–061 (repeat-search failure), and both cleanup reports. / 本地保留首次失败、后续动作及清理报告，不将原始个人界面发到公共仓库。

## Form source and first real run / 表单源码与首次实测

The integrated source suite passed 1043 tests before the additional independent-review cases. Entry-point preflight validates all four field kinds and fails if either new runtime dependency is missing. No package has been declared accepted from these counts.

表单文本、下拉、单选与复选已接入原 MCP。新增独立复核发现下拉读取结果没有约束实际候选、后续读取失败仍保留旧 after；已补失败测试，正在修通用边界。

Real service: W3C Markup Validator, not a homemade fixture. Opening the browser, maximizing and expanding More Options succeeded. The first form focus was interrupted by changing notification occlusion before input. Explicit reselection succeeded; the next Address focus reached the correct field but stopped before typing with text_field_value_patterns_disagree. A scoped UIA probe identified Chromium Edit/textbox returning an object-marker TextRange (U+FFFC) while writable ValuePattern was empty. The existing same-identity object-range handling covered only ComboBox; a generic Edit counterpart is being repaired. No form was submitted. Test browser closed through the framework.

真实 W3C 表单首轮保留两次失败：通知遮挡变化导致截取中断；恢复后正确聚焦 Address，但 Chromium 文本范围对象标记被误当值冲突。没有输入或提交，本轮浏览器通过框架关闭。后续修复与复验不得改记为首次成功。

### Second form run / 表单第二轮

The common TextRange repair and internal current-control binding passed a 1104-test source batch; a subsequent missing-dependency preflight case passed separately (9 preflight cases total). These are overlapping source counts, not live success rates. The corrected text path filled `https://example.com/` into W3C's Address field in 5193 ms, with value verification and an original after-image; no submission occurred.

通用文本范围修复和当前控件绑定完成后，源码批次 1104 项通过；随后额外的漏依赖负控通过（入口检查共 9 项）。这些是重叠的源码结果，不是实机成功率。真实 Address 填写复验成功，用时 5193 ms，实际值与原图均已核对，未提交表单。

Checkbox Show Source (3135 ms) and dropdown Character Encoding (3145 ms) both stopped before clicking: the initial recognition crop omitted the adjacent accessible label, and the model point fell outside the real control bounds. This is a shared initial-ROI context defect, not a reason to expand the clickable target or substitute model coordinates. A generic repair and bounded geometry regressions are in progress; checkbox/dropdown/radio and continuous form acceptance remain open.

复选框与下拉框分别在 3135 / 3145 ms 拒绝，均零点击：首次识别裁图漏掉相邻标签，模型点落在真实控件框外。正在修通用初始裁图上下文，不扩大可点击框、不替换模型坐标。复选、下拉、单选及连续填写尚未通过。

Second-run cleanup reported stopped, host_alive=false, cleanup_verified=true. The observer supplied two invalid close commands (wrong kind, then missing identity); these are tester errors, not close-operation failures. Stop/disconnect cleanup is not evidence of an explicit graceful-close pass. Local evidence: `20260922-test6-forms-live-02`, requests 005–009. / 第二轮宿主停止且清理验证通过；观察者两次关窗参数错误单独保留，不计产品失败，也不冒充显式关窗通过。

### Source integration and runs 03–05 / 源码集成与第三至五轮

- Latest source checkpoint: `python -m pytest tests -q --disable-warnings --maxfail=1`: **1180 passed, 29.37s**. This predates the shared UIA graph integration and is not candidate-package acceptance. / 最新源码检查点 1180 项通过，尚不包含公共图遍历集成，不是候选包验收。
- Run 03 retained model points outside the checkbox/dropdown bounds; no input followed. Run 04 applied reversible small-control enlargement and selection-specific prompts: Show Source clicked successfully (6323ms command / 6566ms client), dropdown opened, but repeated UIA aliases exhausted the reader. / 第三轮错误点拒绝；第四轮复选勾选通过、下拉展开后读取中断。
- Read-only finite-array audits found 253 unique descendants, 256 edges and three repeated shell aliases (including one back edge). CompareElements, stable metadata and canonical ControlView parents identify the same nodes; exhausting indexed arrays still visits all distinct children. True identity or parent conflicts remain failures. / 有限数组取证确认是供应方别名图，不把所有重复节点一律放行。
- Run 05 read the expanded owned UTF-8 option after reader normalization. The model point was inside its actual box, but the common recognition inventory still reported incomplete for the same graph and produced no unique candidate; option input was not dispatched. This is a common-reader/inventory inconsistency, not evidence to force a click. / 第五轮选项读取成功，主识别仍拒绝同一图，选项零点击；正在统一公共契约。
- Runs 03–05 each closed their own test browser through the framework, followed by stopped hosts, empty pending IDs and `cleanup_verified=true`. No form was submitted. / 三轮均通过框架关闭自建测试窗口并验证宿主清理，无表单提交。

All first failures remain separately recorded. Radio, complete dropdown selection, repeated mixed form filling and same-frozen-candidate AionUi acceptance are still pending. / 首次失败独立保留；单选、完整下拉、混合连续填写及同冻结包独立验收仍待完成。

## 2026-09-23 form source acceptance / 表单源码验收

最新源码回归 **1245 项通过（29.46 秒）**。真实 W3C 表单在同一新建 Edge 会话完成文本、下拉、复选与单选的单项及混合连续填写；重复设置不反选，重名控件中断、无效选项部分中断及从已展开下拉恢复均符合预期。10 条表单命令中 8 条正常完成、2 条预期错误；这不是跨网站准确率。最终窗口关闭、宿主退出，cleanup_verified=true；未提交表单。

The latest source suite passed **1245 checks (29.46s)**. A fresh real W3C/Edge session completed individual and mixed continuous text/dropdown/checkbox/radio filling, idempotent state setting, ambiguity rejection, partial interruption and recovery from an open dropdown. Of 10 form commands, eight completed normally and two produced expected errors; this is not cross-site accuracy. The test window and host closed with verified cleanup. No form was submitted.

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

Prior live-06 failure: native option hit belonged to an exact owned popup, while dispatch expected the main root. The shared fix now binds and revalidates the unique same-process/root-owner popup by observed HWND and geometry before using the existing popup-aware input path. Initial Chromium readiness now starts its retry budget after the first complete empty scan. Both primary paths passed live-07. / live-06 原生选项落点归属 popup 与主窗口预期不符；现固定并复验同进程/根 owner 的唯一 popup 后复用原输入器。首次 Chromium 就绪预算从首个完整空扫描后开始；两条主路径均在 live-07 通过。

## 2026-09-23 browser continuity failure / 浏览器连续回归失败

Source run browser-live-02: Google homepage search completed in 9.692s; replacing the result-page search via the generic goal failed in 11.520s. The model point (1012,120) opened Lens, then check_focus interrupted with text_field_keyboard_focus_unavailable; no text or Enter followed. Exact-label ComboBox source repair was not exercised by this generic goal. Investigation must distinguish model error, field-goal identity parsing and candidate selection; no site-coordinate fallback or risk-policy redesign. Explicit test-window close succeeded (62.72ms), host cleanup verified. / 首次搜索通过；结果页泛型目标误点 Lens 后中断，未打字或回车。需区分模型误差、目标身份解析与候选选择；不添加站点坐标补丁。测试窗口及宿主已清理。

Raw report is local at 20260923-test6-browser-live-02/acceptance-report.json; screenshots contain unrelated private notifications and must not be published. This failed run is not release acceptance.

## 2026-09-23 browser fixes and live-04 / 浏览器修复与第四轮实测

- Source suite: 1259 passed in 29.47s. Named-field absence now rejects a synthetic-button replacement; the original wrong-name instruction was independently verified as zero-input in live-03. Explicit labels are no longer wrapped as the entire instruction in ROI prompts. / 源码1259项通过；命名字段缺失不再被合成按钮替代，原错误名称指令在第三轮证实零输入。ROI提示仅把明确标签作为字段名称，并保留原动作语境。
- live-04: homepage search 10.274s, original explicit-label failure replay 14.018s passed, Google result to Maps 14.496s passed. Maps search failed at check_focus after 9.418s: model point (128,140) was outside a writable field, text_field_target_not_writable; no text or Enter followed. This is NOT a completed Maps flow. / 第四轮原标签失败路径复验通过并进入地图；地图填写在聚焦后中断，未输入或回车，不能算完整通过。
- The run closed its exact test window (61.763ms), host exited, pending empty, cleanup_verified=true. Raw local evidence: 20260923-test6-browser-live-04/acceptance-report.json. Private notifications appear in raw images; do not publish them. / 本轮窗口与宿主已清理；含私人通知的原图仅本地保留。
- test.6 remains unreleased; no new package or AionUi dispatch. Investigate current generic field identity/geometry before further continuous regression. / test.6未发布、未新打包、未交AionUi；先核查泛型字段身份与几何路径。

## 2026-09-23 generic-field negative control / 泛型字段负向复验

Complete current UIA now prevents a generic field goal from selecting a synthetic button when the model point hits no writable field. Source suite: 1266 passed in 29.62s. Live-05 rejected the original Maps point before input (3.868s); a clarified instruction also stopped before input (6.459s). This proves the no-misclick invariant, not successful Maps searching or better model accuracy. Both host and test window closed, cleanup_verified=true. / 完整当前UIA已不再把字段框外模型点包装成合成按钮；1266项源码回归通过。第五轮原指令及明确区域后的新指令均在点击前中断，证明不误点，不证明地图搜索成功或模型精度提高。窗口与宿主均已清理。

Next: improve the generic current-field primary localization path using current UIA document ancestry/role evidence; do not add site aliases or snap an erroneous point to a guessed center. Frozen package and AionUi remain pending. / 下一步用当前UIA文档归属和角色改善泛型字段首选定位，不加站点别名或把错误点吸附到猜测中心；冻结包与独立验收仍待完成。

## 2026-09-23 current page-field localization / 当前网页字段定位

Source suite: 1289 passed (33.53s). Generic page-scoped input goals can now use a unique current writable field under an observed browser Document as the primary model ROI, with exact field geometry and reversible coordinates. Unknown/incomplete or multiple-field evidence does not guess a primary target. The model point must remain inside the real field. / 源码1289项通过；明确网页范围的泛型输入目标可使用当前Document内唯一可写字段作模型首选裁图，保持真实边界和可逆坐标，不完整或多字段不猜目标。

live-06 verified the primary ROI and completed two successive place searches (Museum 14.081s, Gallery 17.147s), with real result reads. However, the first correctly located click and a later Google-to-Maps run both interrupted at check_focus with text_field_target_not_writable; exact reader substage is not yet known. This is recovered success, NOT clean continuous acceptance. Adding structured reader diagnostics before another rerun; no blanket retry or writable-check relaxation. / 第六轮两个地点搜索和结果读取通过，但首次及之后完整链在正确落点后仍有字段读状态中断，具体子阶段待证。不能把恢复成功算首次连续通过，先补结构化诊断，不放宽可写条件。

No fresh frozen candidate, AionUi dispatch or release. Raw live evidence remains local only because screenshots include unrelated private UI. / 未新冻结、未派独立验收、未发布；原图含无关私人界面，仅本地保留。


## 2026-09-23 reader substage / 读取子阶段

live-07 reproduced the original interruption with typed diagnostics: text_field_target_not_writable, phase=resolve_field, read_index=1 after a real click at (189,115). It occurred before target description or Value/Text read-only checks; no text or Enter followed. A generic wrapper-resolution path still needs inspection. Both live-06 and live-07 closed their own windows and hosts with cleanup_verified=true. / 第七轮明确第一采样在屏幕命中解析阶段失败，尚未进入控件属性或读写模式判断，不能再猜是只读属性误判；未继续输入。第六、七轮已清理窗口及宿主。

Form-state receipt fix: unavailable checked/expanded observations now mark the field check unavailable and remove the stale top-level after, retaining nested history. Main-agent form-related regression: 101 passed (0.84s). / 表单未知选中或展开状态不再返回前一字段旧after，保留嵌套历史；主代理相关101项通过。

No package, independent acceptance, publication or shutdown yet. / 尚未打包、独立验收、发布或关机。

## 2026-09-23 latest reader-path evidence / 最新读取路径证据

Full source suite: 1311 passed in 31.94s. live-08 proved that the first point resolution returned Text then four Group ancestors, not a writable field. The same recognition receipt contains a current ComboBox with runtime ID and real bbox, but input_sequence passes only a 1px point into the reader. Implementing a narrow identity-dataflow repair to reuse the existing bound-field reader; no new blind input retry. This is an observed path mismatch, not proof of a Windows COM root cause. / 完整源码1311项通过；第八轮第一命中为Text和四层Group，同次识别却有精确ComboBox身份；组合输入丢掉身份只传1像素点。正在保留同帧字段身份并复用已有绑定读取，不新增盲重试，不能把现象直接归因为Windows COM。

Both new diagnostic runs are closed with verified cleanup. Source form feature accepted; full browser continuity, corrected bundle and independent acceptance still pending. No publication or shutdown. / 两轮诊断已清理；表单源码已验收，整批连续浏览器、冻结包和独立验收仍待完成，未发布或关机。


### Cold content observation / 冷启动正文观察

In live-08 the first complete UIA inventory contained only browser chrome (50 controls, no Document/ComboBox); a later same-window inventory contained 193 controls with both. Execute-mode inventory samples once and marks ready when nonempty; form-control first-read readiness is a separate path. This does not prove Chromium lazy publication: conversion can also omit zero-sized/unreadable nodes. Do not equate traversal completion with page readiness. Any future bounded readiness must pair its final tree with a fresh capture, not pre-wait pixels. / 第八轮首次仅有浏览器外壳，后次有正文；执行定位单采样且非空即ready，表单首次等待是另一条路径。不能据此断言浏览器懒发布根因，转换层也可能丢弃节点。后续就绪改动必须把最终树和新截图绑定，不拼旧图。

## 2026-09-23 exact input-field identity / 精确输入字段身份

Source suite: 1327 passed (32.42s). input_sequence now preserves the same selected UIA field runtime ID/type/real bbox and recognition-capture SHA into both field reads; invalid declared UIA does not fall back to an unbound point. Pixel-only inputs keep the previous path. / 源码1327项通过；组合输入两次读值均保留同次UIA字段身份和原识别图摘要，声明UIA但身份无效不降级猜点，纯视觉路径保持原行为。

live-09: the original focus/read failure advanced: check_focus passed (216.525ms), typing completed, but check_input timed out (965.012ms, text_field_hit_not_ready) before Enter. The image confirms text was entered; this is partial execution, not zero input or full success. Investigate readiness-budget semantics around synchronous UIA calls without blind replay. Own window/host cleanup verified. / 第九轮已正确聚焦并填入文字，输入后复读却在就绪预算超时，未回车；不能记成零副作用或完整通过，继续核查同步UIA调用的预算语义，不重放输入。窗口宿主均已清理。

No corrected bundle, AionUi dispatch, release or shutdown yet. / 未新冻结、未派独立验收、未发布或关机。


### Latest continuous regression / 最新连续回归

Source suite: 1338 passed in 31.94s before the subsequent post-input geometry and field-label corrections. Live-10 completed two explicitly replanned Maps queries and reads; it was not an uninterrupted Google-to-Maps pass. Live-11 retained first-scan missing Document on both Google and W3C, same-identity Google field widening after typing (453 to 533 px, Enter withheld), and plain Address versus Address: label mismatch. W3C dropdown/checkbox/radio together passed in 70.15s. Both sessions closed only their owned windows and stopped with cleanup_verified=true.

源码批次1338项通过后，连续复验仍暴露正文树首扫缺失、输入后同身份字段扩宽误拒、字段标签末尾冒号匹配不一致；不能用单项成功冒充整条连续通过。下拉/复选/单选组合再次通过，原图本机核对，全部测试窗口和宿主已清理。正在修公共契约，尚未冻结或交给AionUi。

## 2026-09-23 current source acceptance / 当前源码验收

Latest source suite: **1396 passed (33.38s)**. Source live-12 passed Google search → Maps → Auckland Museum → Auckland Art Gallery with separate content reads, then a new real W3C window passed text entry, four-field text/dropdown/checkbox/radio fill, repeated desired states with zero input, missing-option partial interruption and open-dropdown recovery. Both owned windows closed; host stopped, pending empty, cleanup_verified=true. This is the first complete rerun on the latest source, not proof that earlier attempts passed.

最新源码1396项通过；第十二轮完整谷歌到地图、两个地点查询读取，再到真实W3C表单四类控件连续填写、重复值无输入、中断恢复全部通过。两窗口与宿主已清理。输入后同身份字段扩宽453→533像素的读值复验通过，原绑定不改写；无自动输入重放或表单提交。此前失败记录保留。

Timings: Google search 14.092s; open Maps 15.487s; two queries 17.850s / 24.519s; W3C text 16.197s; four-field fill 91.862s; three no-op choices 8.022s; expected partial failure 35.506s; recovery 22.146s. These are command wall times, not universal performance claims.

Evidence stays local: 20260923-test6-browser-live-12/acceptance-report.json. Raw screenshots contain unrelated private notifications/history; do not publish. Next: freeze one corrected execution-only candidate, own isolated/package/live checks, then AionUi same-candidate independent acceptance. No release or shutdown yet; learning remains excluded. / 下一步冻结执行候选，完成同包检查与实机复验后才交AionUi；未发布或关机，学习不随包发布。


## 2026-09-23 additional window-origin review / 补充普通窗口复核

Source suite 1425 passed (32.24s). Candidate03 was deliberately stopped after Google/Maps partial success because review proved two common regressions: capture-relative UIA origin was mistaken for screen origin, and verified canonical alias graphs were rejected as incomplete. Both now have red/green regressions (including positive/negative origins and unknown-graph refusal); candidate03 is superseded, not accepted.

Non-maximized source replay uses screen origin (879,80) correctly. It exposed a separate readback contract defect: after a valid field click, the browser autofill popup covers the old click point while the exact expected Edit keeps keyboard focus, RID and geometry. The point-based focus read interrupts before typing. Read-only focused-element and point probes confirm the distinction; all test windows/hosts are cleaned. Fix the common bound-field read path, not website coordinates or autofill settings. Keep raw screenshots private.

普通窗口坐标与规范图误拒已修；窄实测又明确显示“原点击点被随后弹出的自动填充遮住，但目标字段仍有焦点”。应按确切当前字段身份读取，而不是把读值当作再点击，不能自动关浮层、改浏览器设置或重放输入。尚未新冻结或派AionUi，未发布／关机。


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


### candidate05 独立复测发现 / Independent findings

AionUi 原始回执已显示：四字段66.034s及重复状态6.755s通过；ISO8859下拉选择两次未执行，模型点比当次真实选项框上沿高1px。坐标变换正确，不放宽框；改进小 listitem 的通用主ROI可读性待验证。裸名词 Search box at the top-left of Google Maps 未进入现有字段语义，导致同帧UIA身份未绑定而退回点读取；按明确字段名词短语修公共解析，不加网站坐标。UTF16及后续填写成功不能覆盖前面失败。/ Four-field fill and idempotence passed, but small option localization and bare field-phrase identity require repair; preserve failed attempts.

候选05不作为已通过的发布包。独立最终报告和清理尚待收齐；后续源码、实机和同包独立复验必须重新闭合。/ Candidate05 is not release-approved; collect final report/cleanup and reverify the repaired path before delivery.


### 独立复测后的公共修复 / Repairs after independent acceptance

1544项源码回归 /32.92s通过。小型唯一当前UIA listitem复用可逆上下文放大，不放宽目标框；真实ISO8859单项25.934s、四字段64.215s、无操作6.253s、预期中断24.481s、同ISO8859恢复16.120s通过。明确裸字段名词进入既有身份绑定；Aion原措辞的Maps两次input_sequence 9.045/10.470s通过，独立读取确认两个地点。/ Small-listitem context and bare-field identity fixes passed source regression and real single/continuous reruns.

搜索结果的短标题与泛化描述仍可能和搜索框/复合链接名称冲突；本轮两次无输入拒绝后，使用回执返回的完整链接身份成功。该记录不是首次通过，也不代表任意自然语言都能定位。源码窗口与宿主均清理true。候选06待同包与针对性独立复验，不将候选05总结的PASS当作新修复的证据。/ Two incomplete link goals were refused before explicit full-identity disambiguation succeeded; preserve them separately. Candidate06 acceptance remains pending.


### candidate06 最新同包状态 / Latest frozen candidate

源码1544项/32.92s，候选06包内1544项/33.92s，隔离入口和MCP smoke通过。同包实机四字段含ISO8859为65.849s，重复状态6.386s零输入，预期缺选项中断25.198s，已展开下拉恢复15.643s。Google搜索10.525s→完整链接7.802s→原裸字段描述两地点8.992/10.660s及读取通过，全部自建窗口和宿主cleanup_verified=true/pending=[]。/ Source, isolated bundle and original-failure single/continuous reruns passed; cleanup verified.

候选05独立报告总结PASS，但保留了ISO8859两次拒绝和Maps字段核对失败，主代理未将替代成功当作原故障已修。候选06已交同一AionUi针对性复验，结果待核对。SDK最外层结构错误仍可能返回标准tool error；此已知错误面差异不记作宿主崩溃，调用方应按schema更正而非重放输入。/ Candidate05 reported task-level PASS with failed original subpaths; candidate06 targeted independent retest is pending. Top-level SDK schema failures may still use tool errors rather than the domain envelope.
