# Adaptive review live acceptance / 主动审核真实验收

## 2026-10-10 P2 当前源码 / Current P2 source

Candidate01 的安装、同版本替换和限定独立桌面验收保留为历史。此后最终取消门禁、学习分支上下文、HTTP总截止及显式v2原生有效超时语义续接的此前冻结组为756 passed/1 skipped（共757，XML80.769秒，1040文件SHA一致）；该旧组不验证后来的manual改动，不累加重叠组或转计旧候选证据。 / Preserve Candidate01's scoped installation/replacement/independent-desktop evidence as history. The earlier cancellation/context/HTTP/native freeze recorded756 passed/1 skipped out of757, XML80.769s and unchanged1040-file hashes; it does not cover later manual changes. Overlapping groups and candidate evidence remain separate.

人工只读 observe 已源码完成；Main 冻结联调1008 passed、1 skipped（共1009，0 failure/error，XML91.700秒；stdout91.74秒，wall92.968秒），1048个app/scripts/tests Python文件前后SHA一致。唯一跳过为符号链接目录拒绝用例，因环境无创建权限。此冻结点包含纯模板模块96例，不覆盖随后模板接线；本次零付费、零桌面、未打包。 / Manual read-only observe is implemented in source. Main's frozen integration records1008 passed/1 permission skip out of1009, zero failures/errors, XML91.700s, stdout91.74s and wall92.968s, with unchanged1048-file hashes. It includes96 pure-template cases but not subsequent template wiring; zero paid calls, desktop actions or packages.

原生续接与人工观察尚无新候选实机验收。纯类型模板解析/认证模块已通过worker96例并纳入Main上述冻结组；共享服务、profile、执行/学习runtime与UI仍待接通，后续接线不由该冻结点证明。源码闭合后仍须新候选真实单项/连续及同候选独立验收；真实加载正例与准确率/速度/Main介入收益未证明。付费仍12/12余0，新增额度待答复，下载仍preview.3。 / Native continuation and manual observe have no new-candidate live acceptance. The pure typed-template validation/resolution module passed96 worker cases and is included in Main's freeze; shared service/profile, execution/learning runtime and UI wiring remain open, and later wiring is outside this evidence. A new candidate still needs live single/continuous and independent acceptance. Loading success and measured benefits remain unproven; usage stays12/12, extra allowance is pending and downloads remain preview.3.

手动观察仅支持原输入completed且action_executed=True的v2核验等待，暂不支持read_text的False；复用原run/step/execution/wait，逻辑请求先持久占位，相同请求不重截图，未知采集不重派。自动与手动共享最多2次，失败/未知也计数；手动12秒采用期限不重置自动期限，同步capture不能硬中断，晚回复拒绝采用。v3保留原after与assessment_round，追加新图/证据摘要/祖先链；仅最新包可审核，旧包只可读取已认证图像，仍须原wait显式continue。 / Manual observe requires completed original input and action_executed=True at a v2 verification wait; read_text=False is unsupported. It retains the original IDs, persists a logical claim before capture and never repeats identical or unknown captures. Automatic and manual captures share two attempts, counting failed/unknown attempts. The separate12-second manual adoption deadline does not reset the automatic deadline or hard-interrupt synchronous capture. V3 preserves original after and assessment_round, appends evidence/ancestry, permits review only of the latest packet and read-only image retrieval from authenticated older packets, then requires explicit original-wait continuation.

记录与后续：[P2源码检查点](ADAPTIVE_P2_SOURCE_20261010.md)。 / Evidence and remaining work are recorded in the linked checkpoint.

## 2026-10-10 最新Candidate01检查点 / Latest Candidate01 checkpoint

此前installed01改名/保存revision3→4、仅step-1.title变化及installed03正确预检后重开/public read/31库hash通过，三次运行正常清理。installed02预检失败后Main未按exit code阻止启动，以及之前执行卸载exit0/complete=false均保留原件；该生命周期检查点hash不改。 / The earlier save/reopen checkpoint retains its31-file library and normal cleanup, together with the caller preflight failure and original incomplete root-removal assertion. Its evidence remains immutable. [Lifecycle](../../.superpowers/sdd/2026-10-09-adaptive-live/INSTALLED_LIFECYCLE_CHECKPOINT.md).

新增同版本包替换检查：旧执行/学习→Candidate01四命令exit0/verified，payload 546/349→557/981，各组件内未知fixture及本次独立外部30库hash保留；没有跨版本或schema迁移。升级后执行依赖7.065s passed（既有LIGHT，Qt/input/host=false），GUI en-US三页offscreen/正常close 1.668s。两维护卸载exit0/verified后各仅保留fixture、原卸载器、retained marker共3文件，外部/另一组件不变，无强删。 / Same-version replacement passed four check-install commands, preserving unknown fixtures and this separate30-file library. Existing-interpreter dependency and offscreen GUI probes passed; two maintained uninstalls retained only three expected files per component without forced removal. These are not cross-version/schema, fresh-environment or live-desktop results. [Upgrade checkpoint](../../.superpowers/sdd/2026-10-09-adaptive-live/UPGRADE_CHECKPOINT.md).

Sol同冻结候选的限定独立桌面验收已通过：新Temp check安装，改名保存、英→中→英、界面库/流程图查看、同库重开和两次正常关闭；10次门控click、1次clear/type，31库hash及旧版本/pin保留，API0。Main复核关键原图和数据，并在维护卸载前重算127原件引用/64原图/8安装元数据；卸载后254外部文件不变，学习临时目录移除，执行未知空目录和卸载记录按合同保留。观察器首败与原回执保留，不把人工效果改写为自动effect。 / The bounded independent journey passed on the same frozen candidate, including bilingual UI, title-only save, exact reopen and two normal closures. Main reviewed key images/data and rehashed the evidence before maintained cleanup; external data and prior versions remain intact. Preserve observer failures and automatic effect facts. [Main closeout](../../.superpowers/sdd/2026-10-09-adaptive-live/INDEPENDENT_MAIN_CLOSEOUT.md).

真实loading/observe正例及新审核上下文的远程效果/收益仍待验证；本次check证据不等于当前候选normal安装、跨版本/schema迁移或新机器依赖验收。安装器/设置/依赖11文件的22项字节比较相等，已有preview.1安装的registry/shortcut仅做了只读观察，不倒写历史。批准有效；付费仍12/12余0，追加最多4次额度尚待答复；冻结产品、版本、公开下载不变，正式目标未完成。 / Real observe and revised-context benefits remain open. Check-mode evidence does not establish normal installation, migration or fresh-machine dependencies. The 22 exact contract comparisons and current installed-state observation retain their own scope. Testing approval stands; additional paid allowance is pending, with no product or release change.

| 保留边界 / Retained boundary | 本轮结论 / Conclusion |
| --- | --- |
| 同版本 / Same version | 执行0.1.2-preview.3、学习0.1.0-preview.3各自前后一致；不是跨版本迁移。 / Each component kept its version. |
| 两个数据根 / Separate data roots | installed生命周期库31与本次替换库30各有原件，不互换或累加。 / Preserve separate fixture identities. |
| 首败 / First failures | installed02调用方预检错误、此前执行卸载complete=false及F01/F02原件不覆盖。 / Later bounded success does not erase earlier failures. |


## 2026-10-10 UI08时点记录（历史） / UI08 checkpoint (historical)

UI08的001–027同窗双语菜单、库与反馈比较限定流程由Main看图确认通过并正常清理；自动effect_verified=false原样保留。本归档者只核读原件，未目视复验或运行测试/桌面/API。663源码与3工具冻结hash、30库文件前后hash一致，仅表示记录时点相同；closed记录source/harness unchanged、owned window closed、host stopped/pending=[]/cleanup=true，bridge23020 exit0由Main见到。证据：[UI08闭合](../../.superpowers/sdd/2026-10-09-adaptive-live/UI08_CLOSURE.md)、[原件/SHA索引](../../.superpowers/sdd/2026-10-09-adaptive-live/UI08_CLOSURE.json)。 / Main visually confirmed the bounded bilingual and feedback journey and cleanup. Automatic effects remain false; this archivist only read evidence. Freeze/library hashes match at the recorded checkpoint; bridge exit is attributed to Main.

公共身份接线修复worker RED1failed/48passed→GREEN161；Main11模块380passed/6.90秒（XML6.877秒，fail/error/skip=0），各组不累加。 / Worker and Main regressions pass as separate evidence groups.

| 请求 / Request | 原件事实与Main观察 / Original facts and Main observation |
| --- | --- |
| 001–005 | Settings→Language；004 action=true/click_count=1，invocation3.603487s（outer wall3.619529s），targets完整。 / Menu opened with one click; preserve timing scopes. |
| 006–014 | 中文、中文库、中文语言菜单、恢复英语；Main确认文字与界面。 / Main confirmed Chinese UI/library/menu and restoration to English. |
| 015–022 | 打开反馈、选择dialog；019完整quoted option、021 Candidate 1均本地VISTA且action=true，各一次click。 / Feedback selections used local VISTA, each one click. |
| 023 | Compare suggestion action=true；Main确认双截图、修改前后描述、processed/read-only。 / Main confirmed paired images, before/after text and read-only processed state. |
| 024–027 | Close action=true，但即时observation unavailable/post_action_observation_failed；025 select root+026 capture确认dialog关闭，027维护关闭/清理。 / Preserve failed immediate capture and successful recovery/cleanup. |

| 公共合同 / Shared contract | 当前结论 / Current finding |
| --- | --- |
| 可见故障 / Failure | UI07 Language popup拒绝保留；UI08同入口成功。 / Keep UI07 refusal; UI08 succeeds. |
| 破坏的合同 / Invariant | bound-only reader不能检查独立popup HWND。 / Bound-root identity cannot be reused for a popup HWND. |
| 修复位置 / Fix | 公共windows_control_hit_reader接独立原生popup观察；原WindowManager/identityreader合同不放宽。 / Common popup identity wiring preserves existing contracts. |
| 为何非应用特例 / Generality | 适用于owned Windows/Qt popup，无工作台文案/坐标特例。 / General owned-popup handling without app-specific text/coordinates. |
| 回归 / Regression | worker49项首败、161项修后与Main380分别保留；UI08原件提供新实机结果。 / Preserve red, green, Main and live evidence separately. |
| 安全影响 / Safety | owner/PID/两次命中/遮挡负例保留；UI06原null不借UI07严格false proof倒改。 / Ownership and negative guards remain; historical unknown facts stay unknown. |

[UI06原件](../../.superpowers/sdd/2026-10-09-adaptive-live/UI06_CLOSURE.md)与[UI07原件](../../.superpowers/sdd/2026-10-09-adaptive-live/UI07_CLOSURE.md)字节未改：007调用格式、009标题冲突/Main5-case明确名称诊断、011采集失败、016原null，以及UI07 relative-link调用错误和004真实拒绝均保留。 / Previous failures and caller errors remain byte-identical.

付费新增0（原状态Decision off/used0、api_profile=null；019/021为本地VISTA），预算12/12余0。批准有效；loading/observe正例、review-context实际远程收益、当前冻结候选安装升级/同候选独立仍未完成，未宣称完整正式版或发布；context441仅离线。 / No remote paid call was added; local VISTA remains model activity. Positive observe, actual context benefit and installed/independent acceptance remain open; no full release is claimed.

## 2026-10-10 上下文修复（历史检查点） / Context repair; historical checkpoint

1. **失败 / Failure:** 两个目录步骤共享field_goal，审核摘要丢失输入参数与预期结果；旧预检还允许单条超长摘要先入队。 / Shared field goals lost distinct step intent; oversize individual summaries could pass admission.
2. **通用合同 / Invariant:** 审核必须保留有限的冻结步骤语义，且远端所需上下文在派发输入前应已满足相同格式边界。 / Preserve bounded frozen semantics and validate provider constraints before input dispatch.
3. **修复层 / Fix:** task_plan_review白名单JSON摘要、task_plan_contract完整结构后二次预检、provider空allowed_states语义澄清。 / Shared projection, preflight and provider wording changed.
4. **通用性 / Generality:** 适用于所有v2临时计划的点击、组合输入与文本读取，不依赖7-Zip目录/坐标。 / Applies to all supported v2 action kinds without app-specific paths or coordinates.
5. **回归 / Regression:** 首次16失败/2通过保留；修后新18项、Sol相关341项通过；Main13文件441项通过，main-review-context-integrated.xml。Main核对增量diff，Sol同hash只读审阅无阻断；重叠组不累加。这是离线证据，不代表真实模型审核减少。 / Preserve red failures; the targeted and Main integration groups passed without establishing real-model benefit.
6. **权限与限制 / Authority and limits:** 不复制input/text实际值、不读取目标元数据，不改阈值、末步审核或输入门禁。超长在入队前拒绝；旧v1不变，旧开发v2运行须在原冻结运行时结束，不能用新投影重算旧binding。预算仍12/12，未增加真实API调用或桌面动作。 / Input values remain excluded; thresholds and gates are unchanged. Reject oversize before queueing, preserve v1 and old evidence, and use new runs for the changed v2 projection. No added real requests or desktop actions.

下方完整路由对照发生在本次上下文修复之前，仅证明当时字段定位及三步完成，不作为新投影的收益证据。 / The complete routing pair below predates this repair and does not measure the new projection.

## 2026-10-10 字段尺度修复与完整路由对照 / Field-scale repair and complete routing pair

本节为此前字段尺度检查点（历史），首败、旧余额和旧下一步均保留。当前批准的12次付费调用已全部记账，不继续付费调用本批API。 / This is the earlier field-scale checkpoint; subsequent failures, balances and next steps are historical. All twelve authorized paid requests are accounted for, with no further paid calls in this batch.

1. **失败 / Failure:** interior/整图路由修复后，640×270缩图仍把17px高地址输入框定位到框上方；输入前拒绝。 / After intent/routing repair, downscaling still placed the point above a thin address field; the gate rejected input.
2. **通用合同与根因证据 / Invariant and evidence:** 两张已保存新帧各比较640/1024/1280，共6次本地诊断，640两次均在Edit外，1024/1280均在Edit内。有效输入意图不能在默认缩图中丢失可辨别细节；这是两张帧的尺度敏感证据，不是通用准确率证明。实际processor网格仅本地同processor回放，非服务遥测。 / Six local diagnostic calls across two saved frames found misses at 640 and hits at both larger sizes. Preserve usable field detail; two frames do not establish general accuracy. Processor-grid observations are local replay, not server telemetry.
3. **修复层与通用性 / Shared fix:** `app/api/action.py::_execute_plan_request_defaults` 对已确认普通field scope默认1024；复用现有vision意图策略，无7-Zip坐标/应用规则。显式尺寸及关闭设置优先，no-scope/strict-fill/显式word或非input不变；无夹点、强制角色或门禁放宽。 / The shared action default uses 1024 only for verified ordinary field focus, retaining explicit overrides and existing exclusions; no app coordinates or weaker input gate.
4. **回归 / Regression:** 首次RED4失败/41通过，最终focused46通过；Main15模块397项/13.87秒，`main-focus-resolution-integrated.xml`。本地诊断summary SHA256 `ba00c1b89c569fd574421a2a8f00e1b670dde5d85f4ac889a81cd527cff7aad8`。 / Retain the red failures and the 397-case Main regression; related groups overlap and are not summed.
5. **实机 / Live:** `focus-resolution-live-02`（Decision off + always_main）与`focus-resolution-adaptive-03`（v2 auto + adaptive）使用同661文件冻结源码、同fixture/goal/窗口几何和不同全新根，各三步完成、三次原wait审核续接，无重放，正常关闭owned窗口与host。setup/open/return共六条输入trace均1024整图、无ROI、无旧学习/识别缓存。此配置对照不是旧版本A对照；旧A准备失败仍保留。 / Both fresh routes completed with three original-wait continuations and cleanup; all six input traces used 1024px full images without learned/cache reuse. This compares current configurations, not the failed old-version baseline.
6. **收益与限制 / Benefit and limits:** 两组Main审核均3次，减少0。原命令wall之和14.909751→15.119481秒（+0.209730秒）；adaptive新增Decision 2.6298517/1.0548096秒，共3.6846613秒、6604 input tokens、0 output。API/HTTP/server及外层wall有包含关系，不能重复相加。总任务wall110.203/135.449秒包含Main空档，独占推理时间与tokens未知；无总体提速/准确率提升结论。两组OCR漏source文件夹，Main由hash一致原图补全，未声称完整OCR。 / Main reviews did not decrease. Original serial command walls were 14.910/15.119s; adaptive added 3.685s of Decision calls. Nested timings overlap. End-to-end walls include Main gaps, whose exclusive reasoning cost is unknown. Preserve the OCR omission and Main image supplementation.

证据汇总 `.superpowers/sdd/2026-10-09-adaptive-live/focus-resolution-paired-result.json` SHA256 `312b85016543dcd6b7f7cf89028f2eb874049deeda81fa32a6822ebd7730d84a`；adaptive03 proof SHA256 `b8a8c2c1d25071eeb45df23767987dc36b7759fd8dc996bb94afa9e2717023e4`；续账 `batch-budget-after-focus-resolution-paired.json` 为12/12、余0、43665 input tokens。Main只读复核73个证据文件/661源码哈希通过；Sol离线证据审阅不等于独立桌面验收。 / The paired evidence, adaptive proof and budget ledger were hash-verified by Main. Worker evidence review is not independent desktop acceptance.

下一步：Decision收到的remaining_plan只有动作类型与goal，缺少step_id、参数名、输入flags及后续成功条件；空allowed_states的provider措辞也有歧义。先修复有限上下文投影并用mock请求验证语义/秘密边界，不发送解析后输入值、不降低阈值。不能断言这些遗漏导致本次0.23/0.68审核概率。真实loading/observe、最终双语渲染、隔离安装和同候选独立实机仍未通过。 / Next repair bounded context projection and verify semantics and secret boundaries with mock requests. Missing semantics and ambiguous empty-state wording are confirmed; their causal effect on the review probabilities is unknown. Loading observation, final bilingual rendering, isolated installation and same-candidate independent desktop acceptance remain open.

## 2026-10-10 匹配先导与字段聚焦复测 / Matched pilot and focus regression

A使用preview.3精确源码714文件；大写request_id为Main调用方未入队拒绝，改为小写后真实准备仍在字段门禁失败，计划未开始。C同窗三步完成，Main审核3次、API0；B与C源码冻结、相对fixture、目标和策略外计划一致，但第三步VISTA点(90,102)落在字段下方，输入前not_dispatched、零点击/填写，2成功+1失败、API1。B少一次审核只是任务未完成，不是收益。原始证据及正常清理核对结果在 `.superpowers/sdd/2026-10-09-adaptive-live/matched-pilot-result.json`。 / A never started its task after a preserved caller error and genuine setup rejection. C completed all three steps; matched B failed the last focus before input. Fewer B reviews reflect incomplete work, not savings. Exact evidence and normal cleanup remain separately recorded.

新增Decision耗时1643.4189ms、HTTP631.7782ms、server508ms（包含关系），3329 input tokens。总账 `batch-budget-after-matched-pilot.json` 为10/12、余2、37061 input tokens；focus-intent-live-01不使用API。A/B失败不得与C完整运行比较提速，Main独占推理耗时和tokens未知。 / One call took 1.643s with 3,329 input tokens; nested timing is not additive. Failed work cannot establish speedup, and Main-exclusive time/tokens are unknown.

1. **失败 / Failure:** 长自然语言field_goal未被文字前缀解析识别为聚焦，尽管input_sequence已有有效内部字段scope，仍用普通点击提示并进入ROI。原生UIA字段存在，首步绑定也完整；不是丢失绑定。 / Typed focus intent was omitted from prompt/routing despite valid scope and complete UIA/binding.
2. **通用合同 / Invariant:** 输入步骤的字段意图不应取决于目标描述如何开头；整图方位不得被重新解释为裁图语境。 / Explicit internal focus intent must survive descriptive wording and image-context selection.
3. **修复层 / Fix:** `app/api/vision.py` 两个helper消费现有has_local_text_focus；显式单词、显式非input目标、strict-fill和plain-click请求shape保留。 / Two common vision helpers consume the existing scoped fact with existing exclusions.
4. **通用性 / Generality:** 适用于任何由维护input_sequence进入的普通字段，不增加7-Zip坐标、角色或应用特例。 / Applies to maintained field sequences without app-specific coordinates.
5. **回归 / Regression:** RED3失败/26通过；focused29通过；Sol相关230通过；Main13模块317通过/13.33秒，JUnit `main-focus-intent-integrated.xml`。真实新根 `D:/AgentReviewAcceptance/focus-intent-live-01` 证实interior提示及final_coarse_full/noROI生效，但模型在640×270图上输出[100,66]→(241,68)，真Edit y79–96、ComboBox y74–100。业务失败、零输入；保留首败，不重复抽点。 / Offline routing passes and live evidence prove policy activation; the coarse point still missed the thin field, so live business acceptance failed.
6. **安全影响 / Input safety:** 未放宽门禁、未夹点或伪造候选；text_field_target_not_writable在派发前拒绝。新窗口/host正常关闭、pending=[]、source661未变、bridge6636 exit0；proof SHA256 `34b014ec7d8e4990723c9c5bdad644864daffc0ca5ce2df8c00b9eec3285cd1a`。 / Rejection remains before input, with normal cleanup and unchanged frozen sources.

下一步仅用保存的新帧比较维护本地模型的图像尺寸与定位，先明确误差层再改默认策略；之后全新数据连续回归。未宣称正式版、总体准确率或收益通过。 / Next isolate image-size effects using the saved fresh frame before changing defaults and running a fresh continuous regression. No stable-release, general accuracy or benefit claim.

## 2026-10-10 7zip-06 非空后缀审核已通过 / Nonempty-suffix review passed

本轮根目录 `D:/AgentReviewAcceptance/adaptive-real-7zip-06`，新 owned 7-Zip 窗口、全新 fixture、同一四步计划。首步真实 API validated=true、success/review_required、needs_agent_review=0.20、off_plan_intervention_gray，remaining_plan=3；审核前后 trial_commands/trial_responses 映射精确不变且仅有首步。Main 审原图和剩余计划，review 返回 continue_required，再使用原 wait 才生成 read_reports。 / A fresh owned window and fixture ran one four-step plan. The first real Decision requested review with three remaining steps. Before/after review command and receipt maps were identical; only original-wait continuation generated the next step.

第三步 return_inbox 的真实 Decision 为 success/continue、adopted=true；condition_met=1、visible_error=0.09、needs_agent_review=0.04，自动执行末步。末步 always_main，不能冒充 Decision 主动审核。最终四个唯一 execution ID、4/4 success、runner completed、ticket/wait/pending 均空，原输入文件未变，无重放；bridge 15272 exit0，owned window 已不存在、host false、source 未变。 / The third step continued automatically through an authenticated Decision; the last step explicitly used always_main. Four unique execution IDs settled successfully without replay, and normal cleanup closed the owned window/host with unchanged sources.

OCR 正确读出 release-note-20261009.txt，但漏掉 source 文件夹；Main 从原图补全，read_complete=false 保留。观察器首次错误要求 read_text.action_executed=true，已仅为该只读步骤修正为 false；不涉及产品改动或动作重试。7-Zip 启动时记住旧目录，所有本轮动作均明确转到新 fixture，不采用旧学习资产。`boundary-before-review-return.json` 标签有命名偏差，实际 packet.step_id=reopen_reports_after_review，以原字段为准。 / Preserve incomplete OCR and the corrected observer assertion for read-only execution. Initial application directory memory is not accepted as a fresh test result. One boundary filename is historical; its actual packet identifies the final reopen step.

两次 Decision 耗时2706.7823/393.2442ms（HTTP1722.6896/384.5542ms，server502/219ms，均为包含关系），6680 input tokens、0 output；不等于端到端耗时或泛化收益。动作 command wall 依次15541.562、2946.394、7815.073、6902.284ms；Main等待另计，不将重叠分段相加。全批9/12、余3、33732 input tokens。 / The two Decision calls took 2.707s and 0.393s, using 6,680 input tokens; nested network/server timings are not additive. These are not end-to-end or population benchmark results.

Main `finalize_suffix06.py` exit0，证明文件 `D:/AgentReviewAcceptance/adaptive-real-7zip-06/main-final-cleanup-proof.json`，SHA256 `d3145b52c92e1e57ff87cf8520b10eb82bbb3f2496d7ea6789b6b27d89730c6c`；当前总账 B/`batch-budget-after-suffix06.json`。Sol ultra 只读核对首步证据、哈希、原wait与四步终结一致；不是独立桌面验收。本轮无产品源码修改，不重跑既有634项或重复打包。 / Main's persisted final proof and batch ledger passed; Sol independently checked original evidence only, not a desktop acceptance run. Product source was unchanged, so the existing 634-case suite and packaging were not repeated.

## 2026-10-10 最新结果 / Latest results

2026-10-10 用户已批准本批测试及同范围修复复测，无需重复申请；旧“未跑/待批准”仅为历史。 / The user approved this batch and in-scope repairs/reruns; earlier unrun/approval-pending wording is historical.

**Edge10 限定流程通过 / Bounded journey passed:** 同一 owned Edge 窗口完成 pathlib 搜索→打开→返回，再全文替换 asyncio→打开→返回，并正常维护关窗、host/pending 清理与源码未变；bridge 84460 exit0，API0。两次 `input_sequence` 均 completed/精确回读 matched；四次导航由 Main 核对标题和 URL，自动 `effect_verified` 仍 false。这不是自动 Decision 验证、准确率/收益、安装或独立验收通过。 / The six-request same-window journey and maintained cleanup passed with exact input readbacks and Main visual navigation review. All four automatic navigation-effect flags remain false; this establishes no automatic Decision, accuracy/benefit, installation or independent-acceptance result.

**最新离线 / Latest offline:** chrome Sol RED6失败/77过→86 passed/2.20s；Main26文件 **634 passed/19.19s**，含原扩组和 proof/sequence300，分组不累加。 / The chrome group and 26-file integration passed; overlapping groups are not summed.

**control_target 输入前证明已修复 / Pre-dispatch proof repaired:** 仅初始 typed 检查拒绝且未开始点击时生成 `recognition_pre_click_rejection.v1`，消费者严格核对 `control_target_check`；点击内 unknown、已点击 true 保持，真实 Decision 二次检查仍由原包装拒绝。RED12失败/62过→GREEN74，Main14文件300 passed/15.38s、Decision二次变化48 passed/5.37s，限定6文件只读审阅无阻断。旧9失败/283过是修前原件，不再作为当前未修项。 / Strict initial-rejection production/consumption passed its regressions without changing unknown/confirmed-input semantics; prior nine failures remain pre-repair evidence.

**chrome 采集与实测边界 / Chrome collection and live limits:** 明确导航且两类结构化目标均缺省时，provider直接同窗root chrome，不先full；默认full、pinned深复制隔离、1000预算、错误/截断无fallback、未采集父full不声明完整。Edge11纠正Main请求后限定六合法命令与维护清理通过，四次导航仍由Main看标题/URL，automatic effect=false，first_attempt_clean=false。两次返回各4.516747/4.234964s、UIA0.627339/0.656670s；与Edge10仅为两次场景观测，非匹配benchmark，不推广性能百分比。 / Corrected-request bounded live use and cleanup passed; preserve the caller failure and manual-effect limits, with no generalized benefit claim.

7zip-06 的真实 Decision 非空后缀审核门槛已通过。字段内部聚焦语义及尺度已修：经验证的普通聚焦默认1024整图，显式配置及原输入门禁保留；Main15模块397项/13.87秒通过。640实机首败保留；新根focus-resolution-live-02与adaptive-03在同一冻结源码下均完成三步及清理。两组Main审核均3次，差0；原命令wall为14.910/15.119秒，后组另有两次Decision共3.685秒，不宣称提速或准确率提升。当前预算12/12余0、43665 input tokens。下一步补齐审核上下文丢失的步骤/参数语义并做离线合同验证，不通过降低阈值掩盖不确定。真实loading/observe、最终双语/隔离安装及同候选独立验收仍未完成；下载仍preview.3。 / The real nonempty-suffix review gate passed. Verified ordinary field focus now preserves its intent and defaults to a 1024px full image, retaining explicit settings and input gates; Main passed 397 cases in 13.87s. Keep the initial 640px live failure. Two fresh runs completed all three steps and cleanup on identical frozen source. Both required three Main reviews, a zero reduction; original command walls were 14.910/15.119s, with two additional Decision calls taking 3.685s in the adaptive route. No speed or accuracy gain is established. Usage is 12/12, none remaining, with 43,665 input tokens. Next repair missing scoped step/parameter context and verify offline without lowering thresholds. Real loading observation, final bilingual/isolated installation and same-candidate independent acceptance remain open; published downloads remain preview.3.

随后完成v2审核上下文修复：步骤摘要保留ID、动作、参数名、flags及验证条件，隐藏输入值；超长在入队前拒绝，空allowed_states明确为未声明额外状态。Main相关441项离线通过（main-review-context-integrated.xml），未调用真实API；不把修前3对3结果转计新投影的效果。旧v2证据保持冻结，新投影不混入旧运行；v1保持原合同。下一步验证真实审核收益与loading观察，再完成最终双语/隔离安装和同候选独立验收。 / A subsequent v2 context repair preserves step IDs, actions, parameter names, flags and verification conditions while hiding input values, rejecting oversize before queueing and clarifying empty allowed_states. Main passed 441 related offline cases without real API calls. The earlier three-versus-three result does not measure this new projection. Keep old v2 evidence frozen and use new runs for the changed projection; v1 retains its contract. Real review benefit and loading observation, followed by final bilingual/isolated installation and independent same-candidate acceptance, remain open.

Edge05–09及匹配先导/640聚焦实机首败全部保留，不改记首次成功。当前预算 **12/12，余0，43665 input tokens**；未构建、提交或发布。下方旧余额均为各检查点当时状态。 / Initial failures are preserved. Current usage is 12/12, none remaining, with 43,665 input tokens; no build, commit or publication. Older balances are historical checkpoint values.

证据：`B=.superpowers/sdd/2026-10-09-adaptive-live/` 下 `input-contract-boundary/main-first.xml`、`edge08-graph-repair/main-green.xml`、`edge09-navigation-repair/{main-scoped-green,main-green,local-control-current-predicate,local-control-baseline-predicate}.xml`；Edge10 proof 为 `D:/AgentReviewAcceptance/adaptive-real-edge-10/main-final-cleanup-proof.json`。 / JUnit and the final live proof remain at these paths.

### 公共合同事件 / Shared-contract incidents

| 项 / Item | 有界结论 / Bounded finding |
| --- | --- |
| 1. 可见故障 / Failure | Edge08 两次 `task_plan_target_uia_incomplete` 零输入；Edge09 最终返回因整页 4000 截断而 `local_recognition_invalid`，零输入。 / Both stages refused before input; neither journey passed. |
| 2. 破坏的合同 / Invariant | 就绪路径接受已验证的完整规范图，目标解析却只接受 raw tree=true；明确中文工具栏导航语序未进入既有 chrome 范围。 / Canonical-graph completeness disagreed across consumers; an explicit localized navigation request missed chrome scope. |
| 3. 公共修复位置 / Fix | 共享uia_graph供readiness/target使用；control_target导航谓词进入既有chrome门禁；action初始typed proof与recognition_dispatch严格消费；provider直接同窗chrome。 / Common graph, admission, proof and collection paths. |
| 4. 为何非网站特例 / Why common | 统一共享目标/就绪合同与浏览器工具栏目标语序，不固化 Python 网站、页面坐标或临时控件。 / Common graph/navigation contracts without site or coordinate exceptions. |
| 5. 回归 / Regression | Graph Main568、nav scoped257及修前9/283原件保留；proof RED12/62→74，Main300，Decision48；chrome RED6/77→86，当前Main26文件634。分组重叠不相加。 / Preserve original failures and separate scoped/integrated evidence. |
| 6. 安全影响 / Safety | 原raw tree=false与身份/父边守卫保留；proof不降级unknown/已点击；chrome默认full、pinned隔离、1000预算，错误/截断不fallback，未采集父full不记complete；授权不变。 / Preserve evidence, identity, input facts and bounded-refusal gates. |

**首败留存 / First failures retained:** Edge05 窗口外同名副本造成歧义，零输入；只排除可证明全窗口外，部分/未知几何仍保留。Edge06 未 quoted label 的单次点击落在链接外，未重试。Edge07 打开/返回经 Main 核验后，填 pathlib 前 `text_field_label_unavailable` 零输入；1361 visited/1343 controls 对比旧名称预算1024支持预算耗尽的强推断，旧异常已被吞为 generic，不能写成绝对已证。Edge08 两次规范图拒绝，最后完整快照未持久化，不能套用 initial alias3/cycle1；Edge09 两次搜索 matched，导航经 Main 核验，最后返回零输入拒绝。各轮正常关窗/cleanup/source 不变及原失败保留，Edge09 proof SHA 为 `e46c45b3956cb3c8eb8989d30c27752c0d8e8aa2dc5ed75d98c90b447a214a1c`。 / Retain off-window ambiguity, the missed link, the bounded-scan inference, canonical-graph refusals and final-back truncation with their original cleanup evidence; no first failure becomes a first success.

Edge10 proof SHA：`3d5acd6cd0a196f90e899bcc6dd5e02fb30436313db60bb2fd5e04318f72e1f9`。

| 请求 / Request | 实测秒 / Measured seconds | 核验 / Verification |
| --- | ---: | --- |
| 001 pathlib 搜索 / search | 27.642880 | completed / matched |
| 003 打开 pathlib / open | 13.947191 | Main 标题+URL / title+URL; automatic=false |
| 004 返回 / back | 59.596994 | Main 查询页+URL / query page+URL; automatic=false |
| 005 全文替换 asyncio / replace/search | 30.316737 | completed / matched |
| 006 打开 asyncio / open | 23.701509 | Main 标题+URL / title+URL; automatic=false |
| 007 返回 / back | 9.642257 | Main 查询页+URL / query page+URL; automatic=false |

004 的既有 `browser_chrome` scope 完整、不截断、59 节点，`parent_scan_complete=false` 原样保留；UIA 56.001811s、VISTA 0.680797s。Edge09 007 拒绝耗时60.732538s，其中 UIA56.715605s、两次 VISTA0.698451/0.679013s。慢耗时已有测量归因；这些非匹配样本不证明收益。 / Scope facts and measured UIA/VISTA timings remain explicit; these unmatched samples establish no performance benefit.

此前分组原件继续保留：合同133；视口 RED6失败/8过→112/254过；请求边界18过；名称预算 RED3失败/1过→388/37过。主证据均在 B，分组可能重叠，不相加。 / Earlier contract, viewport, request-label and named-scan evidence remains preserved without summing overlapping groups.

实机原件在 `D:/AgentReviewAcceptance/adaptive-real-edge-{05,06,07,08,09,10}/` 的 `responses/`、`closed.json` 与已生成的 `main-final-cleanup-proof.json`。本次文档同步只核读原件，不启动测试或动作。 / Original receipts and cleanup proofs remain in their run roots; this update is document-only.

Edge11 原003把operation错误嵌套，MCP报 `ValueError: command fields do not match kind`，未生成 `runtime/commands/edge11-open-pathlib.json`；纠正明确新请求003b后成功，调用方首败保留，不记无失败首次通过。 / Preserve the malformed caller request and its pre-command rejection; success followed a corrected request.

| Edge11合法请求 / Legal request | 实测秒 / Measured seconds | 核验 / Verification |
| --- | ---: | --- |
| 001 pathlib搜索 / search | 28.669654 | completed / matched |
| 003b打开pathlib / open | 14.103662 | Main标题+URL / title+URL; automatic=false |
| 004返回 / back | 4.516747 | Main查询页+URL / query+URL; automatic=false |
| 005 asyncio搜索 / search | 29.849924 | completed / matched |
| 006打开asyncio / open | 23.886579 | Main标题+URL / title+URL; automatic=false |
| 007返回 / back | 4.234964 | Main查询页+URL / query+URL; automatic=false |

007后仍见Searching，额外007b只读图由Main确认Search finished（403页）；这段观察不计入007调用耗时。两次返回均browser_chrome/complete=true/truncated=false/visited59/budget1000/parent=null，UIA0.627339/0.656670s、VISTA0.624452/0.690098s，未先采full。 / The extra readonly settled-search image is separate from Back latency; both returns used complete bounded chrome without a prior full scan.

008正常关窗与host/pending清理、source unchanged，bridge76380 exit0。Main finalize退出0；proof `D:/AgentReviewAcceptance/adaptive-real-edge-11/main-final-cleanup-proof.json`，SHA `b6e37c9866aa4b07e93c198f895cf02d6ba4ba176b6e446f01a0f2f2cf437083`，business_journey_passed=true、first_attempt_clean=false。 / Normal maintained cleanup passed; the corrected journey passed with its first caller error retained.

证据：B下 `control-rejection-proof/{red,green,decision-revalidation,main-integrated}.xml`、`SOURCE_CHANGE.md`，及 `edge10-chrome-performance/{red,green,green-final,main-integrated}.xml`。634是当前离线冻结组合，不把旧分组累加或转为实机收益。 / These artifacts separate proof, collection and integration evidence from live acceptance.

**Edge12真实加载检查 / Real loading check:** API validated=true，三项概率0、still_progressing=0.36，failure/review_required、adopted=false；未observe/未追加capture，加载门槛仍未通过。原输入completed/action=true，单条trial-exec，随后cancelled/pending=null及维护清理成功；不盲复试或降阈值。Edge12完成时预算 **7/12余5，27052 input tokens**；Edge05–11新增0，Edge12新增1。 / The real check was validated but did not enter observation; original input and successful cancellation/cleanup remain distinct. One added call brings the batch to seven of twelve, five remaining.

**本地请求体核对 / Local request-body inspection:** Main执行B/`inspect_edge12_request_body.py`，exit0；使用真实`prepare_request`与`OpenAIDecisionsProvider`，强制`httpx.MockTransport`，网络调用0。规范化binding所有字段与原件一致；4个question完整，loading_condition全文保留；唯一after PNG为1410×1032，base64解码SHA与原图`a6809fb1e9c8f665e09a0189eb326671185b7986fe67eb84f46b3931384525c2`一致。B/`edge12-request-body-inspection.json`仅存问题、角色、MIME、尺寸、哈希等脱敏结果，不存headers/密钥/图像base64。Sol静态审阅也未发现固定0.36或跨会话缓存。此项是本地源码重建，不是旧线上请求的抓包；远端低置信原因仍未知。 / Main's zero-network reconstruction through the real builder/provider preserved every binding field, all four questions and the original image bytes. The retained report excludes secrets and encoded image data. This is local reconstruction, not a capture of the prior HTTP request or proof of remote processing; low confidence remains unexplained.

Edge12原after明确可见asyncio/Searching...；condition_met/visible_error/needs_agent_review均0，still_progressing0.36→failure/review_required，adopted=false。仅assessment_round0，ledger为opened/assessment_claimed/assessed/finished，observe与新增capture均0；API一次，2632 input/total tokens，elapsed2.8329842s、HTTP2.2150483s、server0.873s（分层不相加）。 / The validated round-zero assessment did not observe again; timing layers are not additive.

相对 `--decision-profile` 首次启动在host前被 `explicit_absolute_decision_profile_required` 拒绝（exit1），纠正绝对路径后ready；调用方首败保留，没有动作重放。原输入completed/action=true、仅1条trial-exec；cancel_requested后003 status证实cancelled/pending=null，004正常close，bridge32853 exit0、host=false/pending空/source unchanged/window gone。 / Retain the caller startup failure, unchanged completed-input fact and later cancellation/maintained cleanup.

Main finalize退出0；proof `D:/AgentReviewAcceptance/adaptive-real-edge-12/main-final-cleanup-proof.json`，SHA `e587a4bcfca0cf6349076d741ceb08d4d437bfa32e807a93eaa9c0a92d3d9dc9`。Edge12阶段预算原件B/`batch-budget-after-edge12.json`为used7/request_cap12/remaining5/input_tokens27052；旧6/12只适用此前阶段。 / Preserve the final proof and current budget artifact; the six-call total is historical.

## 以下为此前检查点（历史） / Earlier checkpoints; historical

旧“未跑/待批准”只描述当时状态，不继续阻拦上述已批准范围。 / Earlier unrun/approval-pending wording does not block the approved scope.

**2026-10-10 源码修复，待测 / Source repair, untested:** 独立学习包的回执校验反向导入执行器，静态上会命中构建 forbidden。现已将原输入请求模型与纯目标校验提取到 `app/core/input_sequence_contract.py`、`app/core/control_target_contract.py`，执行端保留原导入入口；未放宽打包排除或校验规则。已补兼容与实际源码收集回归用例，尚未运行；此前255/43项不验证本次提取。详情：`.superpowers/sdd/2026-10-09-adaptive-live/input-contract-boundary/SOURCE_CHANGE.md`。 / A shared receipt reader imported the forbidden executor into standalone learning collection. The original strict request model and pure target validator now live in shared core modules with legacy re-exports. Build exclusions and validation rules remain unchanged. Written compatibility/source-collection regressions await approval; prior 255/43 results do not cover this extraction.

**历史授权限制（本批已获批准） / Historical restriction; batch approved:** 用户最新要求“继续代码开发，测试向我要申请”。当前只做源码开发与只读审阅；离线、桌面、真实 API、构建和安装验证均须提出具体范围并获批准。以下运行结果均为暂停前历史证据，本轮没有新增测试。 / The latest request allows source development and read-only review. Request approval for each concrete offline, desktop, real-API, build or installation validation batch. Recorded runs below predate the pause; no tests ran in this resumed slice.

**Reader 源码收拢 / Reader source completion:** Value/Text 分歧修复及回归用例已写入，限定静态独立审阅无阻断发现；Main 已核对报告和关键源码。已绑定、明确可写、非密码且范围 owner 一致的 Edit/既有 ComboBox 可用 Value 作全文替换与精确回读依据；分歧禁用选区与追加，双读同时比较两种模式，异常/身份检查保持。诊断仅增加 field_reads sidecar，旧 v1 snapshot shape 保持。Main 255 passed / 4.61s 是暂停前结果，不是本轮复测；真实 Edge 尚待批准后验证，不宣称搜索已恢复。 / The implemented slice has no blocker in bounded independent source review, inspected by Main. Writable, non-password, same-owner bound fields use Value for full replacement/readback; disagreement disables selection/append, both pattern summaries participate in double reads, and existing identity/error checks remain. Diagnostics are sidecars without changing v1 snapshot shape. The 255-case Main run predates the pause; real Edge recovery remains unverified.

UI05 翻译跟进：界面库三种状态改用既有 tr，反馈两侧标题改用既有 ui/tr 绑定；无字典/qm 改动。Worker 保留4例 RED 后相关25项通过；Main 合并表单可访问性、英文显示、i18n、步骤 UI 回归 **43 passed / 33.54s**，证据 `main-workbench-ui-integrated.xml`，diff check 通过。运行中切换语言保留用户文字和比较状态；修复后的英文实机效果仍待最终候选复核，不重复计入此前 UI04/05 实机结果。 / UI05 localization now binds the three library statuses and both feedback captions through the existing translation helpers. No catalog changes. Worker retained four RED cases before 25 relevant passes; Main independently passed the integrated 43-case suite in 33.54 seconds. Language changes preserve user content and comparison state. Post-fix live English rendering remains part of final-candidate acceptance.

Date: 2026-10-09, Pacific/Auckland. In progress; this is not stable-release acceptance. / 正在进行，不代表正式版验收通过。

## UI04/05 latest checkpoint / 工作台最新检查点

本轮复用 Learning01 新产生的库，未读取旧验收资产。公共 `ui(QFormLayout.addRow, string, QWidget)` 原先创建 QLabel 后缺少 buddy，导致原生字段 Name 为空；最小修复只恢复 QWidget 重载的标签关联。保留 `workbench-form-red.xml`（1 failed/1 passed），新可访问性+i18n+步骤 UI 回归 `workbench-form-green.xml` 为39 passed、33.40s。UI04 原生 Step name / Field target 名称随后现场确认。 / This journey reused only the fresh Learning01 library. The shared Qt label wrapper lost its buddy association; the narrow repair restored native field names while preserving layout/spanning overloads. Retain the initial RED and the 39-case targeted green result; UI04 confirmed actual accessible names.

| 范围 / Scope | 实际证据 / Observed evidence |
| --- | --- |
| 编辑、保存、重开 / Edit, save, reopen | UI04 将首步改为 Open reports folder，Save 后 program revision3 精确读取；正常关闭后 UI05 同库重开，原图及后续读取确认名称保留。其余 definition 与 revision2 精确一致。 / Only the first step title changed; persisted revision three survived actual reopening. |
| 反馈与采用 / Feedback and adoption | UI05 007/008 真实输入反馈；011 公共 learning_feedback.submit 只存候选；017 实际比较显示唯一 meaning 修改，018 采用，020 主窗显示新 revision2。 / Public submission did not adopt content; explicit UI comparison and adoption produced the new standalone revision. |
| 原引用 / Pinned references | 原 program revision2 与 Learning01 最终读取精确相同；revision3 与 UI04 保存读取精确相同；load_snapshot 校验原 project pin、旧 interface-version-649044… 引用，截图哈希/regions 不变。 / Exact programs and the validated frozen snapshot retain the old interface reference. |
| 首败与恢复 / Preserved failure | 013 的静态 Feedback history 标题与 VISTA 列表项点冲突，action_executed=false；015 使用项文字的新请求通过。018 派发后 dialog 正常关闭，after unavailable；发现并重新选择原 root，再用实际截图和存储核验，无动作重放。 / Preserve the pre-input refusal and the closed-dialog observation; neither was silently converted into success or replayed. |
| 正常收尾 / Cleanup | UI04/05 maintained close、原 HWND/PID 消失、host/pending 空、source/harness 重验不变；桥2601/67492 exit0。 / Both sessions completed maintained cleanup and frozen-source checks. |

Main 执行 `finalize_workbench_ui05_evidence.py` exit0，汇总原件 `D:/AgentReviewAcceptance/adaptive-real-learning-ui-05/main-final-cleanup-proof.json` SHA256 `d70a63955c19a3b4e91ebe4c2eecfaed34ace42e0f947840ec85aa08568b587f`。只读核对时首次把 live project 的 null snapshot_id 与固定 pin 相比属于检查器假设错误；修正为加载固定快照后验证，原产品数据未改。UI01 launcher 身份错配、UI03 字段名故障仍保留为首次失败。 / Main's evidence checker exited zero. Its initial assumption about a live view's null snapshot ID was corrected by loading the pinned snapshot; product data was unchanged. Earlier launcher and field-name failures remain recorded.

Decision0、外部视觉0，本地定位仍用模型；预算6/12、余6。英文状态/比较标题仍有中文残留；浏览器字段、复杂连续流程、真实 loading、主动审核非空后缀、同口径基线、安装及同候选独立验收尚未完成。以上是有界 UI 旅程通过，非正式版或通用准确率结论。 / No external calls were added. Remaining localization, browser, observation, review-suffix, benchmark, installation and independent acceptance gates remain open; this bounded UI result is not stable-release or general-accuracy acceptance.

## Learning01 checkpoint / Learning01 此前检查点

证据根 `D:/AgentReviewAcceptance/adaptive-real-learning-01`；只使用本轮新目录、原始录制回执与截图。7-Zip 初始记住的旧目录在录制前已导航离开，没有作为学习证据复用。程序固定为 `task-program-78d67e9c551150e108a2ebcf9ecfb850a88b9ca05fd3badbf7c370a6721f8bfb`，revision2；三个试运行前后精确读取相同 program SHA/project snapshot。 / Only newly recorded evidence was learned. Navigation left the application's remembered old directory before recording. Revision two and its pinned snapshot read back unchanged before and after reuse.

| 范围 / Scope | 实际结果 / Observed result |
| --- | --- |
| 录制与生成 / Recording and synthesis | 2个真实 input_sequence completed，Main 原图审核，stop 完整、pending0。首次 Main 示例路径分隔符错误被哈希拒绝；同 synthesis/source 一次纠正 draft_ready。 / Two completed recorded actions; one preserved caller-side example-string failure followed by the allowed correction. |
| 审核保存 / Review and persistence | 首次 pending revision1，精确read；只改 review_status 后 revision2，精确read；未伪造用户签审。 / Pending save, exact read, then review-only save and exact read; Main review is not human UI sign-off. |
| 同参数单步 / Same-parameter single mode | 025：两步 completed，rule/rule，图像分数均1；核验分别121.7294/121.6625ms。 / Both steps matched and completed. |
| 更换参数 / Changed parameter | 031：目标改为 reports/source/2026；旧图像9次均不匹配（分数0.1607159，阈值0.95），约2095.0844ms后停在原请求；Main 看原回执与真实summary.txt/地址后审核，原wait继续返回，agent/rule，两步completed。 / Valid mismatch required Main review; no action replay or false template success. |
| 同参数连续 / Same-parameter continuous mode | 034：until_wait连续两步completed，中间无Main审核，rule/rule；核验251.7735/125.7614ms。两条输入回执首开始至末结束12915.265ms，**不含最终核验及调用方规划**，不能当完整用户耗时。 / Two continuous rule-verified steps; the stated input-receipt span excludes final verification and caller planning. |
| 调用与清理 / Calls and cleanup | Decision0、外部视觉0；本地定位模型仍使用，整体model metrics覆盖partial，不能称全部模型0。037维护关窗成功、原HWND/进程消失、host停止/pending空；659源码文件和harness重新核验不变，桥21483 exit0。 / No external calls; local grounding remains. Maintained window/host cleanup and frozen-source checks passed. |

Main 使用 `finalize_learning01_evidence.py` 重验原文件摘要、三轮六条唯一执行票据/终态、图像哈希、原程序保持及收尾，exit0。汇总 `main-final-cleanup-proof.json` SHA256=`32df8d3d83dd50af93ccd52282c8f3fd3cec02e2d9a76b51f4bcb033369deca8`；预算续接 `batch-budget-after-learning01.json` 为 **6/12，余6，24420 input tokens**。这不是新离线测试总数，不与258/862或worker重叠检查累加。 / Main revalidated original evidence, unique completed tickets, images, pinned content and cleanup; the evidence checker exited zero. Accounting remains unchanged, and these checks are not added to overlapping offline suites.

尚未验实际工作台展示/正常关闭同根重开、反馈比较采用后旧pin、新学习定位规则或匹配旧版本收益。六步局部成功不能推出通用准确率；变参后的Main介入耗时保留。浏览器reader候选合同已有只读审计但尚未修复，其他正式版门槛不因此关闭。以下是此前的Edge/R5检查点。 / Actual editor reopening, feedback adoption/pins, learned grounding and matched baseline benefits remain open. Six scoped actions do not establish general accuracy; retain the review delay. Browser reader design has only a read-only audit, not a repair. Earlier checkpoints follow.

## Edge04 checkpoint / Edge04 此前检查点

证据根 `D:/AgentReviewAcceptance/adaptive-real-edge-04`。真实地址栏 input_sequence completed/action_executed=true，访问 vscode.dev 后原 after 仅白页及标签 loading 图标。真实 Decision validated：condition_met=0、still_progressing=0.36、visible_error=0、needs_agent_review=0.01，返回 failure/review_required；未达到 observe，assessment_round=0，无后续 capture/API。唯一1次 API 使用2631 input/total tokens；不计自动 loading 观察或完整工作台成功。 / The real address sequence completed, but the original after showed only a white page and loading tab icon. Validated Decision probabilities yielded failure/review_required at round zero, without entering observe or making a follow-up capture/request. The single call used 2631 tokens; this is neither automatic-loading nor workbench-completion acceptance.

Main 对原 run 执行 cancel→cancelled，原输入仍为 completed/action_executed=true，仅1条 trial-exec、无重放。维护关窗成功，原窗口 Gone、host_alive=false、pending_ids=[]、cleanup/source/harness 核验通过，桥87985 exit0。`main-final-cleanup-proof.json`（SHA256 `aa33b0400377de4cdc0d06b17d9c2122457d81059049c1d76760cd65fcc8daf5`）记录 review_handoff_and_cancel_passed=true、loading_observe_passed=false、business_workbench_completion_passed=false。这只计真实审核交回→取消→清理通过；focus-only 故障取消分支仍仅离线覆盖。 / Cancellation terminated the original run while preserving completed input and one execution command without replay. Maintained window/host cleanup passed with unchanged source/harness and bridge exit zero. The proof passes review handoff and cancellation, while explicitly rejecting loading/workbench acceptance; focus-only failure cancellation remains offline-only.

最新批次预算以 `.superpowers/sdd/2026-10-09-adaptive-live/batch-budget-after-edge04.json` 为准：**6/12，余6，累计24420 input tokens**。Edge02/03各0次、Edge04新增1次；下方5/12保留为此前检查点，嵌套耗时不相加、不作匹配收益结论。全新学习主链与实际 observe/loading 后续仍待完成。 / Latest verified accounting is **six of twelve calls, six remaining, 24420 input tokens**. Edge04 added one call; earlier five-call entries remain historical. No matched-benefit claim follows from nested timing. Fresh learning and actual observe/loading follow-up remain open.

## R5 latest checkpoint / R5 最新检查点

R4 公共派发边界修复由 Main 独立运行相关十文件，240 项通过，证据为 `.superpowers/sdd/2026-10-09-adaptive-live/r4-terminal-repair/main-regression.xml`。仅点击前只读字段校验拒绝可生成严格未派发证明；进入点击后的未知结果仍保持未知，已确认输入不能被后续失败抹除。动作、序列、终态与学习共用该证明，不放宽目标或输入门禁。 / Main independently passed 240 related cases for the common dispatch-boundary repair. Strict pre-click rejection proof preserves no-input facts across action, sequence, terminal and learning consumers; unknown dispatched effects and confirmed input remain distinct. Gates are unchanged.

全新 `D:/AgentReviewAcceptance/adaptive-real-7zip-05` 实机验证了 recognition-plan 与 pre-click-validation 两种零输入拒绝。同一较弱描述仍产生工具栏错点，失败保留；Main 明确调整描述、关闭已知零输入的旧计划并创建 successor 后导航成功。相同逻辑 successor 再查询未增加执行命令。不能据此宣称视觉模型稳定性已修复。 / Both no-dispatch stages were verified live. The original description still missed the field; an explicit Main replan succeeded after closing the known-zero-input parent. Repeated logical successor lookup added no execution command. This is not a general grounding-stability fix.

同一真实窗口完成进入 reports、读取真实文件名、返回三步。返回成功时真实 Decision 给出 `success/review_required`，原票据暂停，Main 核对原图后执行 review，再以原 wait 明确 continue；`responses/012-continue-finish.json` 证明三步 completed。该主动审核发生在最后一步，不计为阻止非空后缀的实机证据；中间读取步骤的普通 Main 审核确实阻止返回步骤，直到明确继续。 / The same real window completed reports navigation, filename reading and return. A real success/review-required decision preserved the original ticket until Main reviewed and explicitly continued. Proactive review occurred on the final step; nonempty suffix blocking was shown only for the ordinary middle read review.

`responses/013-close.json` 及 `closed.json` 证明维护关窗成功、宿主停止、pending 为空、cleanup_verified=true，运行期间 source/harness 未变；原桥进程 exit 0。本轮六条 trial-exec 命令、三个 Decision 产物，批次累计五次 API、余七次。旧 R2 未知业务事实保留；其人工收尾的最新证据见下一节。 / Maintained close and stopped-host receipts confirm cleanup, no pending input and unchanged frozen source/harness; the bridge exited zero. R5 has six execution commands and three Decision artifacts; the whole batch has used five of twelve calls. R2's unknown business result remains unchanged; its later manual cleanup is recorded below.

仍未验收：真实声明 loading 观察链、弹窗/中断连续覆盖、外部浏览器复杂流程、全新学习保存重开和变参复用、匹配收益对照、最终安装及同候选独立验收。以下旧检查点按发生顺序保留，不把后续成功改记首次成功。 / Loading, dialogs/interruption, complex browser use, fresh learned reuse, matched benefits, final installation and independent same-candidate acceptance remain open. Earlier failures below remain historical failures.

## Latest Edge checkpoints and R2 cleanup / Edge 最新检查点与 R2 收尾

Edge01 证据根为 `D:/AgentReviewAcceptance/adaptive-real-edge-01`。`main-first-failure.json` 与 `quick-search-pattern-probe-first.json` 证明 Quick search 正确聚焦后，ValuePattern 为 `""`、TextPattern 为 `"Q"`，触发 `TextFieldReadError` / `text_field_value_patterns_disagree`；仅完成 focus，未执行 type、Enter 或 submit，API 使用为 0。原计划进入 `cancel_requested` 后未终结，`responses/006-close.json` 因 `task_plan_run_active` 拒绝 owned close。`main-host-stop-proof.json` 证明宿主已正常 stopped、cleanup_verified=true、host_alive=false、pending_ids=[]，截至 stop 源码未变。 / Edge01 focused the real Quick search field, then refused conflicting Value/Text evidence before typing or submission. Its nonterminal cancellation blocked owned close; normal host stop subsequently verified cleanup and no pending commands.

用户随后人工关闭 Edge01 原窗口；Main 核实原 HWND 3737662 已消失、bridge 43414 exit 0。`closed.json` 的 owned_window_closed、cleanup_verified、source_unchanged、harness_unchanged 均为 true，closure_source=`externally_observed`、automatic_cleanup_success=false。该人工收尾不计维护关窗或完整业务通过。公共 focus-only 终结合同随后由 Main 独立完成十文件258项离线复验（17.58s、exit0），证据为 `.superpowers/sdd/2026-10-09-adaptive-live/edge-focus-partial-repair/main-regression.xml`，冻结为同目录 `main-reviewed-freeze.json`；其后续窄合同实机证据见下一段，reader 仍未修。 / The user later closed the original window. Verified external closure and clean bridge exit do not convert the failed search journey into a pass or maintained-close success. Main subsequently passed 258 offline cases for the common focus-only terminal contract. Its later narrow live verification is recorded below; the reader remains unchanged.

最新 Edge02/Edge03：全新 Edge02 独立 focus→readonly range probe 返回 observed、范围 Q，reader 冲突未修；维护关窗、host cleanup/source/harness 核验 true，bridge36342 exit0。全新 Edge03 同原搜索计划复测在 focus 后重现相同 TextFieldReadError，未 type/Enter；真实 producer partial proof 经 Main 独立重验，原计划 status=failed、original_input_status=failed、action_executed=true、pending 清空。维护关窗成功，原 HWND Gone、host_alive=false、pending_ids=[]、cleanup/source/harness=true，bridge43788 exit0。`D:/AgentReviewAcceptance/adaptive-real-edge-03/main-final-cleanup-proof.json`（SHA256 `562027a5976b769f365613a30d4dd0ac0c6ec9ebde588965f48d5316d835d5ba`）记录 narrow_contract_passed、business_search_passed=false、field_reader_fixed=false。这只证明公共 partial 失败终结和维护收尾窄合同通过，真实 cancel 分支仍仅离线覆盖；两轮均0 API，批次仍5/12、余7。 / Fresh Edge02 independently focused and observed range Q, then completed maintained cleanup. Edge03 reproduced the search reader failure but independently verified genuine partial proof, failed terminal status with dispatched focus, an empty queue and maintained cleanup. Both bridges exited zero with unchanged source/harness and no API use. Only the narrow partial-failure terminal contract passed live; search/reader remain unresolved and actual cancellation has only offline coverage.

R2 已完成单独人工收尾。`D:/AgentReviewAcceptance/adaptive-real-7zip-02/main-final-cleanup-proof.json` 引用 `.superpowers/sdd/2026-10-09-adaptive-live/r2-readonly-20261009-075046.json`，证明原窗口及进程 gone、宿主 stopped/cleanup_verified=true、pending_ids=[]，原 session 文件未变。Main 先确认旧 bridge 11180 仍活跃，仅在应用及宿主均已消失后发送 Ctrl+C，exit 1 属有意结束旧桥；旧桥未实现外部关窗检测。这不计 maintained close 或业务通过，原 unknown/cancel_requested 票据未重放或改写；R2 应用及桥不再待关闭。 / R2's final cleanup proof confirms the original application and host were absent before Main intentionally stopped the legacy bridge with Ctrl+C (exit 1). This is neither maintained-close nor business success; original unknown/cancel facts remain unchanged. R2 no longer awaits application or bridge closure.

本批预算累计使用 **5/12**，余 **7**；以下旧检查点中的待收尾描述保留为当时事实，当前状态以本节为准。 / The batch has used **5 of 12** calls, with **7 remaining**. Earlier pending-cleanup entries remain historical; this section supersedes their current status.

## Authorization and environment / 授权与环境

The user authorized tests toward a stable release after reviewing the five remaining release gates. Main uses maintained project capture/action interfaces, fresh data and individually owned real application windows. Native Codex Computer Use remains disabled. / 用户批准测试并朝正式版推进，Main 仅通过项目维护接口操作本轮新窗口，数据全新；原生 Computer Use 继续禁用。

The previously used clean interpreter no longer exists. This batch uses `D:/agent-gui-runtime/.venv/Scripts/python.exe`, with missing pinned MCP 2.1.1 and PySide6 6.11.2 added. No pre-existing package was upgraded; package inventories are retained in `.superpowers/sdd/2026-10-09-adaptive-live/`. `uv pip check` passed for 118 packages. An early collection attempt ran before Qt installation completed and failed; once installation returned exit 0, the same five-file group passed **196 tests in 11.68 s**. This environment check does not replace the earlier 862-case source evidence or live acceptance. / 本轮补齐环境缺包，无原包升级；首次环境测试因安装未结束而失败，保留记录，安装完成后原组复测通过，不混作产品故障或实机成绩。

## Main 7-Zip first attempt / Main 首次 7-Zip

Evidence root: `D:/AgentReviewAcceptance/adaptive-real-7zip-01`.

- A new installed 7-Zip window launched through the public MCP path. Window handle, PID and process birth were bound; fresh directory contents and source hashes were recorded. Capture and the bounded native control observation succeeded. / 新建真实 7-Zip 窗口，经正式入口启动、绑定完整身份，截图与原生观察成功。
- The first v2 single-step plan attempted to enter this run's `release-inbox` path, then verify that `drafts` and `reports` were visible. It failed during focus **before any input**, with `text_field_target_not_writable` and `focus_input_not_confirmed`. Decision was not invoked by the failed action. / 首个单步计划在聚焦门前失败，零输入，动作链未调用 Decision。
- Raw grounding point: capture `(256,77)`, screen `(256,100)`. The raw hit was the address `ComboBox`; its writable `Edit` child began at capture y=79/screen y=102. The coordinate transform was consistent. The parent passed the Value-pattern check but lacked Text; `attribute_class=unknown` represented a missing pattern, not proof of read-only state. / 点在组合框上沿、可写子框外两像素；坐标转换无错，父框缺 Text 接口，不能因此直接放行。
- Root invariant: composite-field grounding must resolve a precise writable field before focus input. A generic model point inside the containing combo is insufficient. The existing refusal was correct. The pending repair belongs in common composite-field resolution and must retain child uniqueness, scope, current identity, geometry and final writability checks. / 待修的是公共复合字段解析，现有拒绝正确；不放宽父框可写判断，不为 7-Zip 写特判。
- The original failed plan terminated as failed; no automatic replay occurred. The owned window closed normally and host cleanup verified; source hashes were unchanged during the run. / 原失败不改记成功、未自动重放，本轮窗口与宿主正常清理，源码运行期间不变。

Original input receipt: `runtime/session-a6e5c39ee8604019b413949a583c4335/responses/trial-exec-94334af2a6f7131a451914d26487e846.json`. Main client result: `responses/002-open-fresh-folder.json`. Cleanup: `closed.json`.

## Real v2 API calibration / 真实 v2 API 校准

One bounded call used the newly captured initial 7-Zip image. Main visually confirmed that the requested test folder was not open. This is a screenshot calibration, not evidence of a successful action or full workflow. / 仅用本轮初始真实截图做一次负例校准，Main 已读图确认目录未打开，不算动作或工作流成功。

| Measurement / 项目 | Result / 结果 |
| --- | --- |
| Real requests / 实际请求 | 1; shared session cap 12, remaining 11 |
| Expected condition / 预期条件 | False / 不成立 |
| Returned / 返回 | `completed`, verdict `failure`, disposition `review_required`, adopted `false` |
| Predicates / 概率 | condition 0.00; visible error 0.31; Main review 0.72 |
| Authentication / 认证 | Passed against the original request / 原请求认证通过 |
| Measured wall / 外部总耗时 | 2921.833 ms |
| Service / 服务层 | 2915.119 ms |
| HTTP round trip / HTTP 往返 | 2293.195 ms |
| Server-reported processing / 服务端报告 | 613 ms; included in HTTP, not added to it / 已含在 HTTP 中，不相加 |
| Tokens / 用量 | 4258 input, 0 output, 4258 total |

Evidence: `api-calibration-negative-01.json`. Credentials were not printed or copied into artifacts. A single negative case establishes API/protocol connectivity and this case's non-adoption only; it does not establish general accuracy or latency percentiles. / 证据不含密钥；一个负例只证明本次接口连通与未误放行，不证明通用准确率或延迟分位数。

## Packaging preparation repair / 交付准备修复

Read-only review found that the new adaptive profile example was linked in usage documentation but omitted from execution resources. The existing isolated Decision probe also exercised only v1. The resource is now included; the public checker additionally exercises real v2 service/evidence/persistence/authentication code with a mock provider and synthetic PNGs. It covers loading observation, a later completed assessment, successful outcomes requiring review without adoption, zero-request policies and readonly reopening with rejected binding tampering. / 新配置示例漏包以及包内探针仅覆盖旧协议已修复，使用真实服务与持久化、模拟网络边界验证新版依赖。

- Worker reproduction: **5 failed, 1 passed**; repair group: **12 passed, 1 deselected**, 66.14 s. / 工作者保留首败与修复后成绩。
- Main inspected the four-file diff and independently ran the related group: **12 passed, 1 deselected**, 57.43 s. Evidence: `.superpowers/sdd/2026-10-09-adaptive-live/main-packaging-contracts-rerun.xml`.
- Main initially used an incorrect exclusion expression; that attempt was explicitly interrupted before the final full-build case. The corrected command uses `-k 'not real_payload'`. The full component build case is intentionally not included in this preparation result. / Main 首次排除表达式写错，已在最后整包构建用例前中止；改用确切过滤后复测，不声称完成整包构建。
- The copied temporary payload is checked with an isolated `-I` subprocess outside the source checkout; project module paths must stay in the copy. No API keys, HTTP, GUI or installed product are used by these checks. / 临时复制载荷由树外隔离子进程检查，不能从源工作树补导入；不使用凭据、真实 API 或桌面。

Command / 命令:

```powershell
& 'D:/agent-gui-runtime/.venv/Scripts/python.exe' -B -X utf8 -m pytest -q --tb=short --junitxml=.superpowers/sdd/2026-10-09-adaptive-live/main-packaging-contracts-rerun.xml tests/test_execution_decision_closure.py tests/test_execution_component.py -k 'not real_payload'
```

## Main 7-Zip second attempt / Main 第二次 7-Zip

Evidence root: `D:/AgentReviewAcceptance/adaptive-real-7zip-02`; fresh window/session and files. / 新建窗口、会话与数据。

- Common composite-field resolution was frozen after the worker's RED case. Main inspected the implementation and independently ran 13 related files: **374 passed in 4.67 s**, `main-composite-field.xml`. The original parent ComboBox writability rule remains intact. / 公共字段修复保留父框门禁，Main 独立回归通过。
- The fresh address-input plan completed through the public runtime. Main inspected its original after-image and confirmed `drafts` and `reports` under this run's `release-inbox`. Real Decision returned condition 1.0, visible error 0.0, Main review 0.0, `success/continue`, `adopted=true`, with authenticated original evidence. / 地址输入单步完成，Main 原图核对与真实 API 判断一致。
- This positive call used **4373 input tokens**, measured service **2490.999 ms**, HTTP **1504.484 ms**, server-reported **596 ms** (included in HTTP). Including the separate first negative calibration, the batch has made **2 requests, 8631 input tokens**, with 10 of the initial 12 requests remaining. / 两例不构成准确率或性能分位数评估。
- Main's next plan declared `reports/Edit` for a folder double-click. The native list label has no writable text pattern; the existing explicit Edit target contract correctly refused it with `task_plan_target_field_not_writable`, before input and without Decision. This is a caller target-selection failure; the plan must use a supported navigation action rather than disguise a ListItem as a writable field. / Main 目标声明不满足已有合同，保留零输入拒绝，不放宽门禁。
- That refusal exposed a separate product recovery defect: the local receipt defaulted to `phase=result_unknown`, while its nested `agent_step_result` explicitly reported `action_executed=false` and zero attempts. The plan verifier persisted `original_input_status=unknown`; cancellation remained `cancel_requested` after a 45-second wait. The owned-window close request was then refused as competing input. / 前置拒绝的零输入事实在公共回执中丢失，使取消与自建窗口收尾一起受阻。
- **The second continuous journey has not passed.** No input was replayed or reviewed into success. Main has since called the maintained `InstantSession.stop()` after checking the original host/runner identity. The host exited normally: `cleanup_verified=true`, no pending input, and source unchanged until stop. The owned test window remains open awaiting requested manual closure; the original bridge connection is retained. The old plan remains `cancel_requested`. Host cleanup does not prove application cleanup or business success. / 本轮连续验收失败，未重放或伪结算。Main 核对原宿主身份后经维护 stop 正常停止，宿主清理通过、无待执行输入、停机前源码未变；测试窗口仍待手动关闭，原桥连接保留。旧计划保持取消请求状态，不把宿主清理当作完整收尾或业务通过。
- A second display defect is confirmed: normal host Decision use advanced the durable ledger to used=1/remaining=10, but `instant_status.decision_service` still showed the startup 0/11 snapshot. Dispatch checks the actual transactional ledger, not this display. The status projection needs correction; no budget reset is authorized. / 预算显示过时，实际派发门禁仍读事务账本；须修状态投影，不重置预算。

Positive receipt: `runtime/session-333864b6b52d4c3d974887e6f828aa8c/responses/trial-exec-c9e7db06f875a48c71292ab3caaf3d59.json`; assessment: the matching file under `task-plan-decisions/`. Rejected click receipt: `responses/trial-exec-4a1a85fdfc4b25e8d203c0a84e55330c.json` under that session. Cancellation: run-root `responses/004-cancel-unsupported-target.json`; close refusal: `close.json`.

Normal host-stop evidence: run-root `maintained-stop-request.json` and `main-maintained-stop-proof.json`. No process was force-killed and no original receipt was rewritten. The original R2 bridge still lacks an external-window-closure exit path and remains frozen; the later integration is recorded separately below. / 正常停机证据如上，未强杀进程或改旧回执；原R2桥仍冻结，后续接线候选另记如下。

## R2 repair verification / R2 修复验证

The source was changed only after the original host stopped. The recognition API's pre-dispatch failure branch now emits explicit no-input facts. A shared validator accepts only that complete, consistent producer proof; the local owner receipt and terminal inspector preserve it. The existing v2 runner can then settle failure/cancellation without a paid check or suffix input. Old unknown receipts, conflicting facts and later dispatch failures remain unknown. No target or input gate was relaxed. / 原宿主停止后才修改源码；识别前置失败分支明确输出未派发证明，公共消费者只接受完整且一致的证明。原运行器可据此终结失败或取消，不付费、不执行后续步骤；旧未知回执及冲突仍保持未知，未放宽目标或输入门禁。

- Effective worker RED: **4 failed, 5 passed**; an earlier test-import typo is separately retained. Final worker regression: **252 passed in 14.74 s**. / 有效首败与测试笔误分别保留。
- Main inspected the five-file diff and independently reran the same ten-file group: **252 passed in 14.91 s**, `.superpowers/sdd/2026-10-09-adaptive-live/main-recognition-no-dispatch.xml`.
- This repair has not been live-retested yet. It does not change the failed R2 result or add cross-host/epoch task-plan recovery. / 待全新实机复测，不改第二轮失败、不新增跨宿主恢复。

Budget status now validates the frozen profile and reads the original ledger without creating a service/storage or calling the provider. A missing/invalid ledger under an existing persistence path returns unavailable, not zero. V1 scope and original authenticated admission snapshots remain unchanged. / 预算状态核对冻结配置后只读原账本，已有持久路径的缺失或损坏不能显示零，不改 v1 范围与原认证预算。

- Worker initial RED: **10 failed, 2 passed**; additional missing-ledger edge RED: **3 failed, 1 passed**. Final worker seven-file group: **203 passed in 3.61 s**.
- Main independently reran the seven-file group: **203 passed in 3.60 s**, `main-decision-status-final.xml`.
- Main queried the original stopped R2 session through the updated transport: **used=1, remaining=10**, host cleanup verified, all original session-file hashes unchanged. Read-only proof: `r2-readonly-20261009-054554.json` under the same adaptive-live evidence directory. The owned app was still present. No new API request was made. / Main 只读核对真实旧账本、所有会话文件不变；没有新增 API 请求，应用仍待关闭。

These targeted groups overlap other evidence and are not summed into a unique total. / 定向组与既有测试可能重叠，不累加成独立用例总数。

## Open gates / 待完成

Preserve and finish application cleanup for the second failed session. Its verified stopped host and quiescent original bridge do not prevent fresh acceptance in a separate owned window/data root. The two product repairs still require successful fresh single/continuous cases. Real proactive-review/loading cases, public-browser complex cases, newly learned workflow reuse, matched benefit measurements, independent same-candidate acceptance and consolidated packaging/upgrade/installation checks remain open. / 保留第二轮应用收尾未完成项；旧宿主已停且桥无待命令，可在独立新窗口/新根继续复测。两项产品修复仍待有效实机闭环，其他门槛不变。

## Main R3 harness failure and complete cleanup / R3 测试桥首败与完整收尾

Main reviewed the lifecycle integration and bounded learning allowlist, then independently passed six offline integration cases in0.87s. The real Bridge loop was exercised with fake client/OS boundaries; a separate CLI self-check and combined patch check passed. The active R2 bridge was not modified. Evidence: `.superpowers/sdd/2026-10-09-adaptive-live/bridge-integration/main-combined-freeze.json` and `main-combined-green.xml`. / 接线离线通过仅证明测试桥合同，不等于产品实测成功。

- Fresh R3 used `D:/AgentReviewAcceptance/adaptive-real-7zip-03`, a new maintained launch/host/window and new files. Main inspected the maintained original capture; HWND2427492/PID62620 differs from R2. Its sole address-plan request was rejected by the test bridge before submission. The runtime has no command for that request, no task plan, and **zero paid API calls**. / 独立新会话的首条输入在测试桥前拒绝，未进入产品队列。
- Exact failing layer: helper `_identity_read` accepted only tuple. Main's read-only native query returned `GetWindowThreadProcessId -> list [39596,62620]`, with integer `IsWindow=1`, matching process birth1791527901.8461795 and executable `d:\\7-zip\\7zfm.exe`. The incompatible container check produced `ValueError/unavailable`; it was not an application-target mismatch or a product input failure. / 根因是测试桥对实际Win32返回形状的错误假设，需同时接受严格两元素list/tuple，保留PID/出生时间/路径身份核验。
- Cleanup used the maintained **original-host** `InstantSession.submit(close_launched_window)` after revalidating the original session/host/native identity, all source/harness hashes, no pending command, and absence of the rejected input from the runtime queue. No host was started, input authorization changed, raw close sent or process killed. Original runtime receipt returned `window_closed`. / 通过原宿主正常关闭维护接口收尾，不启动新执行器或绕过产品门禁。
- The existing R3 bridge then observed Gone, normally stopped the host and exited0. `closed.json` plus `main-final-cleanup-proof.json` prove original window/app/host absent, empty pending IDs, cleanup verified and source/harness unchanged until stop. Its bridge labels this separate maintained close as externally observed; the actual close-command provenance is retained in `main-maintained-close-proof.json`. The business attempt remains failed before input. / 完整收尾通过，但不把首败改记业务成功。

The helper compatibility repair is being prepared separately, followed by a fresh R4 retry. R3 has consumed no additional API budget; the overall batch remains2 requests/8631 input tokens, ten initial requests remaining. / 修复后使用全新R4，不重用R3失败请求或旧学习内容。

## R4 refusal and normal cleanup / R4拒绝与正常收尾

The helper patch accepts strict two-element tuple/list and retains PID/birth/executable checks. Its original source is preserved under `bridge-integration/native-binding-fix/`; Main applied it only after R3 was proven closed, then passed57 cases in1.08s across helper/native-binding/bridge/learning integration. This is scoped harness evidence, not57 live cases. / 测试桥兼容修复已应用并离线验证，不混入实机成绩。

Fresh R4 root `D:/AgentReviewAcceptance/adaptive-real-7zip-04` used HWND1378338/PID58300, session `runtime/session-16fd9d26ca2748a9b4bd18b0cdb90649`. Its live helper reported alive_owned. Plan `main-7zip-address-single-04` failed at focus: current address Edit bbox was57,79,2483,17, while selected point1124,41 hit a ToolBar and was rejected with `text_field_target_not_writable`. No type/Enter/Decision followed. Original receipt: `responses/trial-exec-b110e683c1759f7b0f1b06448a698c46.json`. Main verified its hash, the original trace and all three saved PNG hashes. Raw refine output `[196,80]` becomes `(100,41)` in the512px crop, then `(1124,41)` with origin `(1024,0)`. The recorded coarse/refine conversions are consistent: this sample contains a provider target miss, not evidence of a conversion defect. Crop context loss and a changed prompt are observed differences, not proven causes. / 本例原输出定位错误，所示坐标转换一致；保留失败，不用最近Edit纠偏、旧坐标或盲重试掩盖。详见本批 `R4_GROUNDING_DIAGNOSIS.md/.json`。

The task plan became failed with original_input_status=failed and action_executed=false while the nested local receipt uses result_unknown. Source/trace audit confirms this particular focus check threw before click dispatch, but the public receipt lacks complete dispatch_status/input_started proof; aggregate false alone cannot establish that invariant. The inconsistency is being repaired with offline regressions before further live inputs; old receipts remain unchanged. Main used the same bridge's maintained close command. It returned window_closed and the bridge normally stopped/exited0. `closed.json` and `main-final-cleanup-proof.json` prove original window/application/host absent, cleanup verified, empty pending IDs, unchanged source/harness until stop and closure_source=maintained_close. **This refusal's cleanup passed; the navigation/continuous journey did not.** R3/R4 used zero additional API requests. / 本例源码证明点击前拒绝，但公共证明仍须补齐，不能将默认false用于其他未知输入；收尾通过与导航失败分别保留，批次API仍2次。
