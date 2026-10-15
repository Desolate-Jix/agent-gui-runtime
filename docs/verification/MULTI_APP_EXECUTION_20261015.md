# Execution 0.1.4 multi-application acceptance / 执行版 0.1.4 多应用验收

## English

**Status: scoped 0.1.4 installed acceptance completed.** Main's installed cases and independent Sol tasks passed. Final test-installation removal passed after the explicit empty-directory cleanup described below. Publication metadata and checksums are on the [release page](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.4). Installed results below were measured separately from source runs. Notepad source01 continuity predates the public-client repair; repaired source02 passed fresh 12+4-step 7-Zip use and cleanup. Two earlier 7-Zip failures remain failures.

The scope uses the maintained screenshot → visual grounding → Decision → gated-action route in fresh non-browser Windows tasks. Notepad edits and saves a note. 7-Zip navigates directories and a prepared ZIP; **compression and extraction were not tested**. Only this run's files and owned windows are used. Testing these apps does not establish support for every Windows application. Browser data is retained, native Codex Computer Use is prohibited, and desktop input has one owner.

### Observed installed runs

The installed Main and independent runs used the same installation root and fresh task data.

| Installed case | Actual result | Plan elapsed time |
| --- | --- | ---: |
| Main Notepad alpha: edit → File → Save | Automatically completed, 3/3; saved UTF-8 text matched exactly | **30.6212448 s** |
| Main Notepad beta, same-window second round | Automatically completed, 3/3; saved UTF-8 text matched exactly | **22.8734135 s** |
| Main 7-Zip: A → nested → Up → root → B → bundle.zip | Automatically completed, 6/6; archive package folder visible | **69.5148003 s** |
| Independent Sol, fresh Notepad edit/save task | First attempt automatically completed, 3/3; exact disk content and original images checked | **25.4670209 s** |
| Independent Sol, fresh 7-Zip A → nested → Up | First attempt automatically completed, 3/3; original images checked | **29.260771 s** |
| Final test-installation removal | Passed after explicit empty-directory cleanup and a second uninstall | Not a plan timing |

Main's **12** and Sol's **6** history rows all succeeded with **0** agent judgments / Main reviews. One ordinary review in Main's run resolved automatically; no Main takeover was needed. Both runs closed their owned Notepad and 7-Zip windows and recorded normal host `cleanup_verified=true`. The read-only document check matched **72** Main and **36** independent evidence-reference hashes; Main also confirmed the independent host process exited normally.

The installed Notepad oracle strings were exactly:

```text
Runtime 0.1.4 - first installed saved note
Runtime 0.1.4 - second installed saved note
```

Their SHA256 values are `6a806a7c6759b82fe091567a408e2501e3ac916e2e917197eac1a455dddb72d2` and `0d1f12eafafe51a88cf460eebb709cd976031e51d1d1f46c7010fb2fccfb7dd3`. Main's two rounds share the same target-window binding. Independent Sol saved `Independent 0.1.4 - Copper heron checks a fresh saved note.`; a complete decoded-text comparison passed, with file SHA256 `c9cb3707f30699af264f64bff44fe828604a1c838a2bd72f7042e7424c6d6c2c`.

| Complete installed API ledger | Decision primary | Grounding | Ordinary review | HTTP requests | Input tokens | Output tokens | Total tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Main | 26 | 12 | 1 | 39 | 79,701 | 4,613 | 84,314 |
| Independent Sol | 13 | 6 | 0 | 19 | 39,085 | 2,515 | 41,600 |
| Combined | 39 | 18 | 1 | 58 | 118,786 | 7,128 | 125,914 |

Both accounting records are complete with no unknown requests; these totals come from actual deduplicated requests, not a per-step estimate. They exclude earlier source runs and Main/worker subscription usage. The earlier independent read-only summary's partial usage is superseded by the complete DPAPI-authenticated ledger.

Final test-installation removal passed with a retained first-attempt boundary. The first external-setup uninstall removed its payload and completed worker cleanup, but deliberately preserved **6** unknown empty directories created by live imports, plus the ownership marker and `Uninstall.exe`. Main verified that only those **2** files and **6** empty directories remained, removed exactly those **6** empty directories, then reran the same setup. The second uninstall removed the test root; the external sentinel/user data and daily integration remained unchanged. This is not a first-attempt whole-root removal. Both attempt records are retained in `final-uninstall/` and `final-uninstall-empty-dir-recovery/report.json`.

Original installed-run recordings: [Notepad, client area only](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.4/AgentGUIRuntime-0.1.4-Notepad.mp4) · [7-Zip](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.4/AgentGUIRuntime-0.1.4-7Zip.mp4). Both retain original-speed model waiting apart from between-task operator gaps, but the Notepad clip omits its native menu and popup; it is incomplete as a task demonstration. A [full-window Notepad clip and browser demo](DEMO_RECORDING_20261015.md) from separate new runs supersede that presentation and explicitly trim initial waiting. Their edited durations do not replace this report's original plan timings. Cleanup is proved by uninstall receipts, not video.

### Installed step intervals

These sequential intervals run from client dispatch to the first task-decision completion, then from each task-decision completion to the next, using the same machine's monotonic clock. They include preparation, grounding, action and verification as applicable; they are not pure click or model-response times. Final client-return overhead is listed separately. Recording was enabled.

| Notepad step | First round | Second round |
| --- | ---: | ---: |
| Replace note text and verify | 14.864 s | 7.059 s |
| Open File menu and verify | 7.692 s | 7.402 s |
| Save and verify | 7.921 s | 8.287 s |
| Final client-return overhead | 0.144 s | 0.125 s |

| 7-Zip step | Interval |
| --- | ---: |
| Open A | 11.952 s |
| Open nested | 9.698 s |
| Return to A | 14.561 s |
| Return to root | 10.335 s |
| Open B | 11.259 s |
| Open bundle.zip | 11.486 s |
| Final client-return overhead | 0.226 s |

The exact nanosecond boundaries and component timings are retained in `release-plan/main-installed-facts.json`. Rounded rows may not sum exactly to the plan total; inclusive component timings must not be added together.

### Observed source runs

| Source case | Actual result | Plan elapsed time | Independent output/cleanup check |
| --- | --- | ---: | --- |
| Notepad source01 alpha, first 3-step round: edit → File → Save | Automatically `completed`, 3/3 | **26.2441151 s** | Saved UTF-8 text exactly matched alpha; before client repair |
| Notepad source01 beta, same-window 3-step second round | Automatically `completed`, 3/3 | **30.714762 s** | Saved UTF-8 text exactly matched beta; owned window closed, host cleanup verified; before client repair |
| 7-Zip first 9-step navigation attempt | First 7 steps verified; step 8 entered the C path, then Decision and ordinary review falsely rejected its text; no Enter; safe `failed` | **101.1386813 s to failure** | Owned window closed, host cleanup verified; failure retained |
| 7-Zip candidate01, 10-step file navigation | Backend `completed` all 10; public `ExecutionClient` raised `ValueError` at its old eight-step receipt limit; harness recorded `result_unknown` | **112.6966344 s to error** | End-to-end acceptance failed; backend completion alone is insufficient |
| 7-Zip same-window 4-step continuation after that error | Automatically `completed`, without Main review | **45.5966418 s** | Continuity evidence only; not a replacement for the repaired long-plan retest |
| Repaired source02 / frozen candidate02, fresh-data 12-step run | Automatically `completed`; public client returned terminal; 12/12 history rows succeeded | **131.8980933 s** | Main checked the bound final image showing `journey_complete.txt` |
| Repaired source02, same-window 4-step continuation | Automatically `completed`; 4/4 history rows succeeded | **46.3820546 s** | Owned close returned `window_closed` in **129.5041 ms**; normal host `cleanup_verified=true` |

Source02 used fresh `e014-03` data. Its 12-step case added navigation into the prepared archive's `package` directory and `inside_archive.txt`, then returned; it is not the identical earlier 10-step case. All **16 history rows succeeded**, with **0 agent judgments / Main reviews**. The API ledger for those 16 steps records **32 Decision calls, 16 grounding calls and 0 ordinary reviews**, with **120,086 input + 6,782 output = 126,868 tokens**. Startup and closure made no API call. These totals exclude Main/worker subscription usage and all earlier source01 runs. Notepad remains source01 evidence, not a repaired source02 retest.

Notepad's disk oracle read these exact strings as UTF-8:

```text
Runtime 0.1.4 alpha - fresh saved note
Runtime 0.1.4 beta - second saved note
```

The corresponding file SHA256 values are `081ecaeb1b93037e4518232d8bfba158344703c0c0c2e2dda7ab40ce5a9697bd` and `ee9acee7db96dd1bce71a8ab0c80711e80d1d7c0a4e3bfade354cb29f67d6f08`. Both rounds used the same note window. `main-source-01/finished.json` records `cleanup_verified=true`; the note and first 7-Zip owned-window close receipts are retained separately.

### Failures and repair boundary

The first 7-Zip failure is a model false rejection after text entry. The text gate withheld Enter and exposed failure; no compression, extraction or final-submit action was attempted. This evidence does not establish a runtime binding or coordinate defect, and no prompt/threshold repair is claimed here.

The second failure violates the shared public-receipt contract: a supported linear plan completed in the backend but the public client rejected its history length. The location identified was `scripts/learning_benchmark_client.py:391`, with a residual `count <= 8` guard. That fixed cap is now removed in the shared client, rather than adding a 7-Zip adapter: every application using a long caller plan needs the same receipt support. New `tests/test_execution_client_unbounded_plan.py` produced **3 failures and 18 passes before the fix, then 21 passes**: successful 9/10/258-step receipts and 18 malformed cases that remain rejected. The related five-module group passed **140 checks in 12.54 s**, followed by the frozen source02 12+4-step live pass and cleanup above. Extending accepted receipt length does not relax input, evidence, cancellation or final-submit gates. Both original source runs and their failures are retained.

### Offline checks and evidence

Main's earlier source contract groups passed **382 checks across 12 files**. The component module separately passed **10 tests**, including a temporary source payload and isolated real-entrypoint dependency checks. The later client-repair group passed **140 checks across 5 modules in 12.54 s** and overlaps the earlier groups; these counts are not summed as unique tests. The client repair is offline and source-live verified. The installed Main and independent cases above also passed; final test-installation removal passed after the explicit cleanup above.

Local evidence root: `D:/AgentGUI-Projects/evidence/execution-release-014-20261015-01/`.

- `main-source-01/responses/0003-seven-round-01.json`: first 7-Zip failure.
- `main-source-01/responses/0007-note-alpha-01.json`, `0008-note-beta-01.json`, `note-alpha-disk-oracle.json`, `note-beta-disk-oracle.json`: Notepad rounds and independent disk checks.
- `main-source-01/responses/0004-seven-close-01.json`, `0009-note-close-01.json`, `finished.json`: owned-window closure and host cleanup.
- `main-source-02/`: 10-step client error and subsequent same-window continuation; retain original commands, events, response and backend receipts.
- `source-candidate-02/`, `main-source-03/`: repaired frozen code, fresh 12+4-step terminal responses, original evidence and owned-window closure; `main-source-03/finished.json` verifies normal host cleanup.
- `main-installed/responses/0003-installed-note-alpha.json`, `0004-installed-note-beta.json`, `0008-installed-seven-plan.json`, `main-installed/alpha-oracle.json`, `beta-oracle.json` and `finished.json`: installed Main rounds, disk checks and cleanup.
- `independent/ACCEPTANCE.json`: final independent acceptance; `final-uninstall-empty-dir-recovery/report.json`: completed test uninstall with the retained first-attempt boundary.
- `independent/run/responses/0003-sol-e014-note-plan-01.json`, `0007-sol-e014-seven-plan-01.json`, close receipts, `finished.json` and `api-accounting.json`: independent fresh tasks, cleanup and complete accounting.
- `release-plan/component-tests-result.json`: component module result; `release-plan/release-input-audit.json`: source/resource closure audit.

The runtime caller-plan cap removal retains unique step IDs, per-step validation, context-size budgets, original evidence/window authentication, cancellation and API/time budgets. See [source regression](UNBOUNDED_TASK_PLANS_20261015.md). [Operation timings from 0.1.3](EXECUTION_OPERATION_TIMINGS_20261015.md) remain historical; they are not 0.1.4 measurements or a controlled speed comparison. No general model accuracy, unattended application coverage or new-machine dependency setup claim follows from these results.

## 简体中文

**状态：0.1.4 限定安装态验收完成。** Main 安装态任务及独立 Sol 任务已通过；经下述确切空目录清理后，最终测试安装移除通过。发布元数据与校验值见[发布页](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.4)。下述安装态与源码结果分别测量。记事本 source01 连续使用早于公共客户端修复；修复后 source02 通过全新 7-Zip 12+4 步及收尾。此前两次 7-Zip 失败继续记为失败。

范围为通过维护的截图 → 视觉定位 → Decision → 门控动作路线，验证全新的非浏览器 Windows 任务。记事本编辑并保存便笺；7-Zip 只导航目录和预制 ZIP，**没有测试压缩或解压**。仅使用本轮文件与本轮窗口；验证这些软件不等于所有 Windows 应用均受支持。保留浏览器数据，禁用 Codex 原生 Computer Use，桌面输入同一时间仅一个执行者。

### 安装态实测

Main 安装态与独立任务使用同一安装根目录，各自采用全新任务数据。

| 安装态任务 | 实际结果 | 计划耗时 |
| --- | --- | ---: |
| Main 记事本 alpha：编辑 → File → Save | 自动完成，3/3；保存的 UTF-8 内容完全匹配 | **30.6212448 秒** |
| Main 记事本 beta，同窗口第二轮 | 自动完成，3/3；保存的 UTF-8 内容完全匹配 | **22.8734135 秒** |
| Main 7-Zip：A → nested → Up → root → B → bundle.zip | 自动完成，6/6；压缩包内 package 目录可见 | **69.5148003 秒** |
| 独立 Sol，全新记事本编辑／保存任务 | 首次自动完成，3/3；精确磁盘内容及原图核对通过 | **25.4670209 秒** |
| 独立 Sol，全新 7-Zip A → nested → Up | 首次自动完成，3/3；原图核对通过 | **29.260771 秒** |
| 最终测试安装移除 | 核对并清理确切空目录后，第二次卸载通过 | 不属于计划计时 |

Main 的 **12** 条及 Sol 的 **6** 条历史全部成功，agent judgment／Main 审核为 **0**。Main 运行中有一次普通复核，自动解决，无需 Main 接管。两组运行均已关闭各自的记事本和 7-Zip 窗口，宿主正常 `cleanup_verified=true`。只读文档核验确认 Main **72** 份和独立 **36** 份引用证据摘要一致；Main 另确认独立宿主进程正常退出。

安装态记事本 oracle 内容精确为：

```text
Runtime 0.1.4 - first installed saved note
Runtime 0.1.4 - second installed saved note
```

对应 SHA256 分别为 `6a806a7c6759b82fe091567a408e2501e3ac916e2e917197eac1a455dddb72d2` 和 `0d1f12eafafe51a88cf460eebb709cd976031e51d1d1f46c7010fb2fccfb7dd3`。Main 两轮绑定同一目标窗口。独立 Sol 保存 `Independent 0.1.4 - Copper heron checks a fresh saved note.`；完整解码文本比较通过，文件 SHA256 为 `c9cb3707f30699af264f64bff44fe828604a1c838a2bd72f7042e7424c6d6c2c`。

| 完整安装态 API 账本 | Decision primary | 定位 | 普通复核 | HTTP 请求 | Input tokens | Output tokens | Total tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Main | 26 | 12 | 1 | 39 | 79,701 | 4,613 | 84,314 |
| 独立 Sol | 13 | 6 | 0 | 19 | 39,085 | 2,515 | 41,600 |
| 合计 | 39 | 18 | 1 | 58 | 118,786 | 7,128 | 125,914 |

两份账本均完整、无未知请求；上述数量来自实际去重请求，不按每步次数估算。不含此前源码运行或 Main／worker 套餐用量。早期独立只读摘要的部分用量已由完整 DPAPI 认证账本取代。

最终测试安装移除通过，但保留首次过程边界。第一次 external setup 卸载已移除其载荷并完成 worker 收尾，按设计保留 live import 生成的 **6** 个未知空目录，以及归属 marker 和 `Uninstall.exe`。Main 核对只剩这 **2** 个文件及 **6** 个空目录，精确移除这 **6** 个空目录，再运行同一 setup。第二次卸载移除测试根；外部 sentinel／用户数据及日常集成保持不变。这不是首次卸载直接删除整根，两次证据分别保留在 `final-uninstall/` 和 `final-uninstall-empty-dir-recovery/report.json`。

原安装态录像：[记事本，仅客户区](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.4/AgentGUIRuntime-0.1.4-Notepad.mp4) · [7-Zip](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.4/AgentGUIRuntime-0.1.4-7Zip.mp4)。两段除任务间人工空档外均保留原速模型等待，但记事本片漏掉原生菜单及下拉菜单，不能完整展示任务。另用全新运行补录的[记事本完整窗口片及浏览器 Demo](DEMO_RECORDING_20261015.md)已替代该展示，并明确剪去首次等待；剪后时长不替换本文原计划耗时。收尾由卸载回执证明，不由视频代替。

### 安装态逐步区间

以下连续区间由客户端派发起点至首个任务判断结束，再由每次任务判断结束至下一次结束，使用同机单调时钟计算；按具体步骤包含准备、定位、动作和核验，不是纯点击或模型响应时间。客户端最终返回余量单列，测试时开启录屏。

| 记事本步骤 | 首轮 | 第二轮 |
| --- | ---: | ---: |
| 替换便笺文字并核验 | 14.864 秒 | 7.059 秒 |
| 打开 File 菜单并核验 | 7.692 秒 | 7.402 秒 |
| 保存并核验 | 7.921 秒 | 8.287 秒 |
| 客户端最终返回余量 | 0.144 秒 | 0.125 秒 |

| 7-Zip 步骤 | 区间 |
| --- | ---: |
| 打开 A | 11.952 秒 |
| 打开 nested | 9.698 秒 |
| 返回 A | 14.561 秒 |
| 返回根目录 | 10.335 秒 |
| 打开 B | 11.259 秒 |
| 打开 bundle.zip | 11.486 秒 |
| 客户端最终返回余量 | 0.226 秒 |

确切纳秒边界与组件计时保留于 `release-plan/main-installed-facts.json`；四舍五入后的分项未必精确相加为计划总时间，包含关系的组件计时不可相加。

### 源码实测

| 源码任务 | 实际结果 | 计划耗时 | 独立输出／收尾检查 |
| --- | --- | ---: | --- |
| 记事本 source01 alpha 首轮 3 步：编辑 → File → Save | 自动 `completed`，3/3 | **26.2441151 秒** | 保存的 UTF-8 内容与 alpha 完全一致；早于客户端修复 |
| 记事本 source01 beta 同窗口第二轮 3 步 | 自动 `completed`，3/3 | **30.714762 秒** | 保存的 UTF-8 内容与 beta 完全一致；本轮窗口已关闭，宿主收尾通过；早于客户端修复 |
| 7-Zip 首次 9 步导航 | 前 7 步核验通过；第 8 步输入 C 路径后，Decision 和普通复核均误拒内容，未按 Enter，安全 `failed` | **101.1386813 秒至失败** | 本轮窗口已关闭，宿主收尾通过；保留失败 |
| 7-Zip candidate01 的 10 步文件导航 | 后端 10 步全部 `completed`，但公共 `ExecutionClient` 旧八步回执限制抛出 `ValueError`，harness 记录 `result_unknown` | **112.6966344 秒至异常** | 端到端验收失败，后端完成本身不足以计通过 |
| 异常后同一 7-Zip 窗口的后续 4 步 | 自动 `completed`，无 Main 审核 | **45.5966418 秒** | 仅为连续使用证据，不能代替修复后的长计划复测 |
| 修复后 source02／冻结 candidate02，全新 12 步 | 自动 `completed`，公共客户端返回终态，12/12 历史成功 | **131.8980933 秒** | Main 已核对显示 `journey_complete.txt` 的绑定末图 |
| 修复后 source02，同窗口后续 4 步 | 自动 `completed`，4/4 历史成功 | **46.3820546 秒** | 本轮关闭在 **129.5041 毫秒**后返回 `window_closed`，宿主正常 `cleanup_verified=true` |

source02 使用全新 `e014-03` 数据；12 步增加了进入预制 ZIP 的 `package` 目录和 `inside_archive.txt`、再返回的导航，与此前 10 步并非相同任务。**16 条历史全部成功，agent judgment／Main 审核为 0**。这 16 步的 API 账本为 **32 次 Decision、16 次定位、0 次普通复核**，**120,086 input + 6,782 output = 126,868 tokens**；启动与关闭没有 API 请求。不含 Main／worker 套餐用量，也不含此前 source01 运行。记事本继续作为 source01 证据，不冒充修复后的 source02 复测。

记事本磁盘核验按 UTF-8 读取，内容精确为：

```text
Runtime 0.1.4 alpha - fresh saved note
Runtime 0.1.4 beta - second saved note
```

对应文件 SHA256 分别为 `081ecaeb1b93037e4518232d8bfba158344703c0c0c2e2dda7ab40ce5a9697bd` 和 `ee9acee7db96dd1bce71a8ab0c80711e80d1d7c0a4e3bfade354cb29f67d6f08`。两轮复用同一记事本窗口。`main-source-01/finished.json` 记录 `cleanup_verified=true`；记事本及首次 7-Zip 的本轮窗口关闭回执分别保留。

### 失败与修复边界

首次 7-Zip 为输入文字后的模型误拒。文字门禁阻止 Enter，并明确返回失败；没有执行压缩、解压或最终提交动作。本证据不能证明运行时绑定或坐标缺陷，此处不声称修复过提示词或阈值。

第二次失败违反公共回执的共用合同：受支持的线性计划已在后端完成，但公共客户端仍因历史长度拒绝结果。定位为 `scripts/learning_benchmark_client.py:391` 残留的 `count <= 8` 限制。现已在共用客户端移除固定上限，而非添加 7-Zip 适配器；任何应用的长调用方计划都需要相同的回执支持。新增 `tests/test_execution_client_unbounded_plan.py` 修复前为 **3 失败、18 通过，修复后 21 通过**，覆盖 9／10／258 步成功回执和继续拒绝的 18 项畸形用例。相关五模块 **140 项检查通过，耗时 12.54 秒**，之后冻结 source02 完成上表 12+4 步实机及收尾。放宽回执长度不弱化输入、证据、取消或最终提交门禁；两轮原始源码运行及失败均保留。

### 离线检查与证据

Main 此前源码合同分组共 **12 个文件、382 项检查通过**。组件模块另有 **10 项测试通过**，包含临时源码载荷及隔离真实入口依赖检查。后续客户端修复分组共 **5 个模块、140 项检查通过，耗时 12.54 秒**，与此前分组有重叠，不相加为独立用例总数。客户端修复已有离线及源码实机验证；上列 Main 安装态与独立任务也已通过，最终测试安装经上述确切清理后移除通过。

本地证据根目录：`D:/AgentGUI-Projects/evidence/execution-release-014-20261015-01/`。

- `main-source-01/responses/0003-seven-round-01.json`：首次 7-Zip 失败。
- `main-source-01/responses/0007-note-alpha-01.json`、`0008-note-beta-01.json`、`note-alpha-disk-oracle.json`、`note-beta-disk-oracle.json`：记事本两轮及独立磁盘核验。
- `main-source-01/responses/0004-seven-close-01.json`、`0009-note-close-01.json`、`finished.json`：本轮窗口关闭及宿主收尾。
- `main-source-02/`：10 步客户端异常及随后同窗口续用；原命令、事件、响应与后端回执保留。
- `source-candidate-02/`、`main-source-03/`：修复后冻结源码、全新 12+4 步终态响应、原始证据及本轮窗口关闭；`main-source-03/finished.json` 核对宿主正常收尾。
- `main-installed/responses/0003-installed-note-alpha.json`、`0004-installed-note-beta.json`、`0008-installed-seven-plan.json`、`main-installed/alpha-oracle.json`、`beta-oracle.json`、`finished.json`：Main 安装态两轮、磁盘核验及收尾。
- `independent/ACCEPTANCE.json`：最终独立验收；`final-uninstall-empty-dir-recovery/report.json`：测试卸载完成，保留首次过程边界。
- `independent/run/responses/0003-sol-e014-note-plan-01.json`、`0007-sol-e014-seven-plan-01.json`、关闭回执、`finished.json`、`api-accounting.json`：独立全新任务、收尾及完整计费账本。
- `release-plan/component-tests-result.json`：组件模块结果；`release-plan/release-input-audit.json`：源码与资源闭合审计。

运行时取消调用方计划固定步数，仍保留唯一步骤 ID、逐步校验、内容大小预算、原始证据／窗口认证、取消及 API／时间预算，见[源码回归](UNBOUNDED_TASK_PLANS_20261015.md)。[0.1.3 逐操作计时](EXECUTION_OPERATION_TIMINGS_20261015.md) 继续作为历史记录，不套用为 0.1.4 测量，也不构成受控提速比较。这些结果不能推出通用模型准确率、任意应用无人值守覆盖或全新机器依赖安装通过。
