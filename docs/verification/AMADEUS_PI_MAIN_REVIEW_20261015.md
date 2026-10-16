# Amadeus Pi Main review acceptance / Amadeus Pi 主 Agent 续行验收

2026-10-16. Execution 0.1.5 / extension 0.0.2 evidence. Final independent installed acceptance passed within the three-step scope below. Publication status and artifact checksums remain in the [release notes](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.5). Earlier runs retain their original candidate identities. / 执行版 0.1.5／扩展 0.0.2 证据。最终独立安装态验收已在下方三步范围内通过；发布状态及交付校验值仍由[发布说明](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.5)承接，较早运行保留原候选身份。

**Published:** Runtime **0.1.5 is stable/latest**, with release tag/frozen code at `6fa3c487da5710f1e86d7a93f484226c94b96c70`; main was fast-forwarded at publication. Main verified all **4 release assets** against server SHA256 (wheel `32d27ed…`, Setup `c11aa7f…`). This review follow-up changes Amadeus source and these documents only: Runtime **0.1.5** and wheel **0.0.2** retain their versions and exact bytes, with no repackaging. [Public release](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.5). / **已发布：** Runtime **0.1.5 已为 stable／latest**，发布 tag／冻结源码为上述提交，main 已在发布时快进；Main 已核对 **4 个发布附件**的服务端 SHA256（wheel `32d27ed…`、Setup `c11aa7f…`）。本次审查后续只改 Amadeus 源码及这些文档，Runtime **0.1.5** 与 wheel **0.0.2** 的版本和字节均不变，没有重新打包。

## Final independent installed acceptance / 最终独立安装态验收

The final installed Runtime check used frozen release source `6fa3c487da5710f1e86d7a93f484226c94b96c70`. Its original `independent-final-runtime-015/result.json` records `status=success`: Notepad edit → File → Save completed **3/3 steps in 27.70161 s** on the **first attempt**, with one plan submission, no automatic retry/self-correction and **no Main override**. **10 HTTP requests = 7 Decision + 0 ordinary review + 3 grounding**. The exact 55-byte disk result and bound original image passed; the owned window closed, then `host_alive=false`, `pending_ids=[]` and `cleanup_verified=true`.

最终安装态 Runtime 检查使用冻结发布源码 `6fa3c487da5710f1e86d7a93f484226c94b96c70`。原始 `independent-final-runtime-015/result.json` 记录 `status=success`：记事本编辑 → File → Save **首次完成 3/3 步，27.70161 秒**；计划只提交一次，无自动重试／自纠错，**无 Main override**。**10 次 HTTP＝7 Decision＋0 普通复核＋3 grounding**。55 字节磁盘结果精确匹配，绑定原图核验通过；自有窗口关闭，随后 `host_alive=false`、`pending_ids=[]`、`cleanup_verified=true`。

Total tokens are **unknown**, not zero: `accounting.json` has a known subtotal of **16,186 tokens**, plus **one opaque usage record** (`tokens_complete=false`). The **27.70161 s** is plan wall time, not a single API latency or a performance benchmark. This is scoped standalone installed Runtime acceptance, not a second Amadeus Chat/Pi delegation or a new paired-refusal Main-recovery run. Existing-Python checks do not establish clean-machine setup.

总 tokens **未知，不能记为零**：`accounting.json` 的已知小计为 **16,186 tokens**，另有**一项不可读用量**（`tokens_complete=false`）。**27.70161 秒**为计划总耗时，不是单个 API 延迟，也不是性能 benchmark。这是限定范围的独立安装态 Runtime 验收，不是第二轮 Amadeus Chat／Pi 委派或新的双拒绝 Main 恢复实测；复用已有 Python 的检查不证明全新机器 setup。

## Final source and wallpaper follow-up / 最终源码与壁纸补充

The final affected-source regression passed **135 checks** (pytest wall time 117.94 s; JUnit suite time 117.924 s). The earlier 115-check and independent 74-check groups overlap and are not added. All 575 Python files matched the previously installed 0.1.5 candidate before documentation finalization; this is source continuity, not another desktop run.

最终相关源码回归 **135 项通过**（pytest 117.94 秒，JUnit suite 117.924 秒）。此前115项和独立74项有重叠，不相加。文档收拢前，575个Python文件与此前已实测安装候选逐字节一致；这不算另一轮桌面验收。

Lively 2.2.1.0's null display-name mapping was verified by a real intervention: the unchanged copy returned empty wallpaper lists in 7/7 reads; after changing only that mapping, six consecutive post-initialization reads returned the correct scene. Amadeus then completed two mount/stop/restore cycles with the corrected copy. A separate real negative test retained the original mount timeout, `MountUnconfirmed` journal and running host; correcting the copied service then allowed explicit recovery. These are historical runs of the earlier [PR #228](https://github.com/Code-Amadeus/Amadeus/pull/228) candidate, not a repair to Lively's protocol or acceptance of the current review candidate.

Lively 2.2.1.0 的空显示器名称映射已用真实干预验证：原副本7次均返回空壁纸列表；只修正该映射后，初始化后的连续6次返回正确场景。Amadeus随后在修正副本上完成两轮挂载、停止和恢复；单独真实负例保留原挂载超时、`MountUnconfirmed` 日志及宿主，修正副本后显式恢复成功。这些归属 [PR #228](https://github.com/Code-Amadeus/Amadeus/pull/228) 较早候选的历史运行，不是 Lively 协议修复，也不计为当前审查候选验收。

The earlier PR #228 revision `0821a9c16d00d43661886790a887ffe830ca19f6` was ready for review, open and unmerged, with **five CI workflows passed**, including the Windows failed-jobs rerun (attempt 2). These are historical revision results. The first unchanged Python test's **5-second** timeout remains recorded; its exact slow callback/load cause is unknown, and no unrelated Python code was changed. / PR #228 较早 revision `0821a9c16d00d43661886790a887ffe830ca19f6` 曾为 ready for review、open、未合并，**五项 CI 通过**，含 Windows 失败任务第二次运行；这些仅为该旧 revision 的历史结果。首次既有 Python 测试的 **5 秒**超时保留，具体慢回调／负载原因仍未知，未改无关 Python 代码。

At the current review checkpoint, **PR #228 remains DRAFT** at pushed head `6dfb187cad6535631048f11e3703b7d57b6147b3`. Its scope is narrowed to `Preparing` / `Pending` / `Settled` phase rollback, preservation of primary and cleanup errors, and cleanup ownership tied to process identity; **35 offline contracts passed**. Stock Lively's falsely empty report plus a successful no-op Close remains an unresolved counterexample and is **not included in the passing count**. CI for this new head is running and its final result is unconfirmed; the earlier green/ready checkpoint is not current approval or an upstream release.

当前审查 checkpoint 中，**PR #228 保持 DRAFT**，已推送 head `6dfb187cad6535631048f11e3703b7d57b6147b3`；范围收窄为 `Preparing`／`Pending`／`Settled` 阶段回滚、主异常与清理异常保留，以及按进程身份归属清理责任，**35 项离线契约通过**。原版 Lively 的假空报告加 Close 成功但 no-op 仍是未解决反例，**不计入通过数**。该新 head 的 CI 正在运行，最终结果尚未确认；此前全绿／ready 不代表当前批准或上游已发布。

Root's real Close probe, case03, used normal nonempty reporting from the original Lively 2.2.1.0 DLL in an isolated copy: exact-project Close was followed by the owned player's exit. Closing a nonexistent project also returned success, so that acknowledgement alone does not prove closure. This run did not naturally reproduce false-empty reporting and does not close the faulty-protocol case.

Root 的真实 Close 探针 case03 使用隔离副本中的原版 Lively 2.2.1.0 DLL，场景报告正常且非空；确切项目 Close 后，自有 player 退出。关闭不存在的项目也返回成功，因此回执本身不能证明已关闭。本轮未自然复现假空报告，不计为故障协议闭合。

After the earlier lifecycle tests, the local installed Lively DLL was backed up and patched. Of 613 program files, only `Lively.dll` changed: `ca73583755c8fc381cdda674bfbc3c60fea0bf924dcb06f846083c0b30f354ad` → `2206123045ccbad5b1d21039becba8ed7d673d6c2f20c703d5e02c57dfddd414`. The normal installed path then passed **2 cold-start/stop cycles** in `installed-lively-repair-01/product-coldstart-02/result.json`: both owned Lively processes stopped, both native windows closed, no journal remained and the product-owned processes settled. This is a reversible local third-party DLL repair with its original backed up, not an official update or anything bundled in Runtime/the wheel. Other users' installations are not repaired. Renderer screenshots establish composer controls only, not the physical desktop or character background. Two earlier observer errors remain recorded, not complete passes.

在较早生命周期测试之后，本机已备份原 DLL 并应用修正；613 个程序文件中仅 `Lively.dll` 从上述原哈希变为修正哈希。随后正常安装路径在 `installed-lively-repair-01/product-coldstart-02/result.json` 中通过 **2 次冷启动／停止**：两轮自有 Lively 进程停止、原生窗口关闭、journal 均不存在，产品自有进程也已结算。这是保留原件备份、可回退的第三方本机 DLL 修复，非官方升级，亦不随 Runtime／wheel 分发；其他用户的安装不会自动修复。renderer 截图仅证明 composer 控件，不证明物理桌面或角色背景；此前两次观察器错误保留，不计完整通过。

## Earlier installed Amadeus/Pi normal tasks / 较早的安装态 Amadeus／Pi 正常任务

Two normal synthetic Notepad tasks completed through the installed Execution **0.1.5 candidate + extension 0.0.2**, in run10 and the same Chat session. Each used a fresh fixture, Pi Work, Runtime session and owned window; this is not two tasks in one Pi process or Runtime session. All six steps, exact disk checks, owned-window closes and final Runtime status checks passed, with no Main semantic review/override. Normal Host permission approvals remain separate.

已安装的执行版 **0.1.5 候选＋扩展 0.0.2**，在同一 run10 产品及 Chat 会话完成两项正常合成记事本任务。每项分别使用新 fixture、Pi Work、Runtime session 和自有窗口，不是同一 Pi 进程或 Runtime session 连跑。六步均成功，精确磁盘核对、各自窗口关闭及 Runtime 最终状态均通过，没有 Main 语义审核／override；正式 Host 权限批准仍另行保留。

| Normal task / 正常任务 | turn11 | turn12 |
| --- | --- | --- |
| Plan / 计划 | 3/3 success, completed | 3/3 success, completed |
| Runtime model HTTP / Runtime 模型 HTTP | 7 Decision + 1 ordinary Luna + 3 grounding = 11 | 7 Decision + 0 ordinary + 3 grounding = 10 |
| Main semantic review / Main 语义审核 | 0 | 0 |
| Disk, owned close, final Runtime status / 磁盘、自有窗口、Runtime 终态 | exact match; window_closed; host_alive=false, pending_ids=[], cleanup_verified=true / 精确匹配、窗口关闭、宿主清理通过 | same checks passed / 同项检查通过 |

The two tasks total **21 Runtime model HTTP requests**, excluding Chat/Pi models and TTS. Turn11's primary rejection was accepted by ordinary Luna; final history marked decision does not mean every primary check passed. Turn12 self-corrected a policy-denied bash attempt and an SDK-local missing-request_id error before Runtime input dispatch; it is not an error-free first attempt. The original turn10 was rejected by the harness's 4,000-character preflight (4,834 characters); corrected turn11/12 requests were 3,141/3,260 characters. Preserve the original rejection.

两任务合计 **21 次 Runtime 模型 HTTP**，不含 Chat／Pi 模型和 TTS。turn11 首层拒绝后由普通 Luna 复核通过，最终 history 为 decision 不等于全首层通过。turn12 的 bash 策略拒绝及 SDK 本地缺 request_id 错误均在 Runtime 输入派发前由模型自行纠正，不能称零错误首过。原 turn10 因仪表的 4,000 字符前置限制拒绝（实际 4,834）；修正后 turn11／12 为 3,141／3,260 字符，原拒绝保留。

The extension lifecycle also passed through its formal owner: disable → a controlled reopening retaining this extension store → missing contributions; then remove({deleteData:false}) → restart → missing contributions and installation removal. Main verified all **149 original data files / 4,699,337 bytes**, with every SHA unchanged. The observer used the validated Host Python 3.12 at E:/amadeus/.venv; its frozen SHA is 0873605d93a58b9cdaa4c188c7a3dc69e90028dc56b64df1473e83a0a6ddd86b. Both the old product and observer are settled; the old product exited with code 1, so this proves owned-process settlement, not graceful Electron exit.

扩展生命周期也经正式 owner 通过：disable → 保留本轮 extension store 的受控重开 → 贡献缺失；再 remove({deleteData:false}) → restart → 贡献缺失且安装目录清理。Main 核对原 **149 文件／4,699,337 bytes** 的 SHA 全部不变。observer 使用已验证的 E:/amadeus/.venv 下 Host Python 3.12，冻结 SHA 如上。旧产品与 observer 均已 settled；旧产品退出码为1，只记 owned-process settled，不称 Electron 优雅退出。

## Earlier TEST recovery sample / 旧 TEST 恢复样本

The earlier live04 sample used extension 0.0.1 and an unreleased Runtime candidate. It exercised the original-input review path on a real Notepad window: after two intentional test-service rejections, the original Pi Agent received the bound PNG, approved the typed text and explicitly continued the same command. File-menu and Save completed, the file matched, and the owned window and Runtime were closed. This is separate from the installed 0.1.5/0.0.2 normal tasks above.

旧 live04 使用扩展 0.0.1 与此前未发布 Runtime 候选，在真实记事本窗口验证原输入审核。测试服务有意双拒绝后，原 Pi 收到绑定 PNG，审核已输入文字并明确继续原命令；菜单、保存、磁盘及窗口／Runtime 收尾完成。此旧注入样本与上方已安装 0.1.5／0.0.2 正常任务分开，不能转记为 0.1.5 已重测双拒绝。

This is **controlled fault injection with real GUI execution**, not evidence that the paid models naturally misclassified this image, nor an accuracy or latency benchmark. The injection affected exactly one matching Decision value check and its ordinary review. Original nonpass records remain unchanged.

这是**受控故障注入下的真实 GUI 恢复测试**，不代表付费模型在这张图上自然误判，也不作为准确率或延迟评测。注入仅影响一组匹配的 Decision 输入值核验及普通复核，原非通过记录完整保留。

## Earlier TEST facts / 旧 TEST 已核事实

| Contract / 合同 | Evidence / 证据 |
| --- | --- |
| Original execution / 原执行 | One original input job and one `focus_type` dispatch; selection and typing each started/completed once. / 原输入 Job 和 `focus_type` 派发均只有一次，全选与文字输入各开始、完成一次。 |
| Actual image / 实际图片 | Pi's native tool result contains the original 11,099-byte PNG; SHA256 `4903e3a17e1704ae5876f8aaa87b568ae070f05404053c983ea6eec8e8cbafcf` matches the packet and file. / Pi 原生工具回执中的 PNG 与审核包及原文件哈希一致。 |
| Explicit recovery / 明确续行 | `plan-review-note-001` then `plan-continue-note-001`, on the original run, step, execution and wait ID. / 先审核、再继续，均绑定原运行、步骤、执行和等待 ID。 |
| Model provenance / 判断来源 | Both original choices remain `condition_not_met`; input-value approval is separately recorded as `main_agent`. / 原双模型结论仍为非通过，输入值批准单独记为主 Agent 来源。 |
| Remaining plan / 余下计划 | `first_edit`, `first_menu`, `first_save` all succeeded in the same run. / 同一运行的输入、菜单、保存三步均成功。 |
| Saved data / 保存结果 | UTF-8, 43 bytes, no BOM or trailing newline: `Pi Main review - approved without retyping.` / UTF-8 共 43 字节，无 BOM、无结尾换行。 |
| Cleanup / 收尾 | `window_closed`, then `phase=stopped`, `host_alive=false`, `pending_ids=[]`, `cleanup_verified=true`. / 自有窗口关闭后，宿主停止、待处理列表为空、清理验证通过。 |

The final whole-step verifications are marked `judged_by=decision`; the earlier input-value override remains independently recorded as Main review. These fields describe different checks and must not be summarized as “no Main intervention.”

整步最终核验的 `judged_by=decision` 与此前输入值的 Main 审核是不同记录，不能因此声称本轮没有 Main 介入。

## Pi image fix / Pi 图片适配修复

Pi's pinned catalog did not recognize the configured legacy `deepseek-v4-flash` ID. Its custom-ID fallback inherited text-only metadata and omitted MCP images before making the request. A real API probe using that same legacy name read a random synthetic image correctly; the returned model was `deepseek-flash`.

Pi 固定依赖的模型目录未识别已配置的旧名称 `deepseek-v4-flash`，其自定义 ID 路径继承纯文本元数据，在请求前丢弃 MCP 图片。同名真实 API 探测能够正确读取随机合成图，服务实际返回 `deepseek-flash`。

The Amadeus-owned fix uses the public session_start / before_agent_start hooks and pi.setModel for the current unregistered legacy Flash selection. It preserves wire IDs, native cache/refresh, authentication, endpoints and explicit user/provider declarations; Pro and unknown IDs do not gain image capability. The earlier Provider-registration overlay was abandoned. Third-party node_modules were not edited. Current [PR #225](https://github.com/Code-Amadeus/Amadeus/pull/225) head `5b3a434ab8617e4eb2d7472f49fa8171ac445004` passed **24 native SDK + 21 Provider checks = 45 passed**, plus TypeScript typecheck. The optional compatibility boundary now retains Pi's native selection and gives one sanitized warning when it cannot safely repair metadata, instead of turning that optional repair into a fatal extension error. Root verified all **5 remote workflows and 15 check runs successful on this new head**; this does not assert that the PR is merged.

Amadeus 自有修复使用公开 session_start／before_agent_start 与 pi.setModel，仅修补当前未注册的精确 Flash 旧名称选择；保留 wire ID、原生缓存／refresh、认证、接口及用户／Provider 显式声明，Pro 与未知 ID 不增加图像能力。旧 Provider 注册覆盖方案已弃用，第三方 node_modules 未改。当前 [PR #225](https://github.com/Code-Amadeus/Amadeus/pull/225) head `5b3a434ab8617e4eb2d7472f49fa8171ac445004` 经 **24 项原生 SDK＋21 项 Provider＝45 项通过**，TypeScript typecheck 也通过。可选兼容无法安全修补元数据时保留 Pi 原生选择，只给一次脱敏提示，不再把该可选修补升级成致命扩展错误。Root 已核验该新 head 的远端 **5 个 workflows、15 个 check runs 全部 success**；这不代表 PR 已合并。

The earlier **17 native SDK checks**, including image conversion and zero fetch attempts, and the five-workflow green/ready notes for PRs #225/#226 belong to older revisions. The separate [cancellation-cleanup PR #226](https://github.com/Code-Amadeus/Amadeus/pull/226), with its retained **28 related checks**, was **merged upstream on 2026-10-16** as `5dd0b2f2355f0177b89b903b8bc34cd6939fa77e`. The approval-policy proposal remains issue #224. Official compatibility: [model aliases](https://api-docs.deepseek.com/guides/codex), [vision input](https://api-docs.deepseek.com/guides/vision/).

此前 **17 项原生 SDK 检查**（含图片转换、零 fetch 尝试）以及 PR #225／#226 的五项 CI 全绿／ready 记录均归属旧 revision。独立的[取消收尾 PR #226](https://github.com/Code-Amadeus/Amadeus/pull/226) 保留 **28 项相关检查**，已于 **2026-10-16 合入上游**，merge commit 为 `5dd0b2f2355f0177b89b903b8bc34cd6939fa77e`；审批策略提案仍为 issue #224。官方兼容说明见上述模型别名与图像输入链接。

## Scope and limits / 范围与限制

- Frozen Runtime release code: `6fa3c487da5710f1e86d7a93f484226c94b96c70`. Earlier `codex/dev-main-review-resume` checkpoints based on `e6ed046185dcdc935538d4281a07862e4b739b1c` and published 0.1.4 results remain historical. / Runtime 冻结发布源码为前述提交；该开发分支的较早基线检查点及 0.1.4 结果均保留历史归属。
- Amadeus experiment: `codex/dev-amadeus-pi-runtime-extension`, based on `a9a488aecece97b7bcf26429c314c96187321e50`, plus the owned Pi metadata fix. / Amadeus 实验分支在该上游提交上加入自有 Pi 元数据修复。
- Extension identities: earlier live04 TEST used wheel 0.0.1, SHA256 b5f55c4b8768ab4e45acef12c51506d0fb4d6b67351bc676d6e1df996d5167d9; the installed normal/lifecycle candidate uses 0.0.2, SHA256 32d27ed81eab33db05ae2780b98a808205da5057ee98bd71bdad8382e35a6588. Both start the existing Runtime and supply a Skill, without a second executor. / 旧 TEST 与新安装候选身份分开；两者均复用现有 Runtime，不增加执行器。
- Amadeus retains outer `execution=succeeded`, `completion=partial`, `state=review_ready`: its Host does not accept provider self-attestation as explicit business completion. This is separate from the verified Runtime task and cleanup. / Amadeus Host 不把 provider 自述直接视为业务验收，外层保留上述状态；与已核验的 Runtime 任务完成及清理分开记录。
- Normal run10 narration respected the Japanese character-language lock. Two tasks have 38 software playback sentence-end records; generation/cache and playback evidence are recorded, including one cached first sentence. No acoustic recording, listening or ASR acceptance was performed. / 正常 run10 遵守日语角色锁；两任务共38句有软件播放结束记录，保留生成／缓存证据（含一句首句缓存），未作声学录音、听感或 ASR 验收。
- Earlier interfered desktop samples were excluded from functional, speed, stability and accuracy conclusions at the user's instruction. Their raw records and installation/connectivity evidence remain. / 按用户要求排除此前受干扰的桌面业务样本，保留原记录及安装、连通证据。
- run08 mount timeout and run09 45-second readiness failure remain valid unattended failures. Installed Lively IL/setter evidence establishes a null DisplayName defect; the original live exception was not captured. Later copy tests, explicit recovery and the backed-up local installed-DLL repair/two cold cycles above are separate follow-ups, not a repair shipped to other users. / run08 挂载超时及 run09 的 45 秒就绪失败继续保留；安装 IL／setter 证实空 DisplayName 缺陷，原动态异常未捕获。上方副本测试、显式恢复、本机备份后 DLL 修复及两次冷启动均为后续独立证据，不是已向其他用户分发修复。
- The final independent installed check passed only within its three-step scope above. Forced-exit recovery, broader stability, acoustic/ASR and full character/wallpaper composition are not covered. Runtime cleanup is established by each task's original final status, not the lifecycle observer. Publication is handled separately in the release notes. / 最终独立安装态检查仅在上方三步范围内通过，不覆盖强退恢复、更广稳定性、声学／ASR 或完整角色／壁纸合成。Runtime 清理依据各任务原最终 status，不由生命周期 observer 另行证明；发布另由发布说明承接。

## Local evidence / 本机证据

`D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/`:

- [Earlier live04 TEST acceptance / 旧 live04 TEST 验收](D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/pi-field-review-live04-final.json): eight controlled recovery checks passed, separately scoped to the old candidate/0.0.1. / 旧候选与0.0.1的8项受控恢复检查，独立保留。
- [Installed turn11 audit / 安装态 turn11 核验](D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/pi-product10-normal-acceptance-audit.md) and [turn11–12 continuous audit / 两任务连续核验](D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/pi-product10-continuous-audit.md) ([JSON](D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/pi-product10-continuous-audit.json)): two tasks, six steps, 21 Runtime HTTP; second-Work outer errors retained. / 两任务六步及外层纠错边界。
- [Formal lifecycle result / 正式生命周期结果](D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/extension-lifecycle-product-10/result.json); [data before / 数据前清单](D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/lifecycle-data-before-main-01.json) and [data after / 数据后清单](D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/lifecycle-data-after-main-01.json): all 149 original files and SHA unchanged. / 原149文件及SHA全部不变。
- [Final observer review / 最终 observer 核对](D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/lifecycle-observer-main-review-02.json); [Wallpaper native build/setter audit / 壁纸构件与 setter 审计](D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/wallpaper-native-build-audit-01.md): retained earlier diagnostic checkpoints; subsequent local repair and cold cycles are separate above. / 保留较早诊断检查点，后续本机修复与冷启动在上方分列。
- `pi-extension-product-03-core-audit.md` and `.json`: independent read-only verification of original IDs, images, provenance and no replay. / 独立只读核对原 ID、图片、来源与无重放。
- [Historical Pi metadata SDK checks / 历史 Pi 元数据 SDK 检查](D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/pr-preparation/main-final-metadata-17.xml): 17 passed on the earlier revision, before the current 24-SDK/21-Provider review group; the older eight-check Provider-registration result is also historical. / 旧 revision 的17项通过早于当前24项SDK／21项Provider审查组；更早8项注册方案结果亦仅属历史。
- `main-field-fault-live02.jsonl`: one primary and one ordinary injected rejection, separately marked from real forwarded API calls. / 一次主判断和一次普通复核注入拒绝，与真实转发请求分开标记。
- `interference-sample-policy-20261015.json`: prior desktop sample exclusions. / 旧桌面样本排除口径。

- [Final independent result / 最终独立结果](D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/independent-final-runtime-015/result.json) and [accounting / 用量](D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/independent-final-runtime-015/accounting.json): first-attempt 3-step success, 27.70161 s, 10 HTTP; total tokens unknown due to one opaque usage. / 首次三步成功，完整收尾；一项不可读用量使总 tokens 未知。
- [Installed DLL repair / 本机 DLL 修复](D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/installed-lively-repair-01/repair.json) and [two cold cycles / 两次冷启动](D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/installed-lively-repair-01/product-coldstart-02/result.json): backed-up local third-party repair only, not bundled. / 仅可回退的第三方本机修复，不随包分发。
- [PR 228 historical CI audit / PR 228 历史 CI 审计](D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/pr-preparation/wallpaper-ci-failure-audit-01.json) and [historical CI/ready result / 历史 CI 与 ready 状态](D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/pr-preparation/wallpaper-pr-finalization-result-02.json): the earlier revision retained its original Python timeout, then passed one failed-jobs rerun and all five workflows while ready/open/unmerged. These records do not describe the current DRAFT head or its running CI. / 旧 revision 保留首次 Python 超时，随后一次失败任务重跑及五项 CI 通过，当时 ready／open／未合并；这些不描述当前 DRAFT head 或其运行中的新 CI。
