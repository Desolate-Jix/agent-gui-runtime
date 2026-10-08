# Decision preview.2 acceptance / 判断 API preview.2 验收

Versions / 版本：learning **0.1.0-preview.2**；execution **0.1.2-preview.2**。日期 / Date：2026-10-08。

## Scope and method / 范围与方法

本轮使用新建 Image Flow Lab 窗口、新数据根、新教学截图和新工作流版本。真实点击全部经过维护 MCP、目标新鲜度检查和原动作接口；视觉复核复用同一个 Sol Ultra 会话。未调用原生 Codex Computer Use。API 仅上传本轮测试窗口；Key 不进入参数、截图、配置或发布包。 / A newly created native fixture, fresh teaching captures and new pinned programs exercise the maintained MCP/action path. Visual reviews reuse one Sol Ultra worker. Only this owned test window is sent to the API; credentials remain outside artifacts.

两步任务为 HOME → DETAIL → HOME，每轮替换数据。图像、Agent、语义判断三组使用相同审核后的点击规则，仅结果核验不同。图像路线沿用零固定观察等待；纯 Agent 和纯 Decision 路线保留每步 2 秒观察等待。测试真值只用于最终评分，不传给模型或视觉审核。 / The paired two-step task changes data every run. Grounding rules are identical; verification differs. Image checks retain zero fixed observation wait; pure Agent/Decision retain the existing 2 seconds per step. Fixture truth is used only for scoring.

## Source results / 源码结果

首次复用因教学审核漏掉动态 `Current data` 锚点，进入重新定位等待。该次无输入，原请求取消并保留；原稿、原程序版本均保留。通过公开审核/保存接口将锚点改为本轮真实观测到的固定标题，再创建新确切版本。自动锚点提案仍需审核。 / The first reuse exposed a changing anchor missed during teaching review. It was cancelled without input and retained. The public editing/save path pinned new versions using the observed stable title; automatic anchor proposals still require review.

修订后 12 个用例达到预期：图像连续三次、延迟跳转、阻断跳转，Agent 两步对照，纯语义三种主题与阻断，图像+Decision 正例与阻断。三个阻断用例均停止且没有下一步点击。首次失配不算通过，复测成功不改写首轮记录。 / Twelve subsequent cases reached their expected outcomes, including three blocked-transition negatives. The original anchor failure remains separate from successful reruns.

| Route / 路线 | n | Two-step wall time / 两步总耗时 | API / Agent review |
| --- | ---: | --- | --- |
| Local image / 本地图像 | 3 | 4.739 / 4.752 / 4.890 s；median **4.752 s** | 0 / 0 |
| Explicit Decision / 纯语义 | 3 | 10.692 / 9.274 / 9.140 s；median **9.274 s** | 2 per run / 0 |
| Sol Ultra review / Agent 复核 | 1 | **69.270 s** | 0 / 2 |

计时边界为准备数据之后、start 调用之前，到原最终状态回读完成。Agent 数字包含编排、视觉会话往返与读取，不是纯模型推理耗时。混合正例耗时 120.742 秒，包含 Main 排查及一次 Agent 复核等待，单独保留，不纳入自动路径速度对比。 / Wall time includes orchestration and original status retrieval. The mixed case's 120.742 seconds includes diagnosis and Agent review and is not an automatic-path benchmark.

前版已发布安装包本地图像两步流程 Main 中位数 **5.94 秒**、独立 Sol **5.97 秒**（各 n=3），见 [历史验收](https://github.com/Desolate-Jix/agent-gui-runtime/blob/3cd9b989c11592595ae5e63bd6dd183d33554068/docs/verification/LEARNING_PREVIEW_RELEASE_ACCEPTANCE_20261007.md)。本轮源码 4.752 秒与旧安装结果是跨批次观察，不能把差值归因于 Decision API，也不能用源码结果代替新安装包的结果。 / Historical installed medians and current source measurements belong to different batches; their difference is not a causal API speedup or installed-candidate result.

## Actual judgments / 真实判断

源码批次共 **12 次**付费请求，账本原结果全部通过 DPAPI 认证：普通执行前/后检查 2 次，纯语义 7 次，图像匹配失败后的语义检查 3 次。输入 **6,956 tokens**，输出 0。未重试付费请求或输入。 / Twelve source-batch requests have authenticated original records, using 6,956 input tokens and zero output tokens, with no repeated paid dispatch or input.

| Timing / 时长口径 | n | Min / 最小 | Median / 中位数 | Max / 最大 |
| --- | ---: | ---: | ---: | ---: |
| HTTP round trip / HTTP 往返 | 12 | 109 ms | **179 ms** | 1,538 ms |
| Service elapsed / 服务层 | 12 | 114 ms | 184 ms | 2,178 ms |
| Provider processing header / 供应商处理头 | 12 | 55 ms | 72 ms | 440 ms |

三种时长互相包含，不能相加；服务层统计结束于最终加密结果落盘之前，供应商处理头也不等于纯神经网络推理。 / Timings overlap and must not be summed. Service timing excludes final encrypted result persistence; the provider header is not a pure inference measurement.

API 自动采用 11/12：9 个成功条件、2 个不满足条件；另 1 个 HOME 正例仅给出 **0.81**，低于 0.9 阈值，保持 uncertain 后由 Sol 查看当前原图完成复核。保留阈值和原请求，未为通过测试重问模型。混合正例两步中仅 1 步由 API 自动结算；另一项阻断混合用例正确停止。样本小且界面简单，不能声明通用准确率或每次都自动完成。 / Eleven results were automatically adopted; one true HOME case scored 0.81 and required fresh-image Agent review. Thresholds were unchanged. This small controlled sample establishes neither general accuracy nor guaranteed automation.

另在不带 Key 的新进程中重新打开两份真实执行判断，原认证通过，篡改结果和错误执行绑定被拒绝；网络尝试为 0、原账本 SHA 不变。这是证据恢复验证，未冒充 GUI 崩溃恢复验收。 / A fresh keyless process authenticated original execution results, rejected tampering and wrong bindings, made zero network attempts and preserved the database hash. This is evidence recovery, not a desktop crash-recovery claim.

## Packaging and installed acceptance / 打包与安装验收

执行 `0.1.2-preview.2` 冻结安装器 SHA256 为 `540c6dc3d8d1912fd4ce436a6fae876c18d1e5a0e31fa2374eeaa5cac03ad83f`。`build-record.json` 记录隔离依赖/入口检查通过；`installed-test-manifest.json` 记录真实载荷 `--check-install` 退出 0、532 个文件核验通过。安装于同一新建 TEMP checkBase，`integration_written=false`；用户现用 preview.1 不覆盖，HKCU 注册和快捷方式未在本轮重验。 / The frozen execution installer passed isolated dependency checks and test-mode installation with 532 verified files. Its real payload uses a fresh temporary root without registry/shortcut integration or overwriting the user's preview.1.

### Main installed runtime / Main 安装版执行载荷

Main 从上述实际安装根启动 MCP，在 `decision-api-20261008-main-installed-01` 使用新窗口、新教学与新数据。七个原始用例及 `installed-runtime-metrics.json` 一致：五个正例完成，两个阻断负例正确停止；各用例记录 `cleanup_verified=true`。Main 最终宿主/窗口清理见下节；共享测试安装目录的卸载另行记录。 / Main exercised the installed runtime with fresh teaching and data. Seven cases reached their expected outcomes: five completions and two blocked failures, with verified per-case cleanup. Final Main host/window cleanup is recorded below; shared test-installation uninstall is tracked separately.

| Installed route / 安装版路线 | n | Wall time / 总耗时 | Decision / Review |
| --- | ---: | --- | --- |
| Local image stable / 图像稳定 | 3 | 4.4591067 / 4.5438493 / 4.5324778 s；median **4.5324778 s** | 0 / 0 |
| Local image delayed / 图像延迟 1.2 s | 1 | **5.956344 s** | 0 / 0 |
| Local image blocked / 图像阻断 | 1 | **77.6900604 s**，包含 Agent/人工编排复核 | 0 / 1 |
| Explicit Decision positive / 语义正例 | 1 | **10.9602484 s** | 2 / 0 |
| Explicit Decision blocked / 语义阻断 | 1 | **4.8445144 s** | 1 / 0 |

计时仍从 prepare 完成到原最终状态回读，不含后续清理。图像阻断的 77.690 秒包含 Agent/人工编排，不作为自动核验速度。当前安装图像中位数与前版 5.94/5.97 秒仍是跨批次观察，不能归因于 API 或外推速度收益。三个实际判断自动采用两个 success 和一个 failure；负例只发生 Open 点击，没有 Back 或重复输入。Main 的无 Key 只读复算记录三份原结果认证通过、账本 SHA 不变；本批输入 1,692 tokens、输出 0，与源码批次的 12 次请求分开统计。 / Timings end at original status retrieval and exclude later cleanup. The blocked image case includes manual orchestration and is not an automatic-speed result. Historical comparisons remain observational. Three installed decisions adopted two successes and one failure; the negative case stopped after one click. Main's keyless read-only metrics authenticate the original results and preserve the ledger. Installed usage is separate from the source batch.

首次 `installed-main01-image-stable-3` 在辅助 fixture 的 prepare 文件 rename 遇到 WinError 5，发生于第三次运行派发前，`runtime_submitted=false`、`input_executed=false`，没有该次输入或 API。原始 prepare 与失败 marker 保留；修复仅限辅助文件同一待写内容的有界替换，26 项离线检查通过。随后 `installed-main02-image-stable-3` 是独立新用例，不改写首次失败，也未修改冻结执行载荷。 / A fixture-file publish failed before runtime submission. The original prepare/marker remain retained. A bounded auxiliary same-file publish fix passed 26 checks; the subsequent third sample has a separate case identity and does not erase the failure or change the runtime payload.

### Main installed GUI and cleanup / Main 安装版 GUI 与清理

默认英语的新学习安装器为 `0.1.0-preview.2`，SHA256 `b4d6291703d6224b4a6210e93d68cb7af1e552a904845c738e1bd5a815c1a335`。`build-english/installed-test-manifest.json` 记录同一 TEMP checkBase 内拥有归属的测试学习安装升级成功，349 个文件核验通过、退出 0、`integration_written=false`；执行组件维持上述冻结载荷。 / The replacement English-default learning installer upgraded the owned test installation in the same temporary root, verified 349 files and exited successfully without registry/shortcut integration. Execution retained its original frozen payload.

旧 GUI 候选已正常关闭，`gui-1/closed.json` 记录退出 0；其 `gui-main-results` 操作因目标遮挡返回 `CaptureVisibilityError`，`action_executed=false`、`dispatch_attempts=[]`。该操作未派发，原失败保留，不作为产品修复或 GUI 主链通过。 / The previous GUI exited normally, but its attempted Results operation was refused by an occluded capture with no input dispatch. The original failure is retained without claiming a product fix or GUI-journey pass.

旧 `gui-profile` 当前已有 `en-US` 偏好，其写入来源不在这条证据链，不能证明首次默认英语。Main 使用全新 `gui-profile-english-default`，首次偏好文件不存在；`gui-2/english-default-audit.json` 与原截图记录实际菜单、三个主页签和步骤编辑器为 English。通过 Settings → Language → 简体中文的三次维护门禁点击切中文并保存偏好，不改写或推断旧偏好来源。 / The previous profile does not establish the first-launch default. Main used a fresh profile with no preference file, observed English menus/tabs/editor, then switched to Chinese through three gated menu clicks and saved the preference.

在新 GUI 中打开结果规则、关闭首步图像核验并点击保存。原 `gui-zh-save` job 为 completed，产生一次派发并返回 captured 动作后图；实际公开读回的 `gui-2/saved-workflow-audit.json` 记录新确切程序版本，两个 `decision_condition` 保留、原固定版本不变，编辑后的首步回到 pending 审核。关闭重开后，`gui-3/reopened-audit.json` 记录中文保持、相同新版本与首步图像关闭保持、判断账本未变，仍为三次 API。 / The GUI Save job completed with one dispatch and captured post-action evidence. Public readback confirmed a new pinned program, both semantic conditions preserved and the original version unchanged; the edited first step requires review. Reopening retained Chinese, the saved image disablement and program, with the ledger unchanged at three API calls.

`main-installed-complete.json` 记录 Main 完成：GUI index 1（旧）、2（新）、3（重开）均正常退出 0，fixture 退出 0；宿主 `cleanup_verified=true`、`host_alive=false`、`pending_ids=[]`、`cleanup_errors=[]`。七个原 GUI 操作均 completed、单次派发、captured 观察，无自动重试。 / Main's original completion record confirms three normal GUI exits, fixture exit zero and a stopped host with verified cleanup, no pending requests and no cleanup errors. All seven GUI operations completed with one dispatch and captured evidence.

默认语言源码五文件离屏回归仍为 **42 passed in 14.04s**；530 项 execution 冻结输入摘要未变。 / The 42 focused language checks and unchanged execution freeze remain valid.

### Independent installed acceptance / 独立安装版验收

独立 Sol Ultra 使用 `decision-api-20261008-independent-installed-01` 的全新窗口、教学与数据，在 Main 完成后验收同一最终 E/G 载荷，最终 `independent-report.json` 记录 `passed=true`。`frozen-pair-audit.json` 核验执行 532 项、学习 349 项及上述两个 Setup SHA 一致；独立七个原始用例与 `independent-metrics.json` 一致，五个正例完成、两个阻断负例正确停止。 / Independent Sol Ultra used fresh teaching and data after Main's acceptance, verifying the same final execution/learning payloads and installer identities. Its final report records a pass; seven original cases reached five completions and two expected blocked failures.

| Independent route / 独立路线 | n | Wall time / 总耗时 | Decision / Review |
| --- | ---: | --- | --- |
| Local image stable / 图像稳定 | 3 | 4.510305 / 4.6457045 / 4.5148242 s；median **4.5148242 s** | 0 / 0 |
| Local image delayed / 图像延迟 1.2 s | 1 | **5.974997 s** | 0 / 0 |
| Local image blocked / 图像阻断 | 1 | **29.988405 s**，包含 Agent 编排复核 | 0 / 1 |
| Explicit Decision positive / 语义正例 | 1 | **10.3187968 s** | 2 / 0 |
| Explicit Decision blocked / 语义阻断 | 1 | **4.7186372 s** | 1 / 0 |

独立三次 API 为两个 success 与一个 failure，输入 1,692 tokens、输出 0；无 Key 只读复算认证原结果且账本未变。图像阻断含 Agent 编排，不作自动速度对比。前版安装图像 Main 5.94 → 本轮 4.5324778 秒、Sol 5.97 → 本轮 4.5148242 秒（各 n=3），观察中位数分别低约 23.70%/24.37%，约 24%；这是不同批次的小样本观察，不是 Decision 导致提速的因果结论或通用速度保证。 / Independent decisions adopted two successes and one failure, using 1,692 input tokens and zero output tokens; keyless authentication preserved the original ledger. Image medians were approximately 24% lower than the previous installed batches, but this cross-batch observation does not establish a causal API speedup or general benefit.

独立 GUI 首启和重开均为 English；四次维护门禁点击完成结果页打开、关闭首步图像核验、保存及重开后查看。原 `gui-save-audit.json` / `gui-reopen-audit.json` 确认新程序版本、两个 Decision 条件保留、首步图像关闭保持、原固定版本不变；编辑首步仍需审核。两个 GUI `closed.json` 均退出 0，fixture 退出 0；`bridge-01/closed.json` 记录 `cleanup_verified=true`、`host_alive=false`、`pending_ids=[]`、`cleanup_errors=[]`。因此同一冻结候选的 Main 与独立实装主链、保存重开及各自最终宿主/窗口清理均完成；原先源码、辅助 prepare 与旧 GUI 遮挡失败仍单列保留。 / Independent GUI saving/reopening preserved both semantic conditions, image disablement and the original version. Both GUI instances and the fixture exited normally; the host stopped with verified cleanup and no pending requests or cleanup errors. Main and independent installed journeys are complete without erasing the earlier failures.

源码 12 次、Main 实装 3 次、独立实装 3 次合计 **18 次**判断，`combined-api-metrics.json` 记录输入 **10,340 tokens**、输出 0；采用 17 次（13 success、4 failure），1 次灰区保留 Agent 复核。HTTP 时长最小 **109.3689 ms**、中位 **184.19835 ms**、最大 **1,556.163 ms**；这是请求级 HTTP 往返，不能当作整条工作流或纯推理时长，也不与服务层/处理头相加。 / The three distinct batches total 18 requests and 10,340 input tokens, with 17 adopted results and one gray-zone review. Median HTTP round trip is 184.19835 ms; it is neither end-to-end workflow nor pure inference latency.

### Test uninstall and local residue / 测试卸载与本机残留

Main 的 `test-install-cleanup.json` 记录两个正式支持的 `--check-uninstall` 均退出 0，`worker_cleanup_complete=true`、`integration_written=false`，用户默认安装归属 marker SHA 未变。学习测试根已移除；执行测试根按安装器保留合同保持 retained 状态，剩余 297 个文件、9,875,745 bytes，仅为本次生成的 `__pycache__` 和归属/卸载器元数据，清单保留于 `test-install-retained-cache-manifest.json`。不将载荷卸载完成写成整个测试根已删除。 / Both supported payload uninstalls completed successfully without integration changes or altering the user's installation markers. The learning test root was removed; the execution root retains generated caches and ownership/uninstaller metadata, recorded in the residual manifest. Payload uninstall does not imply complete root removal.

Main 随后对这处已核验测试残留尝试的递归删除被自动批准策略拒绝（`blocked by policy`），没有执行删除，也没有绕行；这是本机环境清理约束，不作为产品回归。HKCU/快捷方式仍不在本轮重验范围。本报告记录发布前冻结验收；网络发布与资产下载状态见对应发行页。 / Automatic approval rejected the subsequent scoped residual-directory removal; no deletion or workaround occurred. This is a local cleanup constraint rather than a product regression. Registry/shortcuts were not retested. This report records acceptance at release freeze; publication and asset availability belong to the release page.

## Offline checks and limitations / 离线验证与限制

- 集成阶段执行/配置/客户端 591 项、学习/恢复 320 项、编辑器 12 项通过；各组有重叠，不相加作为独立总数。版本冻结前独立 7 文件组合 **140 passed, 1 deselected, 8.48s**，排除尚未构建的 real_payload。 / Earlier focused suites passed; counts overlap. The final independent seven-file slice passed 140 checks, excluding the not-yet-built payload test.
- 不提供判断 API 设置面板；配置使用 Python 入口和宿主环境变量。默认 shadow，只有显式 auto 和精确条件允许自动采用。 / Configuration remains file/environment based, shadow by default, with explicit allowlisted auto adoption.
- 动态输出读取仍由原读取器或 Agent 完成；判断 API 不提供坐标，不授权输入。原风险边界、未知输入不可重放的规则继续有效。 / Decisions neither locate coordinates, extract dynamic outputs nor authorize input.
- 首次锚点失配和 API 灰区均保留为限制；没有通用准确率、p95、复杂网站或跨机器性能结论。 / Anchor review and gray-zone fallback remain observed limits; no broad accuracy, p95 or cross-machine conclusion is claimed.
