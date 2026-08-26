# Portfolio Hybrid v1.1 Benchmark v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 benchmark v1、24 screenshots、120 targets 与 12 regression + 12 holdout 字节完全不变的前提下，新增一条四臂、真实 WorkflowService、物理隔离 Gold、test-owned UIA、可证明 lifecycle、且 holdout 只能消费一次的 benchmark v2。

**Architecture:** privileged projector/private scorer 与 provider runner 是不同模块、进程入口和文件输入域；runner只接收 sealed provider-safe child。每个screen group拥有一个exact test window与一次真实Hybrid cascade；incumbent可按target运行。Hybrid provider dispatch由现有WorkflowService public operation→worker→poll/adopt→continue链决定；`qwen_only`走同一service-owned worker/poll/adopt边界，所有specialized或generic入口都在同一operation lock内命中durable benchmark mode并恢复/提交同一terminal receipt，绝不进入generic cascade，benchmark始终不手排stage。Holdout以Win32 atomic zero-byte claim sentinel + HKCU registry record双锚为本地消费控制，以partitioned JSONL为审计镜像。

**Tech Stack:** Python 3.11、pytest、现有WorkflowService/Task 7/7A、Win32 HWND + Job Object、`nvidia-smi` raw transcript、canonical JSON/SHA-256、Win32 atomic claim file + HKCU registry dual-anchor CAS、append-only JSONL。

**Spec:** `D:\agent-gui-runtime\.superpowers\sdd\2026-08-25-portfolio-hybrid-v1-1-implementation-plan\task-10-preflight.md`、`task-10b-plan-review-round-1.md`、`task-10b-plan-review-round-2.md`，以及主计划 Task 10 `D:\agent-gui-runtime\docs\superpowers\plans\2026-08-25-portfolio-hybrid-v1-1-implementation-plan.md:808-861`。

## Global constraints

- 统计臂只有且必须是 `qwen_only`、`omni_only_discovery`、`omni_to_qwen`、`omni_to_qwen_vista`；任何额外statistical arm或平行VISTA authority均拒绝。
- v1七项文件、24 images、120 targets、12+12 screens、60+60 targets及partition membership不变。除Task5/6明确allowlist与mandatory Task 6 amendment A/B/C对`workflow_worker.py`、`windows_process_scope.py`、`model_server.py`、`workflow_service.py`、`panel.py`及tracked tests的窄授权外，只新增名字/contract含`v2`的文件；panel完整guarded surface为start/status/adopt/continue/cancel/heartbeat/finish/recover与runtime attachment seam，非benchmark请求/响应与incumbent/Hybrid行为必须byte/semantic不变。
- 禁止读取或触碰 `tests/test_agent_runtime_actual_adapter_portfolio_v1.py`。实现者、reviewer、provider runner不得打开holdout Gold明文。
- Gold-bearing parent只进入privileged projector或private scorer subprocess；provider child不含Gold path、target ID、acceptable region、bbox、reviewer/annotator/scorer字段。`purpose`字符串只能作标签，不能作安全边界。
- Hybrid execution unit是screen group：同屏五个target引用同一Omni inventory、Qwen bindings、fusion、VISTA proposals与capture/window/UIA refs。Incumbent若goal-dependent可按target调用。报告同时给出unique invocation count和amortized-per-target count。
- `pre_review`与append-only `post_review`属于同一logical prediction record；release只读automatic `pre_review`。
- VISTA只评估Hybrid pair：`omni_to_qwen`的same-candidate bbox center baseline，与`omni_to_qwen_vista` exact submitted proposal共享同一fusion/candidate/capture parents。失败/超时/越界/缺结果仍在submitted denominator。
- actual runner必须走WorkflowService public lifecycle：Hybrid为operation→worker→poll/adopt→continue；`qwen_only`为benchmark-scoped operation→single worker→poll/adopt→atomic terminal cut-point，禁止generic continuation。不得直接import/use `LearningStageWorkerRegistry`作为benchmark authority，也不得调用stage handlers。
- 每个screen group只允许test-owned noninteractive display window；UIA必须绑定exact HWND/PID/create-time/Job/screenshot SHA。ambient、missing、multiple或stale binding fail closed。没有真实click/fill/action/publish。
- provider严格串行；timeout/degraded/failed没有positive body-complete时保持pending，直到同一PID/create-time/socket/lease/Job termination被证明。
- regression先行且可用独立attempt events重跑；holdout subledger只有一个pre-authorized genesis和最多一个claim。永久claim namespace只由`benchmark_release_id + frozen corpus parent seal + partition=holdout`决定，不能由provider manifest/code seal分叉。Holdout claim后崩溃仍消费attempt，禁止重跑或调阈值。
- 本地双锚威胁模型只保证正常执行、进程崩溃/重启和最多一个anchor意外丢失时fail closed；不声称能抵抗同一Windows管理员恶意删除file root与HKCU root全部状态。若Portfolio release要求对本机管理员不可抵赖，必须另接不同identity拥有的外部append-only/CAS witness；这是local benchmark-v2 release limitation，不得用夸大的“物理不可删除”措辞掩盖。
- Task 0-12是TDD code slices；Task 13-16是sealed execution gates，不能以形式化RED消费真实holdout。
- Task 6 在恢复实施前必须先完整执行并独立审查 `docs/superpowers/plans/2026-08-26-portfolio-hybrid-v1-1-task6-prerequisite-amendment.md` 的 A、B1、B2；该 amendment 是 C1-C3 blocker 的唯一强制修正，不得以 Task 6 service/test 自造result或cleanup proof替代。
- 每个slice只改allowlist，并由不同reviewer关闭Critical/Important。Review写入 `D:\agent-gui-runtime\.superpowers\sdd\2026-08-25-portfolio-hybrid-v1-1-implementation-plan\task-10b-*-review.md`。

## Frozen v1 baseline

| Path | SHA-256 |
|---|---|
| `app/learn/hybrid/benchmark.py` | `5c633f48ff54192ac49b6483960c0ae6075e4ccf97234b477b1508aac7115c7a` |
| `scripts/run_portfolio_hybrid_v1_1_benchmark.py` | `9a83f101a2eb28190d890b5abcb027c140bde56795142c18e2296b863c3d583d` |
| `app/learn/hybrid/benchmark_scorer_v1.py` | `cfdade5c1bc7b9c6dc44cb66743fa4c22f70df85a6b7fadc8cdf6a10eec8a89a` |
| `configs/benchmarks/portfolio_hybrid_v1_1_gate.json` | `1c54e2216aea626e6581977522139921c51e2e97fcbf3248a1d679c311ac6173` |
| `tests/fixtures/portfolio_hybrid_v1_1/gold.v1.json` | `261ddb82346dccbcfe9595a7fd475c8476c35284aafd9ea33324a19c006a4d4f` |
| `scripts/seal_portfolio_hybrid_v1_1_corpus.py` | `51ad50ed13ebc1dcf91ea894cb63c47b1eec15d96e5598ce38c5461fa30a69a6` |
| `tests/fixtures/portfolio_hybrid_v1_1/corpus-manifest.v1.json` | `8503010496a426893456e903b9d768f2a281ef0509f11230d312b073c0760757` |

任何不一致立即BLOCK；不得更新expected hash。

## Versioned file map

| New file | Responsibility |
|---|---|
| `configs/benchmarks/portfolio_hybrid_v1_1_estimand.v2.json` | 四臂estimand、execution unit、metric formula、threshold预注册 |
| `app/learn/hybrid/benchmark_v2_contracts.py` | provider-safe run/request/prediction/refs closed contracts |
| `app/learn/hybrid/benchmark_v2_privileged_projector.py` | 唯一可解析Gold-bearing parent的projector模块 |
| `app/learn/hybrid/benchmark_v2_provider_corpus.py` | 只验证provider child；无private import/path |
| `app/learn/hybrid/benchmark_v2_provider_sandbox.py` | provider subprocess sealed read/write file allowlist与open-audit拒绝 |
| `scripts/project_portfolio_hybrid_v1_1_provider_corpus_v2.py` | privileged projector process entrypoint |
| `app/learn/hybrid/benchmark_v2_predictions.py` | 同record immutable pre-review + append-only review revisions |
| `app/learn/hybrid/benchmark_scorer_v2.py` | private metrics/gate；只由private scorer入口import |
| `scripts/score_portfolio_hybrid_v1_1_benchmark_v2_private.py` | private scorer subprocess；stdout只返回status/ref |
| `configs/benchmarks/portfolio_hybrid_v1_1_gate.v2.json` | sealed relative automatic gates |
| `app/learn/hybrid/benchmark_v2_holdout.py` | regression/holdout partitioned append-only subledgers |
| `app/learn/hybrid/benchmark_v2_durable_claim.py` | stable release namespace、Win32 atomic zero sentinel、registry双锚与local threat-model verifier |
| `app/learn/hybrid/benchmark_v2_window_owner.py` | test-owned HWND/process/Job/binding/finalization |
| `app/learn/hybrid/benchmark_v2_worker_binding.py` | serialized binding在spawned worker内重验/安装并产生normal clear；abnormal parents只来自amendment B1+B2与Task4 |
| `app/learn/hybrid/benchmark_v2_incumbent_operation.py` | single-worker qwen-only managed operation/cut-point contract |
| `scripts/portfolio_hybrid_v1_1_test_window_v2.py` | harmless Win32 screenshot window child |
| `app/learn/hybrid/benchmark_v2_lifecycle.py` | raw owner journals、per-process/device VRAM与probe receipts verifier |
| `app/learn/hybrid/benchmark_v2_actual.py` | WorkflowService-bound four-arm adapter |
| `scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py` | dry-run/regression/holdout/probe/cleanup CLI |
| `scripts/seal_portfolio_hybrid_v1_1_benchmark_v2.py` | 生成private root seal与provider-safe child seal |
| `scripts/review_portfolio_hybrid_v1_1_benchmark_v2_leakage.py` | provider projection leakage scanner |
| `scripts/authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py` | regression/leakage/durable-claim/genesis authorization |
| `scripts/assemble_portfolio_hybrid_v1_1_benchmark_v2_report.py` | public aggregate/report闭集 |
| `tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-manifest.template.json` | privileged seal template，不给runner |
| `tests/fixtures/portfolio_hybrid_v1_1/provider-corpus.v2.json` | sealed provider-safe 120-case child |
| `tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-private-manifest.json` | Gold-bearing private root，仅sealer/scorer |
| `tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-provider-manifest.json` | runner唯一manifest输入，无private path |

Narrow existing-file allowlist：原有 `app/learn/workflow_service.py`、`app/learn/workflow_worker.py`、`app/api/panel.py` 范围保持；Task 6 blocker修正仅按 mandatory amendment 额外授权 `app/learn/hybrid/windows_process_scope.py`、`app/core/model_server.py` 及其中列出的tracked tests。Panel的完整guarded surface为start/status/adopt/continue/cancel/heartbeat/finish/recover与read-only runtime attachment composition seam；route/request/response shape不变，endpoint不得直接调用Registry。不得修改 amendment/canonical task allowlist之外的existing production files。

---

### Task 0: Pre-register four-arm estimand and metric

**Allowed files:**
- Create `configs/benchmarks/portfolio_hybrid_v1_1_estimand.v2.json`
- Create `tests/test_portfolio_hybrid_v1_1_benchmark_v2_estimand.py`

**Contract:** `ARM_IDS_V2 = (qwen_only, omni_only_discovery, omni_to_qwen, omni_to_qwen_vista)`；Hybrid invocation unit=`screen_group`；incumbent unit=`target`；release arm=`omni_to_qwen_vista`；automatic split=`pre_review`。

Point metric为sealed `acceptable_region_binary_gain_v1`。Private scorer的唯一行键固定为 `(case_id,target_id,arm_id,candidate_id,vista_request_ref)`；同一个pair必须恰有两行，`arm_id`分别为`omni_to_qwen`和`omni_to_qwen_vista`，其余四项完全相同。每个target在VISTA前必须有一个sealed `target_binding_ref`选择唯一candidate，并密封`ELIGIBLE|INELIGIBLE`：ELIGIBLE必须恰有一个same-candidate `submission_status=SUBMITTED` request；duplicate/missing/ambiguous/cross-target/cross-request/eligible-but-unsent全部使run无效。INELIGIBLE必须有sealed reason和零request；若出现request同样FAIL。Scorer不得从同屏多个proposal择优。

对每个ELIGIBLE exact pair，baseline=`strict_bbox_center_v1`，即capture-pixel bbox `[x1,y1,x2,y2]` 的 `((x1+x2)/2,(y1+y2)/2)`；refined=该`vista_request_ref`唯一validated proposal的canonical capture-pixel point。任一acceptable region以half-open规则 `x1 <= x < x2 && y1 <= y < y2`命中则1，多region取OR；submitted后的failed/timeout/out-of-bounds/missing refined=0且仍计入denominator。`gain_numerator=sum(refined_hit-baseline_hit)`，`gain=gain_numerator/submitted_count`使用exact rational，不round后比较。`min_vista_submitted_count=1`，不足直接FAIL；要求`gain_numerator>0`。

Regression attempt policy也预注册：同一seal下第一个完整且lifecycle verified的attempt必须成为`accepted-run-ref`；不得在多个完整attempt中挑最好结果。只有独立review判定为pre-model infrastructure failure或cleanup indeterminate的attempt才允许同seal追加一次新attempt；model-quality/gate failure必须修复并生成新seal。

Holdout claim identity同样在estimand中固定为Task3的root templates、`benchmark_release_id`、frozen corpus-parent seal、literal `partition=holdout`、claim-ID公式和canonical identity schema；**Task14**在唯一holdout前创建唯一authorization。Provider manifest/version、code/config/profile hashes、四臂顺序与exact holdout command/run order只进入该authorization payload，不参与claim key；任一值变化都使本release永久invalid，不能生成新authorization、新key或新attempt。Runner没有path/key/hash override。

其他gate固定：automatic wrong target=0、coverage>=0.20、important-target correct coverage相对`qwen_only`增量>=0.05、semantic precision相对`qwen_only`增量>=0。

- [ ] RED: tests拒绝allowlist之外的arm、target-level Hybrid重复调用、零submitted、successful-only denominator、inclusive upper bound、不同fusion/candidate/capture parents，以及同屏多proposal诱导择优、duplicate/ambiguous/cross-target/eligible-unsent；claim identity的release ID/corpus-parent seal/partition漂移FAIL，而provider manifest变化必须保持同一claim ID。
- [ ] Run RED: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_estimand.py`，Expected missing config/loader FAIL。
- [ ] GREEN: 实现config loader/test helper，只接受上述closed values。
- [ ] Run GREEN: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_estimand.py && git diff --check`。

**Independent review:** 手算bbox center、upper-edge、multi-region、failure-in-denominator和same-parent pair；输出`task-10b-slice-0-review.md`。

**No-action evidence:** metric point是private score evidence，不叫`click_point`且不进入Runtime/pathgraph/action。

**Cleanup:** 纯config/unit tests，不启动UI/service/process；tmp files由pytest关闭删除。

**Commit:** `test(benchmark-v2): preregister four-arm estimand`

---

### Task 1: Physical Gold parent → provider-safe child boundary

**Allowed files:**
- Create `app/learn/hybrid/benchmark_v2_contracts.py`
- Create `app/learn/hybrid/benchmark_v2_privileged_projector.py`
- Create `app/learn/hybrid/benchmark_v2_provider_corpus.py`
- Create `app/learn/hybrid/benchmark_v2_provider_sandbox.py`
- Create `scripts/project_portfolio_hybrid_v1_1_provider_corpus_v2.py`
- Create `tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-manifest.template.json`
- Create `tests/test_portfolio_hybrid_v1_1_benchmark_v2_isolation.py`

**Interfaces:**

```python
# privileged module/CLI only
def project_provider_corpus(*, parent_manifest_path: Path, output_path: Path) -> dict[str, str]: ...

# provider module; must not import privileged/private scorer modules
def load_provider_corpus(*, child_path: Path, expected_sha256: str) -> dict[str, object]: ...
def validate_provider_manifest(value: Mapping[str, object]) -> dict[str, object]: ...
def install_provider_file_policy(*, read_files: tuple[Path, ...], read_roots: tuple[Path, ...],
                                 write_roots: tuple[Path, ...]) -> object: ...
```

Projector subprocess alone receives v1 parent path；输出120个opaque cases：`case_id=sha256("benchmark-v2-case\0"+screen_id+"\0"+target_id)`、screen group、safe goal、image path/hash/dimensions及public layout metadata。Child递归禁止Gold/private keys与任何parent/Gold path。Runner command/env/stdin只得到provider child/provider manifest；private root不在argv/env/cwd projection。Provider subprocess在读取child后立即安装open-audit policy：只读sealed code/profile/provider child与24个exact screenshot files，只写operation/output/ledger roots；`tests/fixtures/portfolio_hybrid_v1_1`下除三个provider-safe files与24截图外全部拒绝。Private scorer是另一个entrypoint，不共享process/import graph或file policy。

- [ ] RED: dependency graph断言provider modules/runner不能import privileged/scorer；subprocess argv/env/file-open allowlist拒绝project root/private path与Gold file；nested private key、same-SHA wrong child lineage、120/24/12+12变化均FAIL。
- [ ] Run RED: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_isolation.py`。
- [ ] GREEN: 实现privileged CLI、closed child verifier与provider process open-audit；移除任何`purpose`式伪边界。
- [ ] Run GREEN: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_isolation.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_estimand.py && uv run python -m py_compile scripts/project_portfolio_hybrid_v1_1_provider_corpus_v2.py`。

**Independent review:** reviewer只看child candidate/hash/import graph，不看Gold；输出`task-10b-slice-1-review.md`。

**No-action evidence:** child标记`artifact_is_authorization=false`,`execute_binding_enabled=false`；无coordinate/action fields。

**Cleanup:** projector test subprocess在finally wait/close pipes；temp child删除；无UI/listener/lease。

**Commit:** `feat(benchmark-v2): isolate provider corpus from private parent`

---

### Task 2: Prediction record, private scorer process, and gates

**Allowed files:**
- Create `app/learn/hybrid/benchmark_v2_predictions.py`
- Create `app/learn/hybrid/benchmark_scorer_v2.py`
- Create `scripts/score_portfolio_hybrid_v1_1_benchmark_v2_private.py`
- Create `configs/benchmarks/portfolio_hybrid_v1_1_gate.v2.json`
- Create `tests/test_portfolio_hybrid_v1_1_benchmark_v2_scoring.py`

**Interfaces:**

```python
def seal_automatic_prediction(*, request_ref: Mapping[str, str], pre_review: Mapping[str, object],
                              execution_refs: list[Mapping[str, str]], lifecycle_ref: Mapping[str, str]) -> dict[str, object]: ...
def append_review_decisions(record: Mapping[str, object], decisions: list[Mapping[str, object]]) -> dict[str, object]: ...
def score_private(*, private_manifest_path: Path, prediction_run_path: Path,
                  lifecycle_path: Path, private_output_path: Path, public_ref_path: Path) -> dict[str, str]: ...
```

同一`prediction_id`含immutable `pre_review_ref`、append-only decisions、derived `post_review`与predecessor chain；no-op append byte-stable。Prediction必须携带sealed `target_binding_ref`、selected candidate、eligibility、fusion/capture/bbox refs及exact VISTA request ref或ineligible reason。Private scorer把opaque case join到private target_id后，只接受Task0的五元行键与恰好两arm pair；它不搜索“最佳proposal”。Private scorer process唯一获得private manifest；stdout仅一行canonical `{status,score_ref,content_sha256}`，stderr对case/Gold/path redaction，public ref无case evidence。Gate只读holdout automatic split和Task0 metric；regression仅precondition。

- [ ] RED: human修正不能掩盖automatic错误；duplicate arm/case拒绝；same-SHA wrong lineage拒绝；五元key duplicate/missing/ambiguous/unsent/cross-target拒绝；point denominator含失败；同屏额外更优proposal不能被选；zero submitted FAIL；stdout/stderr/private leak负控。
- [ ] Run RED: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_scoring.py`。
- [ ] GREEN: 实现closed prediction/private subprocess/gate；assembler不得import scorer internals。
- [ ] Run GREEN: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_scoring.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_estimand.py && uv run python -m py_compile scripts/score_portfolio_hybrid_v1_1_benchmark_v2_private.py`。

**Independent review:** 用synthetic private fixture手算relative coverage/precision/binary point gain；不打开real Gold；输出`task-10b-slice-2-review.md`。

**No-action evidence:** score/pass不是Runtime authorization；所有输出固定non-authorizing。

**Cleanup:** scorer subprocess finally wait，关闭stdin/out/err和private file handles；temp private output清除；无provider/UI。

**Commit:** `feat(benchmark-v2): add isolated automatic scoring gates`

---

### Task 3: Partitioned ledger and crash-safe local holdout CAS

**Allowed files:**
- Create `app/learn/hybrid/benchmark_v2_holdout.py`
- Create `app/learn/hybrid/benchmark_v2_durable_claim.py`
- Create `tests/test_portfolio_hybrid_v1_1_benchmark_v2_holdout.py`

**Interfaces:**

```python
def append_regression_event(*, ledger_root: Path, event: Mapping[str, object]) -> dict[str, object]: ...
def authorize_holdout_genesis(*, ledger_root: Path, claim_identity: Mapping[str, str],
                              authorization_ref: Mapping[str, str]) -> dict[str, object]: ...
def claim_holdout_once(*, ledger_root: Path, claim_identity: Mapping[str, str],
                       authorization_ref: Mapping[str, str]) -> dict[str, object]: ...
def recover_claim(*, claim_identity: Mapping[str, str]) -> dict[str, object]: ...
```

Regression与holdout是独立hash chains。Regression允许多个attempt events。Authorization时只要求`holdout/events.jsonl`为exact genesis且0 claim；regression chain可非空。Production claim identity在Task0/seal中预注册：

- file root：`%LOCALAPPDATA%\AgentGuiRuntime\PortfolioHybridBenchmarkV2\Claims`
- registry root：`HKCU\Software\AgentGuiRuntime\PortfolioHybridBenchmarkV2\Claims`
- `claim_identity_payload={"benchmark_release_id":"portfolio_hybrid_v1_1_benchmark_v2_release_1","corpus_parent_seal_sha256":"8503010496a426893456e903b9d768f2a281ef0509f11230d312b073c0760757","partition":"holdout"}`
- `claim_id=sha256(canonical_json(claim_identity_payload))`；不得包含provider manifest、code/config/profile hash、attempt ID或run order
- 唯一authorization object：`{claim_root}\{claim_id}.authorization.json`
- zero sentinel namespace：`{claim_root}\{claim_id}--{authorization_envelope_sha256}.claim`；任何`{claim_id}--*.claim`都表示本release已消费
- registry key：`{registry_root}\{claim_id}`

所有hash都采用无自引用两层：`payload_sha256=sha256(canonical_json(payload))`；`envelope={contract_version,payload,payload_sha256}`；`envelope_sha256=sha256(canonical_json(envelope))`保存在独立`{id,envelope_sha256}`ref中，绝不写回被hash的envelope。Authorization payload固定claim identity、provider manifest/version、code/config/profile hashes、四臂顺序、exact command/run order和owner-journal root；`CREATE_NEW`写入固定authorization path，已存在但任一byte不同即本release永久invalid。`attempt_id=sha256("benchmark-v2-holdout-attempt\0" + claim_id + "\0" + authorization_envelope_sha256)`，因此single-anchor crash只能恢复同一authorization/attempt。Claim payload固定`claim_id,authorization_ref,attempt_id,provider_manifest_sha256,absolute_owner_journal_root,state=consumed`；claim envelope按同一两层算法hash，registry分别保存canonical envelope bytes与external envelope SHA。

Runner先用Win32 `CreateFileW(path, FILE_READ_ATTRIBUTES|SYNCHRONIZE, FILE_SHARE_READ, security_attributes, CREATE_NEW, FILE_ATTRIBUTE_READONLY|FILE_FLAG_WRITE_THROUGH, NULL)`原子创建零内容sentinel；其filename含唯一authorization envelope SHA，所以zero-byte object仍绑定exact authorization ref。随后用`RegCreateKeyExW(..., REG_OPTION_NON_VOLATILE, ..., lpSecurityAttributes)` create-only创建固定claim-ID registry key，要求disposition=`REG_CREATED_NEW_KEY`，写canonical claim envelope/external SHA并`RegFlushKey`。Provider仅在两个anchors与唯一authorization exact一致后启动。

Local control的fail-closed规则固定：两个anchors exact一致=`consumed`；任一单anchor存在而另一个缺失=`consumed_incomplete`，只允许cleanup/reconcile同一attempt，不允许provider或新claim；双锚authorization/claim/envelope不一致=`permanent_refusal`，不得“选择一个”为真或创建新authorization；两个anchors都absent时仅在固定authorization也证明从未claim且holdout genesis为0 claim时才可首次claim。删除JSONL/output/attempt directory或runner process不能恢复fresh。普通/崩溃/进程重启/单anchor意外删除在此模型内可证明；同一管理员恶意删除两个root及authorization超出本地威胁模型，不能声称物理不可删除。需要更强不可抵赖时，release必须增加外部append-only remote witness后另行version，不改变本地结果的no-action性质。

- [ ] RED: 两个真实Windows process竞争同一stable release namespace只有一winner；换provider manifest/code seal仍命中同一claim ID并使release invalid而非fresh；分别kill在sentinel create、registry record write与flush之后均只恢复同一authorization/attempt；删除任一单anchor、JSONL、output或attempt directory并重启runner仍fail closed；双锚不一致永久拒绝；authorization/claim payload/envelope hash无自引用且任一byte漂移拒绝；zero sentinel filename必须含exact authorization ref；runner禁止genesis/reset/delete/path override。
- [ ] Run RED: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_holdout.py`。
- [ ] GREEN: 实现partition chains、stable release namespace、two-layer canonical hash、Win32 dual-anchor claim、registry reopen、single-anchor reconciliation和no-reset surface；test-only roots显式不同于production roots。不得把本地DACL描述成抵抗同一管理员恶意重置。
- [ ] Run GREEN: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_holdout.py && git diff --check`。

**Independent review:** real two-process concurrency、stable namespace、unique authorization、两层hash、两个anchor crash windows、single-anchor loss/mismatch、registry/file reopen、ledger deletion、restart、output absent及local-admin threat-model wording；输出`task-10b-slice-3-review.md`。

**No-action evidence:** CAS仅消费benchmark attempt，不授予action/publish。

**Cleanup:** test children finally wait并只删除test-scoped claim/registry roots。Production cleanup没有delete/reset操作，只读anchors并append terminal evidence；文档明确不能阻止同一管理员绕过本地控制删除所有roots。

**Commit:** `feat(benchmark-v2): anchor one-shot holdout durably`

---

### Task 4: Test-owned screenshot window and exact UIA binding

**Allowed files:**
- Create `app/learn/hybrid/benchmark_v2_window_owner.py`
- Create `scripts/portfolio_hybrid_v1_1_test_window_v2.py`
- Create `tests/test_portfolio_hybrid_v1_1_benchmark_v2_window.py`

**Interfaces:**

```python
def launch_owned_window(*, image_path: Path, expected_sha256: str,
                        operation_id: str, journal_path: Path) -> dict[str, object]: ...
def attest_bound_window(*, owner: Mapping[str, object]) -> dict[str, object]: ...
def close_owned_window(*, journal_path: Path, reason: str) -> dict[str, object]: ...
```

Windows production path：suspended-create child→create deterministic no-breakaway `KILL_ON_JOB_CLOSE` Job→assign→resume。Child加载exact screenshot、创建nonce class/title的noninteractive HWND并写journal。Binding seal含operation ID、screenshot SHA、PID+create-time、Job name/members、HWND、class/title、client rect/DPI和UIA root identity。调用existing bound-window context前后都re-attest；`snapshot_bound_window()`返回的root HWND必须exact。ambient/missing/multiple/stale HWND或不同screenshot一律fail，不允许fallback snapshot。

cancel、exception、outer worker death和restart从journal执行finalization intent→WM_CLOSE exact HWND→terminate same Job if needed→close handles→stable-zero descendants→EnumWindows证明HWND absent。

- [ ] RED: real harmless helper证明exact binding；ambient foreground不被读；wrong/multiple HWND拒绝；cancel/outer death/restart cleanup；same PID wrong create-time拒绝。
- [ ] Run RED: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_window.py`。
- [ ] GREEN: 实现Win32 owner/journal/reconciler；non-Windows只提供fake contract tests并skip real HWND test，不伪报production readiness。
- [ ] Run GREEN: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_window.py && uv run python -m py_compile scripts/portfolio_hybrid_v1_1_test_window_v2.py`。

**Independent review:** 核对suspended-create/Job/HWND/UIA exact binding与所有death windows；输出`task-10b-slice-4-review.md`。

**No-action evidence:** window只显示sealed bitmap，无input handler/automation/click；允许test-owned noninteractive UI，不允许ambient user UI。

**Cleanup:** 每test在`finally`调用`close_owned_window`并断言zero process/descendant/handle/Job member、HWND absent、无listener/lease；失败即test FAIL。

**Commit:** `feat(benchmark-v2): own exact screenshot window binding`

---

### Task 5: Install serialized exact binding inside spawned observation worker

**Allowed files:**
- Create `app/learn/hybrid/benchmark_v2_worker_binding.py`
- Modify `app/learn/workflow_service.py` only at benchmark-v2 server-owned worker-payload injection/cut-point helpers
- Modify `app/learn/workflow_worker.py` only at spawned entry pre-handler installation and `finally` cleanup
- Create `tests/test_portfolio_hybrid_v1_1_benchmark_v2_worker_binding.py`

**Interfaces:**

```python
def serialize_worker_window_binding(*, operation_ref: Mapping[str, object],
                                    owner: Mapping[str, object], capture_ref: Mapping[str, object]) -> dict[str, object]: ...
def install_spawned_worker_window_binding(*, serialized: Mapping[str, object],
                                          worker_operation_id: str) -> ContextManager[dict[str, object]]: ...
```

WorkflowService从server-owned operation/window owner journal构造sealed `_benchmark_v2_window_binding`；client payload若含该字段直接拒绝。Serialized闭集含operation ID、exact HWND、PID、process create-time、Job name/membership ref、screenshot/capture SHA、owner journal absolute path+content ref、expected UIA root HWND/owner PID、window class/title/client rect/DPI；payload是canonical JSON bytes + SHA-256，不携带parent内存对象。Windows `spawn` child在任何OCR/UIA/model读取前重新打开并hash journal，重验PID incarnation、Job membership、HWND root ownership、window geometry与screenshot SHA，然后仅在child process内调用`bind_window_by_handle(exact_hwnd)`，立即调用`uia_provider.snapshot_bound_window()`取得child-local snapshot，校验snapshot root HWND/owner PID仍与serialized seal exact一致后，才把该返回值安装进`pinned_uia_snapshot` context。`vision_observe_screen` adopted receipt必须含binding-payload SHA、capture SHA、UIA root HWND/owner PID与snapshot ref。

Cleanup evidence区分两条路径：正常return、Python exception、cooperative cancel及可执行Python unwinding的`BaseException`必须在child `finally`退出pinned context、清除process-local binding并写`normal_clear_receipt`；`TerminateProcess`、outer worker death、power/crash不会执行Python `finally`，不得伪造clear receipt。benchmark outer worker强杀时由mandatory amendment B1按sealed operation lineage终止exact child PID/create-time及Job descendants，关闭process/Job handles，并在Task4独立reconcile HWND；只有`stable_zero_processes=true`、`job_members=0`、handles closed、HWND absent均有OS observation时才能写`abnormal_cleanup_receipt`并接受缺失的normal clear，否则fail closed。Task7只验证这些journals，不重新签发cleanup truth。

- [ ] RED: parent-only in-memory binding在real spawned worker内得到`no_bound_window`；serialized canonical JSON在real spawned worker内安装成功且adopted receipt的payload SHA/capture SHA/UIA root HWND/owner PID等于owner seal；wrong PID/create-time/Job/HWND/capture/journal/payload SHA、ambient/multiple/stale binding在provider dispatch前FAIL；normal exit必须有normal clear；real强杀明确无finally receipt，后续只有mandatory amendment B1 exact outer-worker assignment/finalization receipt、B2 provider cleanup receipt与Task4 HWND reconciliation全部verified后可接受。
- [ ] Run RED: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_worker_binding.py`。
- [ ] GREEN: 新增versioned adapter，并给现有service/worker加入仅benchmark-v2 sealed payload可达的兼容hook；incumbent/nonbenchmark byte behavior tests保持不变。
- [ ] Run GREEN: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_window.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_worker_binding.py tests/test_learning_workflow_stage_worker.py -k "vision_observe_screen or benchmark_v2 or incumbent"`。

**Independent review:** 高风险review exact parent serialization→spawn payload→child re-attest→bind/pin→adopted receipt→finally clear链；输出`task-10b-slice-5-review.md`。

**No-action evidence:** child只安装read-only window/UIA context，不注入click、input、action或Runtime authority。

**Cleanup:** test harness自身在`finally`关闭WorkflowService operation与test window；正常child断言normal clear，强杀child断言没有伪造normal clear且必须由mandatory amendment B1 outer-worker cleanup、B2 provider cleanup与Task4 HWND reconciliation形成stable-zero receipts。Exact owned process/Event/file/Job handles逐一closed是primary proof；global handle count只作diagnostic。两路最终都要求child/descendants、HWND、listener、lease全部不存在。

**Commit:** `feat(benchmark-v2): bind spawned observation worker exactly`

---

### Task 6: Managed incumbent qwen-only cut-point

**Mandatory prerequisite:** 先执行并通过 `docs/superpowers/plans/2026-08-26-portfolio-hybrid-v1-1-task6-prerequisite-amendment.md` 的 Prerequisite A、B1、B2及各自独立review；本 Task按该文件的 Amendment C 执行。未满足前不得恢复Task 6 GREEN。

**Allowed files:**
- Create `app/learn/hybrid/benchmark_v2_incumbent_operation.py`
- Modify `app/learn/hybrid/benchmark_v2_provider_corpus.py` only to expose an opaque resolver over the already validated production corpus singleton; no corpus bytes/schema/partition change
- Modify `app/learn/workflow_service.py` only for durable benchmark mode, shared per-operation mutation lock/CAS guard, production singleton composition, guarded generic start/status/adopt/continue/cancel/heartbeat/finish/recover plus runtime attachment seam, and complete/cancel terminal cut-points
- Modify `app/api/panel.py` only so existing start/status/adopt/continue/cancel/heartbeat/finish/recover endpoints and read-only runtime attachment seam call guarded workflow-service functions; no route/model/response change and no direct Registry method call remains in endpoint bodies
- Create `tests/test_portfolio_hybrid_v1_1_benchmark_v2_incumbent.py`
- Modify `tests/test_learning_workflow_stage_execution.py` only for guarded dependency seam、八入口 byte/semantic compatibility与static no-direct-Registry assertions

**Interfaces:**

```python
class BenchmarkV2IncumbentWorkflowService(Protocol):
    def start_incumbent_observe(self, *, provider_case_ref: Mapping[str, object],
                                window_binding_ref: Mapping[str, object]) -> Mapping[str, object]: ...
    def poll_incumbent_observe(self, *, operation_ref: Mapping[str, object]) -> Mapping[str, object]: ...
    def adopt_and_terminalize_incumbent(self, *, operation_ref: Mapping[str, object],
                                       worker_ref: Mapping[str, object]) -> Mapping[str, object]: ...

# Defined in workflow_service.py; this is the only actual-mode composition root.
def get_production_benchmark_v2_workflow_service() -> BenchmarkV2IncumbentWorkflowService: ...

# Frozen in mandatory amendment B1; C may call only these B1 control interfaces.
BENCHMARK_WORKER_CONTROLLER_DEFAULT_TIMEOUT_MS: Final[int] = 5000

def hold_benchmark_worker_controller(
    *, supervision_root: BenchmarkWorkerSupervisionRoot,
    run_id: str, stage: str, operation_id: str,
    timeout_ms: int = BENCHMARK_WORKER_CONTROLLER_DEFAULT_TIMEOUT_MS,
) -> ContextManager[object]: ...

def launch_prepared_benchmark_worker(
    *, reservation_ref: Mapping[str, object],
    expected_operation_anchor: Mapping[str, object],
    authoritative_payload: Mapping[str, object],
    supervision_root: BenchmarkWorkerSupervisionRoot,
) -> dict[str, Any]: ...

def inspect_prepared_benchmark_worker_identity(
    *, run_id: str, stage: str, operation_id: str,
    supervision_root: BenchmarkWorkerSupervisionRoot,
) -> dict[str, Any]: ...

def confirm_prepared_benchmark_worker_anchor(
    *, reservation_ref: Mapping[str, object],
    expected_operation_anchor: Mapping[str, object],
    supervision_root: BenchmarkWorkerSupervisionRoot,
) -> dict[str, Any]: ...

def abort_prepared_benchmark_worker_before_anchor(
    *, reservation_ref: Mapping[str, object], run_id: str, stage: str,
    operation_id: str, workflow_revision: int,
    expected_operation_anchor: Mapping[str, object],
    reason: Literal["store_cas_lost", "cancelled", "stale"],
    supervision_root: BenchmarkWorkerSupervisionRoot,
) -> dict[str, Any]: ...
```

这是versioned benchmark-scoped internal public-service lifecycle，不新增HTTP/panel/action API。`get_production_benchmark_v2_workflow_service()`在`workflow_service.py`内lazy-bind现有production singletons `app.learn.workflow_store.learning_workflow_run_store`与`app.learn.workflow_worker.learning_stage_worker_registry`、B1 root-bound read-only store authority及由启动时已validate provider-corpus singleton生成的opaque case resolver；root getter必须exact绑定同一store singleton，不能暴露transition。Panel generic endpoints和benchmark façade必须使用这同一composition。Runner/`benchmark_v2_actual.py`只能取得façade并传closed `provider_case_ref={case_id,case_content_sha256}`，不能import、构造或传递Registry/store/case mapping，也不能创建平行composition。

Start在同一operation `RLock`和outer controller guard内先做active-operation/revision precheck，再由production resolver exact解析closed case ref，并由`benchmark_v2_incumbent_operation.py`按amendment冻结的literal `ObserveScreenTaskInput`规则（`provider_mode="local_understanding"`，沿现有managed observe path取得并绑定B2 exact Qwen lease）、validated corpus file/content、case content SHA及Task5 window/capture refs生成先于reservation的closed `benchmark_v2_incumbent_handler_payload_source_v1`；source的`predecessor_content_sha256`必须exact等于`provider_corpus_file_ref.content_sha256`，不得为file SHA、source parent或null；full source document/ref贯穿reservation、B1 anchor identity、expected/actual supervision及C durable operation。随后调用B1 `prepare_benchmark_worker_identity`原子封存closed source并reservation exact worker ID/nonce；crash在reservation后/anchor前时fresh service只能以B1 read-only `inspect_prepared_benchmark_worker_identity`恢复同一source，再由current resolver重验并重试CAS。然后以store expected-revision CAS持久化同一source、closed B1 operation anchor、reservation、parent-independent expected supervision、sealed mode与Task5 lineage。若pre-anchor CAS出现fresh可证明的revision conflict/cancel/stale，B1 root-bound getter在controller guard内先`LearningWorkflowRunStore.get`形成closed store decision，再取Registry lock决定abort；matching anchor存在必须拒绝abort并fresh confirm，相同revision/operation且anchor absent只能重试CAS。C只消费Registry receipt，不接收/自述store absence或zero spawn/provider。Anchor CAS成功后立即confirm `reserved→anchored`；Confirmation后才B2 zero-provider owner+第二CAS。随后fresh service从current store source document/ref→current production resolver取得same sealed case→literal projection+Task5 sealed capture path重建`authoritative_payload`，绝不读取caller/old service/client path/ref、B1 journal或raw payload artifact，再launch exact once。Launch在Registry lock内要求payload SHA exact等于source/reservation/anchor并重验source↔Task5 relation后才写`launching`。Store-anchor后/launch前restart必须丢弃caller及old Registry/service，再由current resolver重建，以同worker/nonce launch；raw case/payload不持久化。

Composition只持有production root/factory capability、exact root-bound只读store getter与opaque case resolver，绝不持有per-operation authority；test composition必须绑定同一test store/root/resolver，cross-store/corpus/root substitution FAIL。Actual supervision在launch时绑定当前Registry parent identity。跨进程owner exclusion由B1独立per-operation named mutex保证，不能只依赖process-local Registry/service locks；C在service RLock后取得opaque controller guard并从source/prepare之前跨store anchor CAS/confirmation、B2 owner CAS、必要abort、payload rebuild一直持有到launch/compensation durable。Abort exact lock order为`service RLock→controller mutex→store get/decision→Registry lock`；Registry lock内回调store立即拒绝。`BENCHMARK_WORKER_CONTROLLER_DEFAULT_TIMEOUT_MS=5000`，timeout exact exception+zero mutation；WAIT_ABANDONED fresh重验；same-thread recursion逐层release、outer close；pre/post-launch ReleaseMutex/CloseHandle failure按primary→release→close combined diagnostic并强制recovery_required/zero second spawn。完整start交错为`precheck→controller guard→resolver case ref→source compose→B1 identity prepare→store source+B1 anchor CAS/仅fresh closed decision允许的pre-anchor abort→B1 anchor confirmation→B2 owner prepare→store owner-ref CAS→fresh source/current-resolver authoritative payload rebuild→B1 launch→postcheck/compensation→guard release`；adopt严格`precheck→Registry`。现有generic worker start/status/adopt/`continue_learning_stage_worker_result`/cancel/heartbeat/finish/recover、specialized terminalizer、restart reconciler都必须先取得operation lock并从store读durable mode，不能相信caller payload。Panel八个入口与read-only runtime attachment seam只改内部调用到这些guarded functions；endpoint不得再直接调用Registry，nonbenchmark响应、call order/count/side effects保持byte/semantic不变。只有`workflow_service.py`的production composition持有Registry/store/root factory。

对benchmark mode，所有generic/specialized adopt或continue入口都调用同一个`_resume_benchmark_v2_incumbent_terminalization`，绝不进入`interpret_learning_stage_worker_result`、`_ensure_next_managed_stage_operation`或`_start_next_managed_stage_worker`；后二者也有defense-in-depth mode guard，发现该mode即fail closed。Complete状态机固定：①锁内调用 amendment A 的 Registry read-only inspection验证exact worker/result SHA，并要求Task5 binding ref、B1 worker cleanup ref与B2 Qwen cleanup ref可验证；②store expected-revision CAS写durable `terminal_intent`（含worker/result/cleanup refs）；③幂等Registry adopt/finalize exact result并要求SHA exact相等；④store CAS写唯一terminal `benchmark_v2_incumbent_observe_complete` receipt。Crash在①前重poll，①→②间无adopt，②→③间restart按intent adopt同一result，③→④间restart读取同一adopted receipt完成CAS，④后任何入口只返回byte-identical replay。

Guarded cancel使用互斥状态机：①同锁读取durable mode/revision；②仅在没有`terminal_intent`或terminal receipt时以CAS写`cancel_intent`（绑定operation anchor/reservation、可空PID-create-time/Job、model-request/acquisition-intent/runtime-owner与reason）；③调用exact Registry cancel，并只经 amendment B1/B2 production observers取得outer-worker与Qwen cleanup；④B1按launch state给出`verified_not_launched|verified_exact_worker_exited`，B2按lease state给出互斥`verified_not_acquired|verified_exact_process_exited`后CAS写唯一terminal `benchmark_v2_incumbent_cancelled` receipt。B2 not-acquired必须来自production aborted-acquisition owner/tombstone并证明无active lease、owned process/listener/Job；missing intent保持pending。`terminal_intent`与`cancel_intent`由同一expected-revision CAS竞争，恰一winner；loser不得覆盖winner、重复cancel/adopt或改变outcome，只返回winner最终receipt或`intent_pending`。Crash在pre-gate、post-gate/pre-acquire、acquire-intent、lease-acquired及其后各cut都只恢复同一owner/receipt，不能启动replacement worker/provider。Heartbeat也取得同一锁并读mode：只在纯`running`且无complete/cancel intent时按CAS续租同一operation；见任一intent或terminal receipt即拒绝且不得增加revision、覆盖evidence、重启worker或推进stage。任一intent/result/receipt漂移永久SAFE_STOP；complete/cancel/heartbeat任何路径都不能签发next worker或复活terminal operation。

完整task/provider multiset必须exact `{vision_observe_screen:1}` / `{qwen:1}`；任何`panel_learning_two_stage_understanding`、`panel_learning_calibration_sequence`、`panel_learning_model_review_repair`、VISTA owner或next-worker ref使arm FAIL。

- [ ] RED: 现有generic incumbent continuation负控会产生downstream worker；同一benchmark operation同时竞争panel generic start/status/adopt/continue/cancel/heartbeat/finish/recover八个入口，并在另一case加入specialized terminalizer，证明complete/cancel intent只有一个CAS winner、恰一terminal receipt、zero next worker/provider且heartbeat/finish/recover不能复活、覆盖winner或推进Hybrid。逐点覆盖resolver case ref→source→B1 prepare→anchor CAS conflict/cancel/stale→root-bound fresh store decision→public abort receipt、anchor CAS success→crash→fresh abort观察matching anchor并拒绝→anchor confirmation、B2 owner refs→丢弃caller/old Registry/service→current store source/current production resolver/Task5 authoritative payload rebuild→同worker/nonce launch，以及complete/cancel各crash cut；wrong corpus file/content、case ID/content、rules/source/default/capture/predecessor、provider_mode `qwen|local|local_grounding|api|null`、caller case mapping replay、client/journal payload、raw payload persistence、cross-store authority和C self-minted abort/store proof均FAIL。两个真实live Registry/controller竞争同operation：A在prepare返回后、store CAS前暂停仍持outer controller guard，B必须literal 5000ms timeout exact exception且zero mutation；abandoned helper、same-thread recursive exception、pre/post-launch ReleaseMutex/CloseHandle failure、Registry-lock→store callback分别验证fresh revalidation/combined diagnostics/recovery_required/no deadlock/no handle residue。Same-identity reminted A snapshot必须被store-anchored Task5/B1/B2 parents拒绝；第二store/Registry/root/resolver composition、panel direct Registry method call、stale revision、missing acquisition intent、cleanup failure fail closed；逐入口断言旧panel incumbent与Hybrid完整request/response、exact call order/count/side effects及continuation graph不变，start为precheck→Registry→postcheck/compensation，adopt为precheck→Registry。
- [ ] Run RED: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_incumbent.py`。
- [ ] GREEN: 依 mandatory amendment 的A/B证据实现durable mode、shared lock/CAS、single production composition、panel八入口与runtime attachment guarded wiring及recoverable complete/cancel/heartbeat/finish/recover state machine；generic incumbent/Hybrid行为保持原样。
- [ ] Run GREEN: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_incumbent.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_worker_binding.py tests/test_learning_workflow_stage_execution.py -k "incumbent or benchmark_v2 or hybrid"`。

**Independent review:** trace production singleton composition、start/status/adopt/continue/cancel/heartbeat/finish/recover、runtime attachment与specialized/restart入口的同锁mode guard、complete/cancel intents互斥CAS、Registry adopt/cancel、A/B cleanup journals、terminal各crash点与restart replay，并证明terminal不可被heartbeat/finish/recover/cancel复活且generic cascade不可达；输出`task-10b-slice-6-review.md`。

**No-action evidence:** operation只封存观察结果，不授权/执行下一stage、click或publish。

**Cleanup:** success/cancel/restart tests finally关闭single Qwen worker、lease、test window/service operation及B1 controller mutex handles；pre-anchor failures保留并验证Registry abort receipt。最终zero downstream workers/providers/processes/listeners/Job/Event/beacon/mutex handles。

**Commit:** `feat(benchmark-v2): terminalize incumbent after qwen observe`

---

### Task 7: Raw lifecycle, per-process VRAM, and probe receipts

**Allowed files:**
- Create `app/learn/hybrid/benchmark_v2_lifecycle.py`
- Create `tests/test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle.py`

**Interfaces:**

```python
def collect_raw_gpu_sample(*, device_uuid: str, transcript_path: Path) -> dict[str, object]: ...
def verify_lifecycle_from_raw(*, owner_journal_paths: list[Path], sampler_transcript_paths: list[Path],
                              probe_receipt_paths: list[Path], actual_mode: bool) -> dict[str, object]: ...
```

Production verifier只读Task4 window owner/finalization、Task5 binding normal-clear、mandatory amendment B1 outer-worker assignment/finalization、B2 Qwen cleanup sidecar与raw sampler transcripts；不接收caller-supplied observation mapping，不重新签发或复制worker/provider cleanup receipt。actual mode要求sealed production observer identity，fake/injected observer拒绝。Sampler保存下列命令的raw stdout/stderr/exit code/timestamp，并以OS observer补PID create-time：

```powershell
nvidia-smi --query-gpu=uuid,memory.used --format=csv,noheader,nounits
nvidia-smi --query-compute-apps=pid,gpu_uuid,used_gpu_memory --format=csv,noheader,nounits
```

External GPU fingerprint为非owned `(pid,create_time,gpu_uuid,memory)`集合；baseline/post窗口变化则`indeterminate`，不能填0。Owned VRAM按exact PID+create-time/device归属，device residual另报。Owner overlap从B1/B2/Task4 raw acquire/release intervals独立重算；这些receipts只是parents，Task7不得重签owner/cleanup truth。

Probe receipt必须绑定provider profile、request-in-flight journal、lease/socket/PID/create-time/Job、trigger timestamp、body-complete state、same-incarnation termination与stable-zero。未运行probe不能seal PASS。

- [ ] RED: forged observation、total VRAM巧合归零、external PID变化、PID reuse、overlap owner=2、missing probe、timeout body unknown冒充complete均FAIL。
- [ ] Run RED: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle.py`。
- [ ] GREEN: 实现raw parser/verifier，production mode无injection接口。
- [ ] Run GREEN: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle.py tests/test_learning_workflow_stage_worker.py -k "hybrid and (cleanup or cancel or timeout or provider)"`。

**Independent review:** 从raw transcript手工重建一条owner/VRAM/probe结论；输出`task-10b-slice-7-review.md`。

**No-action evidence:** collector只observe/seal；只回收exact owned incarnation，不宽泛kill。

**Cleanup:** test-owned helper绑定Job并在finally exact terminate/wait；zero process/window/listener/lease/handle。

**Commit:** `feat(benchmark-v2): verify raw provider lifecycle evidence`

---

### Task 8: WorkflowService-bound four-arm actual adapter

**Allowed files:**
- Create `app/learn/hybrid/benchmark_v2_actual.py`
- Create `tests/test_portfolio_hybrid_v1_1_benchmark_v2_actual.py`

**Interfaces:**

```python
class WorkflowServicePort(Protocol):
    def start_hybrid_operation(self, *, screen_group: Mapping[str, object], window_binding: Mapping[str, object]) -> Mapping[str, object]: ...
    def continue_hybrid_operation(self, *, operation_ref: Mapping[str, object]) -> Mapping[str, object]: ...
    def start_incumbent_observe(self, *, provider_case_ref: Mapping[str, object], window_binding: Mapping[str, object]) -> Mapping[str, object]: ...
    def poll_incumbent_observe(self, *, operation_ref: Mapping[str, object]) -> Mapping[str, object]: ...
    def adopt_and_terminalize_incumbent(self, *, operation_ref: Mapping[str, object], worker_ref: Mapping[str, object]) -> Mapping[str, object]: ...
    def cancel_operation(self, *, operation_ref: Mapping[str, object]) -> Mapping[str, object]: ...

def run_screen_group(*, provider_group: Mapping[str, object], service: WorkflowServicePort,
                     window_owner: object, lifecycle: object, prediction_sink: object) -> dict[str, object]: ...
```

Production port仅包装现有WorkflowService public functions与Task6 `get_production_benchmark_v2_workflow_service()`返回的façade。Hybrid由service决定next stage/payload/predecessor/revision，benchmark不得选择task kind；每screen group启动一个cascade并从server-adopted receipts投影三臂，五target引用同一Omni/Qwen/fusion/VISTA/capture/window/UIA refs。Incumbent每target调用同一production façade的start→poll→adopt-and-atomic-terminalize；即使并发generic continue/adopt/cancel/heartbeat出现，也只能命中Task6同锁complete/cancel/heartbeat guards，绝不进入generic cascade或复活terminal。Registry/store只存在于WorkflowService production composition内部。

- [ ] RED: AST拒绝Registry/store/handler imports或第二composition；fake public service验证benchmark无法跳stage；stale operation/revision/predecessor拒绝；duplicate poll/adopt/continue幂等；screen group只有1次Hybrid cascade；incumbent最多5次single-worker operations且完整multiset无任何downstream task/provider。
- [ ] Run RED: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_actual.py`。
- [ ] GREEN: 实现service-bound adapter和projection extractor，不复制orchestration logic。
- [ ] Run GREEN: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_actual.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_worker_binding.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_incumbent.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle.py`。

**Independent review:** 分别trace Hybrid public continuation链与incumbent single-worker atomic cut-point/restart adoption；输出`task-10b-slice-8-review.md`。

**No-action evidence:** public operations限定observe/learn/calibration/review；无action API或click。

**Cleanup:** 每screen group finally先service cancel/reconcile，再window close与lifecycle stable-zero；fake service active ops/workers/windows/listeners/leases全部空。

**Commit:** `feat(benchmark-v2): run arms through workflow service`

---

### Task 9: Runner and executable regression-only lifecycle probes

**Allowed files:**
- Create `scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py`
- Create `tests/test_portfolio_hybrid_v1_1_benchmark_v2_runner.py`

Runner只接收`--provider-manifest`；不得接收private manifest/project root/Gold path。每次actual dispatch前re-attest provider child、window binding、service operation、lease/profile/socket/PID/create-time。Regression attempt ledger在第一个provider call前append+fsync并为每次run分配唯一attempt directory；output缺失仍可从ledger cleanup。通过独立review的attempt另写immutable `accepted-run-ref.json`，不覆盖旧run。

**Exact CLI:**

```powershell
uv run python scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py --provider-manifest tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-provider-manifest.json --partition regression --dry-run --output runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/dry-run.json
uv run python scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py --provider-manifest tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-provider-manifest.json --partition regression --actual-models --attempt-ledger runtime_state/portfolio-hybrid-v1-1/benchmark-v2-ledger/regression/events.jsonl --output-root runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/attempts
uv run python scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py --provider-manifest tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-provider-manifest.json --partition regression --run-cancel-probe --providers omni,qwen,vista --attempt-ledger runtime_state/portfolio-hybrid-v1-1/benchmark-v2-ledger/regression/cancel-probes.jsonl --output-root runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/cancel-probes
uv run python scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py --provider-manifest tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-provider-manifest.json --partition regression --run-timeout-probe --providers omni,qwen,vista --attempt-ledger runtime_state/portfolio-hybrid-v1-1/benchmark-v2-ledger/regression/timeout-probes.jsonl --output-root runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/timeout-probes
uv run python scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py --cleanup-open-attempts --partition regression --ledger-root runtime_state/portfolio-hybrid-v1-1/benchmark-v2-ledger --output-root runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression
```

Probe必须等待server journal=`request_in_flight`后触发，逐provider串行，保存same-incarnation/body-complete/stable-zero receipt；holdout parser拒绝probe flags。

- [ ] RED: CLI matrix、private input拒绝、fake actual forbidden、probe未in-flight拒绝、multiple regression attempts preserved、output不存在cleanup、holdout probe拒绝。
- [ ] Run RED: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_runner.py`。
- [ ] GREEN: 接Task3-8，不新增HTTP/panel/action route。
- [ ] Run GREEN: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_runner.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_actual.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_holdout.py && uv run python -m py_compile scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py`。

**Independent review:** 核对runner输入域、probe可执行性、append-only attempt ledger与cleanup recovery；输出`task-10b-slice-9-review.md`。

**No-action evidence:** 只有test-owned noninteractive window和provider calls；无真实GUI action。

**Cleanup:** unit fake resources finally zero。Actual/probe任何退出都按attempt journal关闭WorkflowService ops、test HWND、Job/provider processes/listeners/leases。

**Commit:** `feat(benchmark-v2): add service-bound benchmark runner`

---

### Task 10: Split private/provider seal

**Allowed files:**
- Create `scripts/seal_portfolio_hybrid_v1_1_benchmark_v2.py`
- Create `tests/test_portfolio_hybrid_v1_1_benchmark_v2_seal.py`

Sealer生成两个闭集：private root含v1 hash/path、private scorer hash和provider child hash；provider manifest只含provider corpus ref、四臂、estimand/gate provider-safe projection、profiles/budgets/context/order、runner/service/window/worker-binding/incumbent-cut-point/lifecycle/durable-claim code hashes与no-action policy，不含private path。两seal都携带stable `benchmark_release_id`、frozen corpus-parent seal与literal holdout partition identity；provider manifest SHA只供Task14唯一authorization payload绑定，绝不参与Task3 claim namespace。Final seal必须包含Task0-12所有新增/修改代码、scripts、config hashes；本slice只实现tool，Task13才生成real fixtures。

- [ ] RED: 任一v1/image/v2 hash、四臂/order/metric/window/probe/CAS policy漂移FAIL；provider manifest private path/key leak FAIL；missing later artifact FAIL。
- [ ] Run RED: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_seal.py`。
- [ ] GREEN: 实现canonical split seal与verify；无allow-missing production flag。
- [ ] Run GREEN: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_seal.py && uv run python -m py_compile scripts/seal_portfolio_hybrid_v1_1_benchmark_v2.py`。

**Independent review:** 只用temp fixtures核对split boundary和hash closure；输出`task-10b-slice-10-review.md`。

**No-action evidence:** 两seal均non-authorizing；provider manifest无publish/action。

**Cleanup:** temp seals删除；无UI/service/process。

**Commit:** `feat(benchmark-v2): seal split private and provider manifests`

---

### Task 11: Leakage review and holdout authorization

**Allowed files:**
- Create `scripts/review_portfolio_hybrid_v1_1_benchmark_v2_leakage.py`
- Create `scripts/authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py`
- Create `tests/test_portfolio_hybrid_v1_1_benchmark_v2_leakage.py`

Leakage scanner只读provider manifest/corpus/request projections、regression public refs和seal metadata。本slice实现但不实际执行authorization：authorizer要求regression score/gate/lifecycle/probes PASS；holdout subledger exact genesis/0 claim；固定claim namespace下无任何`{claim_id}--*.claim`且registry key absent；regression subledger可有任意合法events。Authorizer固定stable release/corpus/partition claim ID，并把absolute ledger identity、unique authorization path、provider manifest/version、code/config/profile hashes、四臂顺序与exact holdout command/run order写入canonical authorization payload。它计算payload SHA，构造不含自身hash的envelope，再把envelope SHA写入独立ref；以`CREATE_NEW`创建固定authorization object与holdout genesis，runner不得initialize或覆盖。

- [ ] RED: nested private field、private path、cross partition、changed provider/version/profile/prompt/threshold/run order、missing probe、regression events误判、任一holdout claim anchor已consumed均拒绝；provider manifest变化不得产生新claim ID；existing different authorization使release invalid；payload/envelope hash无自引用。
- [ ] Run RED: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_leakage.py`。
- [ ] GREEN: 实现scanner与dual-anchor/genesis authorization。
- [ ] Run GREEN: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_leakage.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_holdout.py && uv run python -m py_compile scripts/review_portfolio_hybrid_v1_1_benchmark_v2_leakage.py scripts/authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py`。

**Independent review:** reviewer身份不得是实现者；不读取Gold；输出`task-10b-slice-11-review.md`。

**No-action evidence:** authorization scope=`benchmark_provider_calls_only`且`artifact_is_action_authorization=false`。

**Cleanup:** 不启动provider/UI；本slice测试只用test roots。实际unique authorization只在Task14生成；失败artifacts保留审计，production authorization/claim anchors/genesis没有delete/reset接口。

**Commit:** `feat(benchmark-v2): authorize one sealed holdout attempt`

---

### Task 12: Public report assembler and release tests

**Allowed files:**
- Create `scripts/assemble_portfolio_hybrid_v1_1_benchmark_v2_report.py`
- Create `tests/test_portfolio_hybrid_v1_1_release_gate_v2.py`

Assembler只join sealed public score refs/run refs/lifecycle/probe/window cleanup/ledger/dual-anchor refs；不import private scorer，不读取Gold，不执行模型。缺四臂screen-group matrix、same-parent VISTA pair、submitted denominator、test HWND closed、spawned worker binding verification、incumbent mode-guard/atomic-terminal verification、probe receipts、single durable claim或cleanup任一项即FAIL。Public report必须显式列`local_one_shot_threat_model`与`external_append_only_witness_present=false` limitation，不得把本地双锚描述成可抵抗同一管理员删除全部状态。

Release-gate dependency manifest必须按exact DAG列出Task5、A、B1、B2、C/Task6的独立PASS result refs与reviews：`task-10b-slice-5-review.md`、`task-10b-slice-6-prerequisite-a-review.md`、`task-10b-slice-6-prerequisite-b1-review.md`、`task-10b-slice-6-prerequisite-b2-review.md`、`task-10b-slice-6-review.md`。同时seal production source SHA：`benchmark_v2_worker_binding.py,workflow_worker.py,windows_process_scope.py,model_server.py,benchmark_v2_provider_corpus.py,benchmark_v2_incumbent_operation.py,workflow_service.py,panel.py`；以及load-bearing test SHA/result refs：`test_portfolio_hybrid_v1_1_benchmark_v2_worker_binding.py,test_learning_workflow_stage_worker.py,test_learn_hybrid_windows_process_scope.py,test_model_request_cancellation.py,test_portfolio_hybrid_v1_1_benchmark_v2_incumbent.py,test_learning_workflow_stage_execution.py`。B1 direct ref必须覆盖source-bound reservation/read-only pre-anchor inspection→store anchor→anchor confirmation→fresh current-resolver authoritative-payload launch、root-bound store decision public pre-anchor abort三reason/replay/matching-anchor reject、two-controller 5000ms timeout、abandoned/recursive/release-close named-mutex controls、same-live receipt retry、dead-supervisor inference及raw handle observations；C direct ref另覆盖validated corpus resolver/source projection、sealed `local_understanding` managed-Qwen path、predecessor=corpus-content公式与wrong corpus/case/rules/mode/predecessor/capture/restart negatives；B2 direct ref必须覆盖not-acquired/exact-exited disjoint outcomes；C ref必须覆盖start/adopt call order、CAS-lost只消费B1 abort receipt和combined remint rejection。缺失、非PASS、review有未关闭Critical/Important或任一SHA与final seal不一致均FAIL；C broad E2E不能替代A/B direct result refs。上述闭合只扩展C对既有`benchmark_v2_provider_corpus.py`的窄resolver allowlist，不新增额外B1/C production或test文件；Task12 inventory必须含该source SHA。

- [ ] RED: automatic fail被human掩盖、screen group重复cascade、successful-only point、zero submitted、ambient HWND、external GPU drift、missing probe、deleted ledger但任一claim anchor consumed、private leak均FAIL。
- [ ] Run RED: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_release_gate_v2.py`。
- [ ] GREEN: 实现闭集assembler；threshold仅来自sealed gate。
- [ ] Run GREEN: `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_estimand.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_isolation.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_scoring.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_holdout.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_window.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_worker_binding.py tests/test_learning_workflow_stage_worker.py tests/test_learn_hybrid_windows_process_scope.py tests/test_model_request_cancellation.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_incumbent.py tests/test_learning_workflow_stage_execution.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_actual.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_runner.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_seal.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_leakage.py tests/test_portfolio_hybrid_v1_1_release_gate_v2.py`。Task12 reviewer必须消费该exact command的真实result ref，并核对A/B selectors独立PASS refs，不能以Final deterministic command将来会运行或C broad E2E替代。

**Independent review:** public/private、metric、window、worker binding、incumbent cut-point、lifecycle、dual-anchor闭集；输出`task-10b-slice-12-review.md`。

**No-action evidence:** final report即使PASS也不是Runtime/action/publish authority。

**Cleanup:** deterministic tests finally关闭所有test window/helper/private scorer/fake service；zero HWND/process/listener/lease/handle。

**Commit:** `feat(benchmark-v2): assemble non-authorizing release report`

---

### Task 13: Final seal, actual regression, and real probes

**Allowed writes:** 新建三个sealed fixtures；其后只写`runtime_state/.../benchmark-v2/regression/`、regression subledger和review report。

- [ ] 生成provider child candidate：

```powershell
uv run python scripts/project_portfolio_hybrid_v1_1_provider_corpus_v2.py --parent-manifest tests/fixtures/portfolio_hybrid_v1_1/corpus-manifest.v1.json --output runtime_state/portfolio-hybrid-v1-1/benchmark-v2/provider-corpus.candidate.json
uv run python scripts/seal_portfolio_hybrid_v1_1_benchmark_v2.py --template tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-manifest.template.json --provider-corpus runtime_state/portfolio-hybrid-v1-1/benchmark-v2/provider-corpus.candidate.json --output-private runtime_state/portfolio-hybrid-v1-1/benchmark-v2/private-manifest.candidate.json --output-provider runtime_state/portfolio-hybrid-v1-1/benchmark-v2/provider-manifest.candidate.json
```

- [ ] 独立review三candidate无Gold leak且hash闭集后，byte-copy为`provider-corpus.v2.json`、`benchmark-v2-private-manifest.json`、`benchmark-v2-provider-manifest.json`，verify并commit：`chore(benchmark-v2): seal immutable benchmark manifests`。
- [ ] Run dry-run与actual regression，依次执行Task9前两条exact commands。
- [ ] Run真实cancel probes和timeout probes，依次执行Task9第三、第四条exact commands；每个provider必须已有request-in-flight再触发。
- [ ] 按Task0 policy把同一seal下第一个完整且lifecycle verified的regression attempt封存为`runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/accepted-run-ref.json`；不得从多个完整attempt择优，旧attempt与events保持append-only。
- [ ] 运行private regression scorer：

```powershell
uv run python scripts/score_portfolio_hybrid_v1_1_benchmark_v2_private.py --private-manifest tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-private-manifest.json --prediction-run-ref runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/accepted-run-ref.json --private-output runtime_state/portfolio-hybrid-v1-1/benchmark-v2/private/regression-score.json --public-ref-output runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/score-ref.json
```

**Independent review:** 四臂、12 screens/60 targets、Hybrid每screen一次、test HWND exact/closed、raw VRAM、六probe receipts、zero residue；输出`task-10b-regression-review.md`。失败只能修code→新seal→重跑regression；不得调threshold。

**No-action evidence:** 只有test-owned noninteractive UI；无真实click/fill/action/publish。

**Cleanup:** 正常路径每screen finally关闭service/provider/window；强杀/outer death不声称执行child finally，改由mandatory amendment B1 outer-worker cleanup + B2 Qwen cleanup + Task4 HWND reconciliation形成OS stable-zero receipts，Task7只消费验证。结束运行Task9的`--cleanup-open-attempts` exact command并验证zero HWND/process/descendant/listener/lease/handle；失败BLOCK。

**Commit:** 只commit三个sealed fixtures；runtime/review outputs不commit。

---

### Task 14: Independent leakage review and holdout genesis authorization

**Allowed writes:** leakage report、固定路径unique authorization object、external authorization ref、holdout genesis/CAS precondition metadata；不改sealed files。

```powershell
uv run python scripts/review_portfolio_hybrid_v1_1_benchmark_v2_leakage.py --provider-manifest tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-provider-manifest.json --regression-run-ref runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/accepted-run-ref.json --output runtime_state/portfolio-hybrid-v1-1/benchmark-v2/leakage-review.json
uv run python scripts/authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py --private-manifest tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-private-manifest.json --provider-manifest tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-provider-manifest.json --regression-run-ref runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/accepted-run-ref.json --score-ref runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/score-ref.json --leakage-review runtime_state/portfolio-hybrid-v1-1/benchmark-v2/leakage-review.json --ledger-root runtime_state/portfolio-hybrid-v1-1/benchmark-v2-ledger --output runtime_state/portfolio-hybrid-v1-1/benchmark-v2/holdout-authorization.json
```

该命令只能为stable claim ID执行一次：先计算canonical payload SHA，再计算不含自身hash的envelope SHA；`--output`只写`{authorization_id,envelope_sha256,fixed_authorization_path}`外部ref，完整envelope用`CREATE_NEW`写Task3固定authorization path。任何existing object/ref byte mismatch、provider/version/run-order变化或重复authorization均使本release永久invalid，不得删除重建或换provider manifest获得新claim key。

**Independent review:** reviewer不读Gold，确认regression chain合法非空、holdout chain exact genesis/0 claim、stable claim namespace下全部sentinel/registry均absent、unique authorization two-layer hashes、provider/version/run-order frozen、exact command hash与cleanup recovery identity；输出`task-10b-slice-14-review.md`。

**No-action evidence:** authorization只给provider benchmark调用。

**Cleanup:** 本slice无UI/provider。Genesis/CAS metadata不可删；失败报告保留。

**Commit:** 无commit。

---

### Task 15: Unique holdout invocation

**Allowed writes:** holdout dual-anchor consumed record、holdout JSONL mirror、claim-derived attempt directory/run/lifecycle outputs；不改repo。

执行一次且仅一次：

```powershell
uv run python scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py --provider-manifest tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-provider-manifest.json --partition holdout --actual-models --holdout-authorization runtime_state/portfolio-hybrid-v1-1/benchmark-v2/holdout-authorization.json --ledger-root runtime_state/portfolio-hybrid-v1-1/benchmark-v2-ledger --output-root runtime_state/portfolio-hybrid-v1-1/benchmark-v2/holdout
```

两个consumed anchors都必须先于第一个provider call。Crash前未生成run/attempt mirror时，cleanup从authorization中的claim identity与现存anchor恢复exact attempt/owner journals：

```powershell
uv run python scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py --cleanup-only --holdout-authorization runtime_state/portfolio-hybrid-v1-1/benchmark-v2/holdout-authorization.json --ledger-root runtime_state/portfolio-hybrid-v1-1/benchmark-v2-ledger
```

**Independent review:** file/registry anchors与unique authorization exact一致且只对应stable release namespace中的一个consumed attempt、双锚不一致永久拒绝、mirror最多一claim、started request有terminal/unknown、无第二attempt、每screen test HWND已关闭；成功时从anchors/ledger封存exact `runtime_state/portfolio-hybrid-v1-1/benchmark-v2/holdout/run-ref.json`，不依赖固定run filename；输出`task-10b-holdout-review.md`。

**No-action evidence:** test-owned window仅显示图片；无action/click/publish。

**Cleanup:** 只运行上述claim-bound cleanup；不得删ledger/output/claim anchors或redispatch。Zero window/process/descendant/listener/lease/handle，否则release FAIL。

**Commit:** 无commit。

---

### Task 16: Private holdout scoring and final public report

**Allowed writes:** private holdout score、public score ref、final report与final review。

```powershell
uv run python scripts/score_portfolio_hybrid_v1_1_benchmark_v2_private.py --private-manifest tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-private-manifest.json --prediction-run-ref runtime_state/portfolio-hybrid-v1-1/benchmark-v2/holdout/run-ref.json --private-output runtime_state/portfolio-hybrid-v1-1/benchmark-v2/private/holdout-score.json --public-ref-output runtime_state/portfolio-hybrid-v1-1/benchmark-v2/holdout/score-ref.json
uv run python scripts/assemble_portfolio_hybrid_v1_1_benchmark_v2_report.py --provider-manifest tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-provider-manifest.json --regression-run-ref runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/accepted-run-ref.json --holdout-run-ref runtime_state/portfolio-hybrid-v1-1/benchmark-v2/holdout/run-ref.json --regression-score-ref runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/score-ref.json --holdout-score-ref runtime_state/portfolio-hybrid-v1-1/benchmark-v2/holdout/score-ref.json --leakage-review runtime_state/portfolio-hybrid-v1-1/benchmark-v2/leakage-review.json --ledger-root runtime_state/portfolio-hybrid-v1-1/benchmark-v2-ledger --output runtime_state/portfolio-hybrid-v1-1/benchmark-v2/final-report.json
```

任一gate失败即`promotion_eligible=false`；不得改阈值、用post-review掩盖、删除claim anchors/ledger或重跑holdout。未来实验必须新version和字节不同的新holdout。Final report保留“同一管理员可恶意删除全部本地state，强不可抵赖需外部append-only witness”的release limitation；本地PASS不消除该限制。

**Independent review:** 只读public report、sealed refs、private score hash、dual-anchor/cleanup proof；不读Gold；输出`task-10b-final-review.md`。

**No-action evidence:** final PASS不是Runtime/action/publish授权。

**Cleanup:** 关闭private scorer、文件句柄；最终zero test HWND/provider/helper/descendant/listener/lease/handle及VRAM结论非indeterminate。Evidence保留。

**Commit:** 无commit。

## Final deterministic verification before actual runs

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_estimand.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_isolation.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_scoring.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_holdout.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_window.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_worker_binding.py tests/test_learning_workflow_stage_worker.py tests/test_learn_hybrid_windows_process_scope.py tests/test_model_request_cancellation.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_incumbent.py tests/test_learning_workflow_stage_execution.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_actual.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_runner.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_seal.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_leakage.py tests/test_portfolio_hybrid_v1_1_release_gate_v2.py
uv run pytest -q tests/test_learning_workflow_stage_worker.py -k "completed_result_identity or benchmark_worker or prepared_benchmark_worker or handler_payload_source or payload_projection or managed_qwen_mode or authoritative_payload or store_anchor_decision or pre_anchor_abort or benchmark_provider_cleanup"
uv run pytest -q tests/test_learn_hybrid_windows_process_scope.py -k "benchmark_worker or exact_process_identity_to_scope or controller_mutex or controller_cleanup_failure or handle_close_observation"
uv run pytest -q tests/test_model_request_cancellation.py -k "qwen_cleanup_sidecar or benchmark_provider_cleanup or verified_not_acquired"
uv run python -m py_compile app/learn/workflow_worker.py app/learn/hybrid/windows_process_scope.py app/core/model_server.py app/learn/workflow_service.py app/api/panel.py app/learn/hybrid/benchmark_v2_contracts.py app/learn/hybrid/benchmark_v2_privileged_projector.py app/learn/hybrid/benchmark_v2_provider_corpus.py app/learn/hybrid/benchmark_v2_provider_sandbox.py app/learn/hybrid/benchmark_v2_predictions.py app/learn/hybrid/benchmark_scorer_v2.py app/learn/hybrid/benchmark_v2_holdout.py app/learn/hybrid/benchmark_v2_durable_claim.py app/learn/hybrid/benchmark_v2_window_owner.py app/learn/hybrid/benchmark_v2_worker_binding.py app/learn/hybrid/benchmark_v2_incumbent_operation.py app/learn/hybrid/benchmark_v2_lifecycle.py app/learn/hybrid/benchmark_v2_actual.py scripts/project_portfolio_hybrid_v1_1_provider_corpus_v2.py scripts/score_portfolio_hybrid_v1_1_benchmark_v2_private.py scripts/portfolio_hybrid_v1_1_test_window_v2.py scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py scripts/seal_portfolio_hybrid_v1_1_benchmark_v2.py scripts/review_portfolio_hybrid_v1_1_benchmark_v2_leakage.py scripts/authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py scripts/assemble_portfolio_hybrid_v1_1_benchmark_v2_report.py
git diff --check
```

不得运行forbidden test。Deterministic PASS、final seal、actual regression/probes、independent leakage PASS只是holdout前置条件；唯一holdout、private gate与final cleanup全部满足后才能PASS。

## Round 4 closure matrix

| Finding | Disposition | Exact plan closure |
|---|---|---|
| C1 unsupported extra arm / incumbent refinement | CLOSED | Global constraints和Task0固定四臂；旧incumbent-refinement slice与第二套point gain已移除，当前Task3改为ledger；Task0只比较同一Hybrid fusion/candidate/capture parent。 |
| C2 ambient UIA / missing spawned-child binding | CLOSED | Task4创建并seal exact test-owned HWND/PID/create-time/Job/screenshot/capture/UIA owner journal；Task5把完整binding序列化进server-owned worker payload，spawn child在任何OCR/UIA/model前重开并校验journal、PID incarnation、Job、HWND、geometry与SHA，再在child内安装exact bound window/pinned UIA，adopted receipt回传exact UIA root；parent-only binding、ambient/missing/stale/multiple均为负控。正常unwind必须finally clear；强杀只由mandatory amendment B1 outer-worker assignment/finalization、B2 provider cleanup与Task4 HWND receipts证明，不伪造finally receipt。 |
| C3 Gold boundary only depended on a purpose string | CLOSED | Task1拆privileged projector、provider-only validator、独立process/file inputs；Task2/Task16使用private scorer subprocess；runner只接收provider manifest。 |
| C4 direct Registry / contaminated incumbent orchestration | CLOSED | Mandatory amendment A/B先补Registry read-only result identity、B1 reservation→store anchor→launch/Job/gate/raw-handle journals与B2 production acquired/not-acquired cleanup journals；Task6再把durable `learning_pipeline_mode=benchmark_v2_incumbent_single_observe`写入现有store。specialized/restart与panel generic start/status/adopt/continue/cancel/heartbeat/finish/recover八入口及runtime attachment seam共用同一operation mutation lock、store revision CAS与mode guard，endpoint不再直接调用Registry，`_ensure_next...`/`_start_next...`另有fail-closed guard。唯一production composition绑定现有store/Registry singletons及root factory而非per-operation authority。Complete `terminal_intent`与`cancel_intent`同revision互斥；winner按crash-safe Registry adopt或cancel→B1/B2 cleanup→terminal路径恢复，loser只重放同一receipt。Heartbeat只可续租无intent的running operation，不能覆盖intent、复活terminal或推进Hybrid；八入口并发/逐点重启测试证明zero next worker/provider。 |
| C5 deletable ledger and regression/genesis contradiction | CLOSED within stated local threat model | Task0/3固定namespace=`benchmark_release_id + frozen corpus-parent seal + partition=holdout`，provider manifest不能开新key；Task14唯一authorization冻结provider/version/code/profile/arm order/command/run order，变化使release invalid。Authorization与claim都用payload SHA→non-self-referential envelope SHA两层，zero sentinel filename绑定authorization ref；single-anchor loss只允许同attempt cleanup，双锚不一致永久拒绝。明确承认同一管理员可恶意删除全部本地state；更强不可抵赖需外部append-only witness，并作为release limitation而非伪称物理不可删。 |
| C6 self-reported lifecycle / missing probes | CLOSED | Task7只从server journals/raw transcripts重建per-process/device VRAM；Task9给出真实cancel/timeout probe CLI，Task13执行并独立review receipts。 |
| I1 under-specified point metric / zero subset | CLOSED | Task0固定唯一行键`(case_id,target_id,arm_id,candidate_id,vista_request_ref)`及同pair两arm约束；每target在VISTA前seal唯一candidate与ELIGIBLE/INELIGIBLE，ELIGIBLE恰一same-candidate SUBMITTED request，duplicate/missing/ambiguous/unsent/cross-target/cross-request均FAIL；Task2 scorer不得择优，并保留half-open、exact rational、失败入denominator和`min_vista_submitted_count=1`。 |
| I2 dependency order | CLOSED | Exact DAG为Task0 estimand→Task1 isolation→Task2 predictions/scoring→Task3 durable claim→Task4 window owner→Task5 spawned binding→Prerequisite A Registry snapshot→B1 outer-worker supervision→B2 Qwen cleanup sidecar→C/Task6 incumbent cut-point→Task7 lifecycle journal verifier→Task8 actual adapter→Task9 runner/probes→Task10 seal tool→Task11 leakage/authorization code→Task12 report/dependency manifest→Task13 final seal/regression→Task14 independent authorization→Task15 holdout→Task16 final scoring/report。任何A/B/C review或direct result ref缺失都阻止Task7及以后。 |
| I3 per-target repeated Hybrid cascade | CLOSED | Global constraints与Task8固定每screen group一次Hybrid cascade；同屏target共享parents，同时报告unique和amortized calls。 |
| Round3 I1 Task12 omitted load-bearing tests | CLOSED | Task12 GREEN与final deterministic commands加入Task5、A、B1、B2、C direct modules/selectors；release dependency manifest必须消费五份独立reviews、production/test source SHA与真实PASS refs，C broad E2E不能替代A/B results。 |
| Round3 I2 forced termination was attributed to child finally | CLOSED | Task5/Task13区分normal clear与强杀：`TerminateProcess`/outer death预期无finally receipt；benchmark outer worker只接受mandatory amendment B1 exact Job/PID/create-time stable-zero与handles closed、B2 provider cleanup及Task4 HWND absent的production receipts，Task7只消费并验证这些journals。 |
| Round4 Important cancel/heartbeat bypassed the mutation authority | CLOSED | Global/Task6/amendment allowlist覆盖panel完整start/status/adopt/continue/cancel/heartbeat/finish/recover与runtime attachment seam；workflow service定义同锁durable-mode guards、cancel intent状态机、heartbeat CAS规则及八入口竞争和cancel crash/restart测试，同时保持所有非benchmark endpoint bytes/semantics不变。 |
| Amendment C1 KILL_ON_CLOSE Job absent after parent death | CLOSED | B1在gate前durable写`assignment_proven`，在最后owner handle close前写`cleanup_finalization_intent`；fresh Registry严格区分Job可重开、validated intent+raw close observations的same-live-supervisor retry、fresh exact supervisor absence的dead-supervisor inference、pre-assignment recovery-required四分支。真实outer-parent termination及每个close/receipt atomic stage覆盖assignment/gate/stable-zero/Job-close/receipt-replace cuts，journal state或absence永不单独升级。 |
| Amendment I1 A claimed unanchored semantic remint detection | CLOSED | A只证明Registry lock内同一次validated envelope的exact-byte snapshot和no-adoption side effect；same-identity remint不由A判定，必须在C由Task5+B1+B2独立parents拒绝。首次读取前immutability若需要，必须另增parent anchor并重审。 |
| Amendment I2 worker Job authority/name under-specified | CLOSED | B1冻结expected/actual supervision、closed operation anchor、production/test disjoint root capability、prepare reservation→store expected supervision→authoritative-payload launch协议、execution nonce、worker scope及controller mutex name公式；composition不持有per-operation authority，fresh observer从store anchor验证expected supervision，outer-worker/controller/provider grammars互不相容。 |
| Amendment I4 wrappers/durable schema under-specified | CLOSED | C冻结single composition/root test-pair injection、九个wrapper完整signature/return/exception contracts、operation/intents/terminal receipt schemas、transition table及八入口APIResponse/error precedence/call-count/side-effect matrix；start严格precheck→Registry→postcheck/compensation，adopt严格precheck→Registry。 |
| Amendment Round2 cancel before Qwen lease | CLOSED | B2复用production aborted-acquisition owner/tombstone签互斥`verified_not_acquired`，acquired owner只签`verified_exact_process_exited`；C cancelled接受与launch/lease state匹配的B1/B2组合，missing acquisition intent保持pending，fresh crash matrix覆盖pre-gate、post-gate/pre-acquire、acquire-intent和lease-acquired。 |
| B1 preflight C1 restart payload unavailable | CLOSED in plan | C先由validated provider-corpus singleton resolver、closed case ref、literal projection rules和Task5 refs生成`benchmark_v2_incumbent_handler_payload_source_v1`；full source/ref原子封存在reservation，read-only inspection恢复pre-anchor crash，再贯穿anchor identity/expected+actual supervision/C document。Projection唯一mode为production已支持并取得managed Qwen lease的`local_understanding`；rules/source/payload SHA随该literal计算，`qwen|local|local_grounding|api|null`替换FAIL。Source predecessor唯一等于provider corpus content SHA，file SHA/source parent/null FAIL。Fresh restart丢弃caller/old service，经current store source→current production resolver→sealed case→exact projection重建authoritative mapping；wrong corpus/case/rules/source/mode/predecessor/capture及raw/caller replay zero spawn。 |
| B1 preflight C2 missing pre-anchor abort authority | CLOSED in plan | B1 root持不可序列化、root-bound只读production/test store authority，lazy-bindexact `LearningWorkflowRunStore.get`；abort按controller→fresh store decision→Registry lock，只在matching anchor absent且fresh conflict/cancel/stale predicate成立时转`reserved→aborted_before_anchor`并把decision ref纳入receipt。Matching anchor存在拒绝后fresh confirm；same revision/op absent只重试CAS；caller/C state mapping不能自证。 |
| B1 preflight cross-process owner concurrency | CLOSED in plan | 独立per-operation production/test named mutex包围全部B1 prepare/launch/abort/Job reopen/cleanup observer；default timeout固定5000ms，WAIT_TIMEOUT/ABANDONED、same-thread recursion、ReleaseMutex/CloseHandle pre/post-mutation precedence、combined diagnostics/recovery_required及真实dual/abandoned helper RED冻结；lock order为service→controller→store read→Registry，Registry-lock→store拒绝。 |
| B1 round-2 provider literal/predecessor | CLOSED in plan; pending round-3 review | `provider_mode`由无效`qwen`机械改为existing managed-Qwen `local_understanding`，rules/source/payload SHA与selectors同步；source predecessor exact固定为provider corpus content SHA，wrong/null alternatives均为负控。 |
