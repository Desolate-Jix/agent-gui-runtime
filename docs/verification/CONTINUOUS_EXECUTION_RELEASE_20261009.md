# Continuous execution preview.3 delivery / 连续执行 preview.3 交付

Status: **Main and independent installed acceptance passed; publication and public-download verification pending.** / **本方及独立实装验收通过，网络发布与公开下载核验待完成。** Latest publication receipts will be recorded in the [online release record](https://github.com/Desolate-Jix/agent-gui-runtime/blob/main/docs/verification/CONTINUOUS_EXECUTION_RELEASE_20261009.md). / 后续发布证明维护在该在线记录。

Execution `0.1.2-preview.3` and optional learning `0.1.0-preview.3` use independent installers. This release carries short task plans, original-ticket cancellation/review continuation, native control validation and browser-field fixes. Local models remain optional for users; the release tests use local grounding with Decision off. / 执行与可选学习组件独立安装；本次交付短计划、原票据取消审核续接、原生目标校验和浏览器字段修复。用户不强制使用本地模型，本轮验收采用本地识别并关闭 Decision。

## Existing source evidence / 已有源码证据

See [continuous execution acceptance](CONTINUOUS_EXECUTION_ACCEPTANCE.md) and [external vision evaluation](../development/EXTERNAL_VISION_BENCHMARK.md). Final source tests passed ten matched pairs (20 complete runs, 40 correct effects), cancellation/review continuation, explicit dialog recovery and independent same-source verification. Warm two-step medians were 6502.299 ms with local visual grounding and 2069.760 ms with reliable native targets; the 68.17% reduction excludes startup and Main reasoning. Ordinary Luna evaluation ended after twelve controlled cases. / 源码受控测试及独立验收已通过，原失败分别保留；预热后两步中位数 6.502 对 2.070 秒不含启动与主模型思考，普通 Luna 十二案评估已结束。

The following delivery checks must use actual built/installed payloads; source success alone does not prove installation completeness. / 下述交付核验须使用真实构建和安装载荷，不能以源码通过替代。

## Delivery evidence / 交付证据

The release source check passed 415 focused tests in 74.50 s. After fixing the PowerShell worker closure, five packaging/installation groups passed 39 tests with one real-payload test deselected (33.50 s); actual builds and installation below cover that boundary separately. Counts overlap and are not added. / 发布源码定向检查 415 项通过（74.50 秒）；补齐 PowerShell worker 后，五组打包／安装检查 39 项通过（33.50 秒），未跑的一项真实载荷测试由下述实际构建与实装单独覆盖。检查存在交集，不相加。

Both installers built successfully from the recorded source/resource manifests. Isolated E checks passed functional-entry imports, image dependencies and synthetic offline DPAPI Decision storage; frozen G passed English/Chinese startup, normal close and image-feature checks. Existing clean interpreters were reused; this is not a fresh-machine dependency installation. / 两安装器构建成功；包外入口、图像依赖与离线认证存储通过，冻结学习包中英文启动、正常关闭及图像检查通过。复用既有干净解释器，不声称全新系统依赖安装。

The initial pair used a new temporary root. Real local-route acceptance exposed a missing dynamically launched worker, so only E was rebuilt and installed into another fresh root; G bytes did not change. Final checks verified all **546 execution and 349 learning** declared payload files, with no shortcuts or per-user integration written. / 首次实装发现动态启动 worker 漏包，仅重建 E 并另用全新临时根安装，G 字节未变；最终逐项核验执行 546 与学习 349 个声明载荷文件，不写用户集成或快捷方式。

| Installer / 安装器 | Bytes | SHA256 |
|---|---:|---|
| AgentGUIRuntimeExecutionPreview-Setup.exe | 2939392 | `fe18ec4436a9ef1a75407e7905d5b68a8d37b53c92233256250fca83a8bfa760` |
| AgentLearningWorkbenchPreview-Setup.exe | 124354560 | `6769c80039bc6974f236275e1cf6171dab14e5d4a55cfabf09daf915affd6805` |
| SHA256SUMS.txt | 216 | `a6592699211e2f99b229d6d700f742669fca93368b9441e4c82bd82697e85818` |

Main's final installed E runs covered a native two-step smoke, an actual local-model/native-target B/C pair, cancellation after A, original-ticket review/explicit continuation and explicit dialog recovery. **13 original business input receipts** passed **303 read-only evidence checks**, including image hashes, original commands, target identity, effects, no replay and cleanup. B/C timings from this one installed pair are only smoke evidence; use the ten-pair source result for the reported performance comparison. / 最终 E 实装覆盖原生两步、本地模型与原生目标对照、A 后取消、原票据审核续接及明确弹窗恢复；13 个原业务输入回执通过 303 项只读证据审计。单对实装耗时仅为冒烟证据，公开性能数值仍引用十对源码测量。

Main's installed G opened in English, edited and saved a fresh synthetic standalone interface, closed normally, reopened the same library and displayed revision 2 with the edited value. The original pinned revision was unchanged. Four UI commands, two normal closes and observation-host cleanup were verified; this is editor persistence acceptance, not a new learning/execution benefit experiment. / G 默认英文打开，全新合成独立界面经真实 UI 修改保存，正常关闭重开显示修订 2，原版本不变；4 个 UI 命令、两次正常关闭及观察宿主清理通过。这是编辑器持久化验收，不冒充新的学习收益实验。

Native E acceptance MCP and host processes used installed script paths and cwd, with recorded PID/birth/parent/venv ownership. E MCP used `-I -B`; the public host does not inherit `-I`. Independent G used its installed EXE but the frozen older GUI-observation bridge did **not** pass MCP `-I`; its installed paths, payload hashes and process cleanup were checked separately, without claiming identical isolation flags. Existing FULL dependencies and read-only model weights were reused. The 648 `app` hashes in the native controller audit describe controller W, not installed E; installed closure is proven by the declared payload manifest. / 原生 E 验收使用安装入口及隔离 MCP 参数；独立 G 的旧观察 bridge 没有 `-I`，入口、清单与清理单独核对，不冒称同样隔离。648 个控制工作树源码哈希不代替安装载荷清单。

## Independent installed evidence / 独立实装证据

Independent Sol verified the same final E installer in fresh B/C, cancellation/review continuation and notice-recovery cases: **11 original inputs**, **255 read-only checks**, `errors=[]`, no input replay and normal host/fixture cleanup. The first raw audit is `INDEPENDENT_INSTALLED_RAW_AUDIT.first.json`; these installed results are separate from the earlier source-only independent acceptance. / 独立 E 三组实装共 11 个原输入、255 项核对，无错误、不重放并正常清理，源码旧结果不转计。

Independent G `gui02` completed **four original GUI commands** on a fresh synthetic standalone draft: edit/save, normal close and reopen showed **revision 2**, with original **revision 1 unchanged**. Both GUI processes closed normally and the observation host cleaned up. Main's separate `MAIN_REVIEW_INDEPENDENT_GUI.first.json` verified **46 evidence-file hashes**, four command/read-back receipts, persisted save/reopen and cleanup; Main visually inspected the final reopen PNG. Field read-back is not relabelled as generic task-effect proof. / 独立 G 四命令、新草稿保存重开修订 2、原修订 1 不变、两次正常关闭及宿主清理通过；Main 另核对 46 个证据文件哈希并查看最终后图。

The final combined payload/GUI audit `INDEPENDENT_FINAL_PAYLOAD_GUI_AUDIT.third.json` passed **1293 checks**, `errors=[]`; installed E **546** and G **349** declared file hashes had no mismatch, and all recorded owned processes exited. Its first/second audit versions only misread counter fields (`checks` is a dictionary in the embedded audit; `original_inputs` is a list). The third corrects those audit interpretations; no product change or input replay occurred. The 255/1293/46 audit counts overlap and are not distinct product cases or added totals. / 最终审计 1293 项无错误，安装文件与进程清理通过；前两版只是计数字段误读，第三版修正审计，不修改产品或重放输入，核对数分别报告。

## Preserved failures and fixes / 保留的首次失败与修复

1. `smoke-01`: zero business inputs; the new adapter incorrectly required the actual child `argv[0]` to equal the venv redirector. A no-GUI probe confirmed Windows uses the configured base executable for that child. The adapter now validates the exact redirector/base chain, retaining the same executable allowlist; offline regression passed. / 测试脚本的 Windows 虚拟环境进程路径误判，已按无 GUI 复现修正，未扩大可执行文件集合。
2. `smoke-02`: zero business inputs; `start_transformers_vision_server.ps1` could not find `app/vision/model_workers/vista_openai_server.py`. **Invariant:** every maintained dynamically launched entry must be shipped with its dependencies. **Fix:** `scripts/build_execution_component.py` explicitly includes the worker; Python AST collection cannot discover a PowerShell string launch. The new regression failed before the fix, passed afterward, and rebuilt E passed actual local model inference. This common packaging repair applies to all local-route applications. No input gate was loosened. / 本地 worker 漏包打破动态入口依赖闭合合同；在公共打包器显式收录，新增回归先红后绿，重建后实际本地推理通过。修复通用于本地识别路线，不放宽输入门禁。
3. Installed `bc-01`: both runs/four inputs and cleanup passed, but the adapter originally counted a new `logs/model_server_leases/.lease-state.lock` as payload drift. All pre-existing files and 546 declared payload hashes were unchanged. Source and raw bytes confirm this one generated lock contains ASCII `0`; the adapter permits only that exact new path/content, still rejects other additions, changes or removals. A nine-check read-only supplement passed, with the original false report preserved and **no input replay**. Adapter regressions passed 27 tests. / 两任务已正确完成，后置测试把已知单字节运行锁误计为程序变更。补充审计仅认可该确切路径与内容，原文件哈希不变、9 项审计通过；保留原 false 报告，不重放输入。
4. Independent G `gui01` supplied incomplete current-vision capabilities (`controller_CAPS_missing_current_vision`), so the product refused with `capability_unknown`, **zero attempted/executed inputs**, and normal GUI/bridge cleanup. The original failed receipt is retained; corrected capability metadata was used in fresh `gui02`, which passed. This caller correction is not a product repair or replay of an executed input. / 独立 GUI 首案错误 CAPS 被安全拒绝且零输入，关闭清理通过；保留首败，修正调用能力后以新案通过，不改产品或重放。

Initial failed E SHA `da13f3478e38cd0e8811cbc9c3377c1fc5e32ef902bddd8401ef11eb04c2a225` is retained only as failure evidence and is not the published asset. Its supported test uninstall completed. / 首候选 E 仅保留失败证据，绝不作为发布资产；测试载荷已受支持卸载。

Evidence is retained under this batch's dedicated Main/independent installed roots and private `2026-10-09-continuous-release` records, including both audit corrections and the original `gui01` refusal. Public summaries exclude raw desktop images, user configuration and credentials. / 本方、独立原回执、PNG、清理和清单本地保留，审计前两版与 GUI 首拒绝不覆盖；公开摘要不包含原始桌面图、用户配置或凭据。

Final supported test-uninstall completed for both owned installations: exit 0, `worker_cleanup_complete=true`, user defaults unchanged. G has `remaining_paths=[]`; E retains only its ownership receipt, `Uninstall.exe`, runtime logs, the one-byte lease lock and empty directories. Initial failed E uninstall is also recorded. Additional residual deletion was blocked by automatic approval policy and was not bypassed; this is not a claim that every temporary test file was removed. Network publication, public-download verification and shutdown remain unfinished. / 两个最终测试安装均受支持卸载完成，用户默认未变；G 无残留，E 保留明确的归属/卸载器/日志/单字节锁及空目录。额外残留删除被审批策略阻止且未绕过，不宣称测试文件全删；网络发布、下载核验与关机仍待。

## Scope / 范围

No generic autonomous planner, automatic cross-window/dead-host replay, dynamic output integration, broad accuracy guarantee or real Main-model cost comparison is claimed. Browser scan reduction remains future work. / 不宣称自主规划、跨窗或宿主退出后自动重放、动态输出集成、通用准确率或主模型成本收益；浏览器重复扫描优化留待后续。

Some historical origin-status badges remain Chinese in the otherwise English default UI. Installer READMEs retain their build-time preparation snapshots; final acceptance and publication evidence are maintained online. / 默认英文界面仍有少量历史来源状态标签为中文。安装包 README 保留构建时准备快照，最终验收与发布状态以在线记录为准。
