# Portfolio Hybrid v1.1 Task 6 Prerequisite Amendment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不提前运行 actual/provider/holdout/action、不中断 Registry identity boundary、也不伪造 lifecycle evidence 的前提下，先补齐 Task 6 已证实缺失的 pre-adopt identity、benchmark outer-worker supervision 与 production Qwen cleanup journals，再按完整 panel 竞争面恢复 Task 6。

**Architecture:** 变更分为四个可独立拒绝或接受的 slice：A 只增加 Registry 锁内只读 identity inspection；B1 只增加 benchmark-marked multiprocessing child 的 pre-handler gate、exact PID/create-time/Job owner 与 durable worker cleanup；B2 只增加 production Qwen owner cleanup sidecar 与 Registry normal/abnormal reconciliation；C 才实现 Task 6 durable operation、同锁 intent/CAS 与 panel compatibility。Task 7 只消费 A/B 的 sealed journals和raw OS transcripts，不重复签发 owner/cleanup truth。

**Tech Stack:** Python 3.11、pytest、现有 `LearningStageWorkerRegistry`、Windows `spawn`、Win32 Job Object、`psutil` PID create-time、现有 Qwen lease/tombstone、canonical JSON/SHA-256、WorkflowService expected-revision CAS。

**Spec:** `docs/superpowers/plans/2026-08-26-portfolio-hybrid-v1-1-benchmark-v2-plan.md`、`.superpowers/sdd/2026-08-25-portfolio-hybrid-v1-1-implementation-plan/task-10b-slice-6-brief.md`、`task-10b-slice-6-preflight.md`、`task-10b-slice-6-report.md`、`task-10b-slice-5-review.md`。

## Status and authority

本 amendment 是恢复 canonical Task 6 前的强制前置，不是可选建议。执行顺序固定为 **A → 独立审查 → B1 → 独立审查 → B2 → 独立审查 → C/Task 6 → 独立审查 → Task 7**。任何 slice 未 GREEN 或仍有 Critical/Important finding，后续 slice 不得开始。

本地证据是本 amendment 的 authority。ChatGPT consultation 已因保存的用户浏览器权限阻塞；不得将“未完成 consultation”当作放宽证据标准的理由。

## Global constraints

- 不运行 benchmark actual mode、真实 Qwen inference、Omni、VISTA、regression execution、holdout、click、fill、publish、action 或 Runtime execution。
- 不读取或触碰 `tests/test_agent_runtime_actual_adapter_portfolio_v1.py`；任何工作树中既有的同名 untracked 文件也不属于这些 slice。
- 不从 `logs/workflow-workers/<id>.result.json` 在 Registry 外直接读取 result，不访问 `registry._records`，不复制 `_load_worker_result()`，不让 WorkflowService 自算或自报 result/cleanup truth。
- `pid`、`process.is_alive() is False`、`request_not_active`、test-owned external Job 或 synthetic mapping 单独都不是 cleanup proof。
- 保持现有 panel routes、Pydantic request models、`APIResponse` messages/error codes/data shape 不变；非benchmark incumbent/Hybrid 的返回 bytes/semantics、continuation graph 与 exception mapping 不变。
- benchmark durable mode 只能由 server-owned store CAS 写入并读取；caller payload、`learning_pipeline_mode`、reserved key、task kind 或测试 patch 都不能启用 production benchmark branch。
- Task 5 的 `_benchmark_v2_window_binding` serializer/injector/validator 是唯一 window binding path；A/B/C 不复制它，也不接受 client 提交的 generic adoption mapping。
- 所有新增 receipt 都必须是 sealed closed mapping，保存 parent ref/content SHA、exact operation/worker/model-request identity 与 raw journal path ref；派生结论只能引用已验证 parent。
- 注释使用 UTF-8 中文；文件保留 UTF-8 与 LF；每个 slice 只改自身 allowlist。

## Evidence-backed rulings

1. `LearningStageWorkerRegistry.status()` 删除 `worker_result`，只暴露 `result_available`；`adopt_result()` 才计算 exact result SHA，但会立即写 adoption。因此必须先新增锁内 read-only inspection，不能由 Task 6 绕过 Registry。
2. generic `vision_observe_screen` journal 不保存 outer child create-time/Job/handle owner；restart 后 `process=None`，detached cancel 的 backend termination 是 `not_covered`。因此 outer worker supervision 必须在 Task 6 前进入 production Registry path。
3. Windows multiprocessing `spawn` 不能假称已由现有 `spawn_process_in_scope()` suspended-create。B1 采用 child bootstrap gate：child 只可发布自身份并等待；parent 在 release gate 前完成 exact identity复核、Job assignment、sole-membership复核和durable journal。此设计只证明“handler/provider 前已纳管”，不夸大为“Python interpreter 创建前已纳管”。
4. generic Qwen normal release 的返回值当前被丢弃；已有 owner tombstone 不含足够的 full-lease cleanup evidence供 Task 6验证。B2 必须由 production `model_server.py` 写独立 sidecar并提供 read-only verifier；测试 helper 不得签发 production receipt。
5. panel 真实竞争面是 start/status/adopt/continue/cancel/heartbeat/finish/recover 八个入口，另有 read-only runtime attachment composition seam；只改“五入口”仍可绕过 intent winner。

**Codegraph anchors reviewed:** Registry `start/status/adopt_result/read_adopted_result/cancel_by_operation` 位于 `app/learn/workflow_worker.py:1749,2121,2143,2214,2289`；journal/public refresh在 `:1682,2686,2844,3057,3299`。Job assignment/suspended subprocess primitive在 `app/learn/hybrid/windows_process_scope.py:63,108,190,256`。Qwen release/cleanup/tombstone链在 `app/core/model_server.py:624,1020,1030,1346,1791,2312,2357`。Panel八入口位于 `app/api/panel.py:892,932,1042,1077,1122,1166,1235,1287`。实现时只在这些anchor附近做窄改并重新用codegraph impact确认blast radius。

## File responsibility map

| File | Responsibility introduced by this amendment |
|---|---|
| `app/learn/workflow_worker.py` | A 的 completed-result identity primitive；B1 的 benchmark worker owner/gate/journal/reconciliation；B2 的 provider cleanup ref retention/recovery |
| `app/learn/hybrid/windows_process_scope.py` | B1 的 exact PID/create-time handle-open、Job assignment与closed assignment observation；不创建第二套 Job implementation |
| `app/core/model_server.py` | B2 的 production Qwen finalized-cleanup sidecar writer/reader/verifier；不改变既有 owner tombstone/API response |
| `app/learn/hybrid/benchmark_v2_incumbent_operation.py` | C 的 closed durable document/receipt contracts与 benchmark façade protocol |
| `app/learn/workflow_service.py` | C 的 single composition、operation RLock、guarded wrappers、intent/CAS/resume |
| `app/api/panel.py` | C 的八入口内部 wiring；routes/models/responses不变 |
| `tests/test_learning_workflow_stage_worker.py` | A/B1/B2 Registry contracts、restart与cleanup regression |
| `tests/test_learn_hybrid_windows_process_scope.py` | B1 exact identity assignment、PID reuse/Job/handle负控 |
| `tests/test_model_request_cancellation.py` | B2 production Qwen sidecar normal/abnormal/idempotent recovery |
| `tests/test_portfolio_hybrid_v1_1_benchmark_v2_incumbent.py` | C durable operation、race/crash/no-cascade/no-action tests |
| `tests/test_learning_workflow_stage_execution.py` | C incumbent/Hybrid panel compatibility和八入口 dependency seam |

---

### Prerequisite A: Registry read-only completed-result identity

**Allowed files:**
- Modify `app/learn/workflow_worker.py`
- Modify `tests/test_learning_workflow_stage_worker.py`

**Interfaces:**

```python
class LearningStageWorkerRegistry:
    def inspect_completed_result_identity(
        self,
        *,
        worker_id: str,
        run_id: str,
        stage: str,
        operation_id: str,
    ) -> dict[str, Any]: ...
```

返回 mapping 的 exact keys 固定为：

```python
{
    "contract_version": "learning_stage_worker_completed_result_identity_v1",
    "status": "completed",
    "worker_id": str,
    "run_id": str,
    "stage": str,
    "operation_id": str,
    "task_kind": str,
    "model_request_id": str,
    "payload_sha256": str,
    "result_sha256": str,
    "result_available": True,
    "normal_binding_evidence_ref": {"content_sha256": str} | None,
    "provider_cleanup_evidence_ref": {"content_sha256": str} | None,
}
```

实现必须在 `Registry._lock` 内调用现有 `_refresh_record()`，由现有 `_load_worker_result()` 完成 envelope contract、七字段 identity、payload SHA、status 与 response shape validation，再从同一次读取后保存在record内的 `worker_result` object计算 `result_sha256`和两个ref；不得在锁外或对result file做第二次读取。这是“Registry当前已验证 envelope 的exact-byte snapshot”，不是首次写入前immutability证明。它不得写 `result_adoption`、不得调用 `_persist_record_journal()`（`_refresh_record()` 对首次完成状态的既有持久化除外）、不得返回 response/result path/raw envelope。两个 evidence ref必须是closed one-key mapping且value为lowercase SHA-256；A只验证closed ref shape，不复制Task5/B1/B2 parent verifier。A允许provider ref为`None`，B2后benchmark-marked result必须非空。

若第一次inspection前有人用相同七字段identity和合法self hash重写response，A会如实snapshot当前bytes，**不会也不能单独识别semantic remint**。A只报告变化后的current SHA且不作tamper结论；联合parent-remint拒绝属于C RED 3/E2E。若未来要求第一次读取前byte immutability，必须新增先于result file且由独立parent持有的anchor与one-read protocol，并单独review；本slice不得用child/self hash冒充该anchor。

- [ ] **RED 1 — public identity boundary:** 新测试 `test_completed_result_identity_is_pre_adopt_read_only_and_closed` 先断言方法不存在；准备真实 Registry result envelope，要求 inspection 后 `result_adopted is False`、journal无 `result_adoption`、返回keys完全相等且无 `response/result_path`。
- [ ] **RED 2 — observable invalidity:** wrong worker/run/stage/operation/task/model-request identity、payload SHA不匹配、failed/running status、completed response非object、broken JSON、evidence ref多字段/缺字段/非lowercase SHA全部fail closed。
- [ ] **RED 3 — exact handoff:** inspection result SHA 必须与随后 `adopt_result()["receipt"]["result_sha256"]` exact相等；并发 inspection/adopt 不得产生不同 digest或第二 adoption receipt。
- [ ] **RED 4 — claim boundary:** same-identity semantic remint在A产生一个不同但有效的current snapshot SHA；A测试只断言current SHA变化且A不把它误报为旧bytes或tamper proof，不创建、调用或仿造未来B1/B2/C fixture。
- [ ] **Run RED:** `uv run pytest -q tests/test_learning_workflow_stage_worker.py -k "completed_result_identity"`；Expected: missing method / asserted contract FAIL。
- [ ] **GREEN:** 只实现上述 Registry method与最小 closed ref helper；不把 result SHA 加入现有 `status()` public record。
- [ ] **Run GREEN:** `uv run pytest -q tests/test_learning_workflow_stage_worker.py -k "completed_result_identity or adopt_result or read_adopted_result" && uv run python -m py_compile app/learn/workflow_worker.py && git diff --check`。

**Crash/race/negative controls:** result file在 `_refresh_record()` 前或同一次locked refresh中变成broken/identity-mismatched envelope必须FAIL；refresh完成后的inspection和adopt只使用同一个record snapshot，文件随后变化不得让同一次调用混合两个bytes。inspection 与 cancel/status并发不得泄露 raw response；reloaded Registry 对磁盘上当前合法completed envelope返回其current SHA，不声称等于更早未锚定bytes。

**Cleanup:** 只使用 tmp Registry roots；无 spawn、Qwen、window、Job、listener或lease。测试 finally 删除 temp root并断言无 adoption side effect。

**Independent review gate:** reviewer逐行确认唯一 result读取者仍为 Registry、inspection在同一lock内、无 raw response/path、无 adoption mutation；输出 `task-10b-slice-6-prerequisite-a-review.md`，Critical/Important 必须为零。

**Commit:** `feat(learning-worker): inspect completed result identity read-only`

---

### Prerequisite B1: Benchmark outer-worker gate, exact Job owner, and durable worker cleanup

**Depends on:** Prerequisite A PASS + independent review PASS。

**Allowed files:**
- Modify `app/learn/hybrid/windows_process_scope.py`
- Modify `app/learn/workflow_worker.py`
- Modify `tests/test_learn_hybrid_windows_process_scope.py`
- Modify `tests/test_learning_workflow_stage_worker.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class BenchmarkWorkerSupervisionRoot:
    authority_kind: Literal["production_workflow_service", "test_only"]
    journal_root: Path
    root_capability: object
    read_only_store_authority: object
    store_identity_sha256: str

def get_production_benchmark_worker_supervision_root(
) -> BenchmarkWorkerSupervisionRoot: ...

def compose_test_benchmark_worker_supervision_root(
    *, journal_root: Path, test_capability: object,
    workflow_store: LearningWorkflowRunStore,
    test_store_capability: object,
) -> BenchmarkWorkerSupervisionRoot: ...

BENCHMARK_WORKER_CONTROLLER_DEFAULT_TIMEOUT_MS: Final[int] = 5000

def benchmark_worker_scope_name_v1(
    *, authority_kind: Literal["production_workflow_service", "test_only"],
    run_id: str, stage: str, operation_id: str, worker_id: str,
    payload_sha256: str, execution_nonce: str,
) -> str: ...

def benchmark_worker_controller_mutex_name_v1(
    *, authority_kind: Literal["production_workflow_service", "test_only"],
    run_id: str, stage: str, operation_id: str,
) -> str: ...

@contextmanager
def hold_benchmark_worker_controller(
    *, supervision_root: BenchmarkWorkerSupervisionRoot,
    run_id: str, stage: str, operation_id: str,
    timeout_ms: int = BENCHMARK_WORKER_CONTROLLER_DEFAULT_TIMEOUT_MS,
) -> Iterator[object]: ...

def compose_benchmark_worker_operation_anchor_v1(
    *, supervision_root: BenchmarkWorkerSupervisionRoot,
    reservation: Mapping[str, object],
    handler_payload_source: Mapping[str, object],
    window_binding_ref: Mapping[str, object],
    capture_ref: Mapping[str, object],
    predecessor_content_sha256: str | None,
) -> dict[str, Any]: ...

def validate_benchmark_worker_operation_anchor_v1(
    value: Mapping[str, object], *,
    supervision_root: BenchmarkWorkerSupervisionRoot,
    expected_reservation: Mapping[str, object],
) -> dict[str, Any]: ...

def compose_benchmark_worker_supervision_v1(
    *, supervision_root: BenchmarkWorkerSupervisionRoot,
    reservation: Mapping[str, object],
    expected_operation_anchor: Mapping[str, object],
    supervisor_process_identity: Mapping[str, int],
    startup_gate_timeout_ms: int,
) -> dict[str, Any]: ...

def validate_benchmark_worker_supervision_v1(
    value: Mapping[str, object], *,
    supervision_root: BenchmarkWorkerSupervisionRoot,
    expected_operation_anchor: Mapping[str, object],
) -> dict[str, Any]: ...

def assign_exact_process_identity_to_scope(
    *, scope_name: str, process_identity: Mapping[str, int]
) -> dict[str, Any]: ...

class LearningStageWorkerRegistry:
    def prepare_benchmark_worker_identity(
        self,
        *, run_id: str, stage: str, operation_id: str,
        workflow_revision: int, task_kind: str,
        handler_payload_source: Mapping[str, object],
        supervision_root: BenchmarkWorkerSupervisionRoot,
    ) -> dict[str, Any]: ...

    def inspect_prepared_benchmark_worker_identity(
        self,
        *, run_id: str, stage: str, operation_id: str,
        supervision_root: BenchmarkWorkerSupervisionRoot,
    ) -> dict[str, Any]: ...

    def launch_prepared_benchmark_worker(
        self,
        *, reservation_ref: Mapping[str, object],
        expected_operation_anchor: Mapping[str, object],
        authoritative_payload: Mapping[str, object],
        supervision_root: BenchmarkWorkerSupervisionRoot,
    ) -> dict[str, Any]: ...

    def confirm_prepared_benchmark_worker_anchor(
        self,
        *, reservation_ref: Mapping[str, object],
        expected_operation_anchor: Mapping[str, object],
        supervision_root: BenchmarkWorkerSupervisionRoot,
    ) -> dict[str, Any]: ...

    def abort_prepared_benchmark_worker_before_anchor(
        self,
        *, reservation_ref: Mapping[str, object],
        run_id: str, stage: str, operation_id: str,
        workflow_revision: int,
        expected_operation_anchor: Mapping[str, object],
        reason: Literal["store_cas_lost", "cancelled", "stale"],
        supervision_root: BenchmarkWorkerSupervisionRoot,
    ) -> dict[str, Any]: ...

    def observe_benchmark_worker_cleanup(
        self,
        *, worker_id: str, run_id: str, stage: str, operation_id: str,
        terminate: bool,
        expected_operation_anchor: Mapping[str, object],
        supervision_root: BenchmarkWorkerSupervisionRoot,
    ) -> dict[str, Any]: ...
```

`benchmark_v2_incumbent_handler_payload_source_v1`必须在任何B1 reservation/anchor之前由C的server-owned composer生成，并作为可重建而非raw payload的durable authority。Exact fields固定为 `contract_version,provider_corpus_file_ref,provider_case_ref,projection_contract_version,projection_rules_content_sha256,window_binding_ref,capture_ref,handler_payload_sha256,predecessor_content_sha256,content_sha256`：`contract_version=benchmark_v2_incumbent_handler_payload_source_v1`；`provider_corpus_file_ref`是closed `contract_version,relative_path,file_sha256,content_sha256,source_parent_ref`且exact指向启动时已由`validate_preloaded_provider_corpus`验证的`provider-corpus.v2.json` bytes；`provider_case_ref`是closed `case_id,case_content_sha256`，后者对该validated corpus singleton中的完整closed case canonical JSON取SHA；`projection_contract_version=benchmark_v2_observe_screen_payload_projection_v1`；`projection_rules_content_sha256`对下述包含exact `provider_mode="local_understanding"`的literal rules table canonical JSON取SHA，任何先前按`"qwen"`或其他mode计算的rules SHA均无效并必须拒绝；Task5两个refs必须closed且current；`handler_payload_sha256`为规则投影最终mapping的canonical SHA；`predecessor_content_sha256`必须exact等于同一source内`provider_corpus_file_ref.content_sha256`，不得选择`file_sha256`、`source_parent_ref`或null。Source自身不含case mapping、goal、layout、image path或handler payload；其one-key ref为 `{"contract_version":"benchmark_v2_incumbent_handler_payload_source_ref_v1","content_sha256":source.content_sha256}`。Prepare原子把full source+ref写入B1 reservation，anchor CAS再将同一full source+ref exact复制到C durable operation；因此reservation后/anchor前fresh service经B1只读inspection恢复source，anchor后fresh service从current store source恢复，不依赖caller或old memory。Wrong corpus file/content、case ID/content、rules SHA、Task5 binding/capture，或predecessor为null/等于file SHA/source parent/任意wrong content SHA一律FAIL。Source ref加入reservation、operation anchor、anchor identity、expected/actual supervision和C durable operation，故source→reservation→anchor→launch无反向ref、worker ID或nonce循环。

Payload projection rules table是closed常量且逐key固定：最终mapping只含`task,app_name,state_hint,provider_mode,agent_mode,learn_depth,write_policy,metadata,operation_context,capture_live,image_path,_benchmark_v2_window_binding`。值固定为`task="observe_screen"`、`app_name=case.layout.title`、`state_hint=case.goal`、`provider_mode="local_understanding"`、`agent_mode="learn"`、`learn_depth="fast"`、`write_policy={"path_graph":true,"element_memory":false,"trace":true}`、`capture_live=false`；`metadata` exact为`{"benchmark_release_id": validated_corpus.benchmark_release_id,"case_id":case.case_id,"screen_group":case.screen_group,"partition":case.partition,"source_kind":"privacy_safe_synthetic"}`；`operation_context`按`ObserveScreenTaskInput`的`OperationRuntimeContext` closed投影为`contract_version="operation_runtime_context_v1"`、`authorized_intent_id=null`、`semantic_action="observe_screen"`、`skill_id=null`、`gate_decision_id=null`、`gate_policy_version=null`、`allowed_action_scope=null`、`capture_id=capture_ref.content_sha256`、`window_binding_id=window_binding_ref.content_sha256`、`viewport_size={"width":case.image.width,"height":case.image.height}`、`evidence_refs=[source前体provider corpus content SHA,case content SHA,window binding SHA,capture SHA]`、`source="benchmark_v2_provider_safe"`、`synthesized_fields=[]`；`image_path`只能由Task5 sealed capture ref经server resolver得到的canonical existing provider-safe capture path，且其file SHA/1280×720必须分别匹配case image SHA/dimensions与capture ref；`_benchmark_v2_window_binding`只能是Task5既有literal projection。`local_understanding`是当前production `vision_observe_screen`唯一在本计划中sealed的managed observation mode：worker现有model-ready path会取得B2追踪的managed Qwen lease，随后existing local-understanding provider绑定该exact lease；本计划不新增provider mode或修改factory。Pydantic validation后再以`model_dump(mode="json")`加唯一marker取canonical SHA；`provider_mode`替换为`"qwen"|"local"|"local_grounding"|"api"|null`、default变化、extra key、caller-supplied path或case字段均FAIL。该rules table的canonical bytes及SHA在C source module中是production常量并由tests直接锁定，不能在restart时从journal重构。

Store锚定的是不含launch-time parent incarnation的`benchmark_worker_expected_supervision_v1`，其exact fields固定为 `contract_version,authority_kind,operation_anchor_ref,reservation_ref,supervision_inputs_ref,handler_payload_source_ref,run_id,stage,operation_id,workflow_revision,worker_id,task_kind,payload_sha256,execution_nonce,scope_name,startup_gate_timeout_ms,artifact_is_authorization,execute_binding_enabled,content_sha256`。实际launch后写`benchmark_worker_supervision_v1`，exact fields固定为 `contract_version,authority_kind,expected_supervision_ref,operation_anchor_ref,reservation_ref,supervision_inputs_ref,handler_payload_source_ref,run_id,stage,operation_id,workflow_revision,worker_id,task_kind,payload_sha256,execution_nonce,scope_name,supervisor_process_identity,startup_gate_timeout_ms,artifact_is_authorization,execute_binding_enabled,content_sha256`。`expected_supervision_ref`必须等于store anchor；`supervisor_process_identity`是实际持有creator Job/Event/process handles的launching Registry parent exact PID/create-time。expected contract故意不含该launch-time identity，使store-anchor后、launch调用前的server restart可由fresh exact parent使用同一reservation；实际supervision及owner chain再绑定新parent，不能remint expected inputs。`task_kind`必须是`vision_observe_screen`；nonce必须是Registry在任何spawn前reservation阶段生成并首次持久化的32位lowercase hex；两个authorization boolean必须为false。任何extra/missing field拒绝。

Scope-name input是canonical JSON `{"contract_version":"benchmark_worker_scope_name_v1","authority_kind","run_id","stage","operation_id","worker_id","payload_sha256","execution_nonce"}`，name为production `Local\\AgentGuiBenchmarkWorker-<sha256>` 或 test `Local\\AgentGuiBenchmarkWorkerTest-<sha256>`。Fresh Registry必须从sealed inputs重算，不能相信journal内name。该grammar独立于且不得放宽现有 `Local\\AgentGuiHybrid-(omni|qwen|vista)-<sha>` provider namespace。existing same-name Job一律collision FAIL，绝不attach或生成新nonce重试。

Cross-process owner authority使用独立per-operation named mutex，而不依赖进程内`Registry._lock`或“旧server应该已退出”的假设。`BENCHMARK_WORKER_CONTROLLER_DEFAULT_TIMEOUT_MS`字面值固定为`5000`；production及未显式覆盖的test调用必须使用该值，拒绝负数、零、非整数或超出Win32 DWORD安全范围的值。Mutex canonical input固定为 `{"contract_version":"benchmark_worker_controller_mutex_name_v1","authority_kind","run_id","stage","operation_id"}`；production name=`Local\\AgentGuiBenchmarkWorkerController-<sha256>`，test name=`Local\\AgentGuiBenchmarkWorkerControllerTest-<sha256>`，grammar与worker Job/provider namespaces互不相容。`hold_benchmark_worker_controller()`只向root-bound service/Registry返回thread-bound、不可序列化opaque guard；C必须从B1 prepare之前一直持有同一guard，跨越store anchor CAS、必要pre-anchor abort、B2 owner CAS、authoritative payload rebuild和B1 launch/compensation，直到启动或abort结果durable。B1 public methods在无outer guard时自行取得mutex；已有same-thread exact guard时只做Win32 mutex reentrant acquire/release，不能提前释放outer hold。Lock顺序固定service RLock→controller mutex→Registry `_lock`；持mutex时可在Registry lock外访问store，Registry lock内不得等待mutex或回调store。Mutex timeout返回busy/pending且zero mutation；`WAIT_ABANDONED`只授予exclusive ownership，不证明前任cleanup，必须fresh重验reservation/owner chain和OS state后才能变更。Mutex handle的真实acquire/release/close observations进入B1 diagnostic/negative evidence；wrong/cross-kind name、guard跨thread/operation/root复用、双live Registry controller和release/close failure均FAIL。这样另一个process不能在prepare返回与store CAS之间插入abort/anchor/launch，也不能同时reopen/close creator Job或写同一operation journal。

Mutex结果/递归/错误语义机械固定：首次同thread/root/name取得handle并`WAIT_OBJECT_0|WAIT_ABANDONED`后recursion count=1；同一thread/root/name嵌套复用exact handle，每层再执行一次Win32 wait并加一，每层`finally`恰调用一次`ReleaseMutex`并减一，只有count归零才调用一次`CloseHandle`；跨thread/name/root release与underflow拒绝。`WAIT_TIMEOUT`必须先关闭本次未取得ownership的handle，再抛`LearningStageWorkerError("benchmark worker controller mutex timed out")`，且reservation/journal/store/process/Event/Job/beacon/provider mutation count全为0；timeout handle close错误以cleanup diagnostic附加但不能把timeout升级为ownership。`WAIT_ABANDONED`记录raw outcome后必须在任何write/spawn前fresh读取store decision、reservation/journal与exact OS owner，不能用abandoned本身补cleanup。

`ReleaseMutex`和`CloseHandle`每次raw return/WinError都进入`benchmark_worker_controller_cleanup_failure_v1` sidecar，exact绑定root/name/thread/recursion level、primary exception class+message或null、release result、close result、mutation snapshot ref及predecessor/content SHA；sidecar只是故障证据，不是release/absence proof。无primary时cleanup failure仍抛`LearningStageWorkerError("benchmark worker controller cleanup failed")`；有primary时combined diagnostic顺序固定`primary → ReleaseMutex → CloseHandle`，原primary作为`__cause__`且panel仍按原wrapper error code映射。若fresh mutation snapshot证明failure发生在任何reservation/store document/launching/OS handle之前，断言zero mutation；若已存在reservation/store anchor、`launching`或任一owned handle，调用不得返回success，operation/Registry journal有效状态视为`recovery_required`，fresh controller必须先按store+OS恢复同一incarnation，绝不second spawn/abort/remint。Release失败使ownership未知时不得直接写业务journal或调用store；只可原子写root-local failure sidecar，待另一fresh exact controller成功取得mutex后再promote recovery。Close失败但Release成功也不得忽略：primary仍优先、sidecar保留、fresh exact handle/owner验证后才继续。

Composition只持有长期的production root/factory capability，不持有per-operation authority。`get_production_benchmark_worker_supervision_root()`在B1内即可用且返回production Registry稳定journal root、不可序列化opaque root capability，以及同一root私有绑定的只读production store authority；该authority在首次使用时lazy-bind exact `app.learn.workflow_store.learning_workflow_run_store.get` bound method和该singleton的configured state-path identity，不暴露`transition`或底层mapping。`store_identity_sha256`对closed `{"contract_version":"benchmark_worker_store_identity_v1","authority_kind","store_class","canonical_state_path_or_memory_token"}`取SHA，不能取Python `id()`，且root capability同时绑定exact store object、bound getter与identity。Test root必须显式绑定per-test `LearningWorkflowRunStore`、test store capability、tmp journal root和`authority_kind=test_only`；production/test或两个test store/root/capability交叉替换全部FAIL。Panel/client mapping不能构造、序列化或替换任何authority。现有`LearningWorkflowRunStore.get(run_id)`已在store自身lock内返回deepcopy，机械上足够；B1不得扩展workflow store public API，也不得从C接收bool、state mapping、decision/ref来替代fresh getter。

`benchmark_worker_operation_anchor_v1` 是store持有的closed server-read document，exact fields为 `contract_version,run_id,stage,operation_id,workflow_revision,task_kind,payload_sha256,worker_id,execution_nonce,reservation_ref,supervision_inputs_ref,expected_supervision_ref,handler_payload_source_ref,window_binding_ref,capture_ref,anchor_identity_sha256,predecessor_content_sha256,content_sha256`。`anchor_identity_sha256`只对exact immutable subset `contract_version,run_id,stage,operation_id,workflow_revision,task_kind,payload_sha256,worker_id,execution_nonce,reservation_ref,supervision_inputs_ref,handler_payload_source_ref,window_binding_ref,capture_ref`取canonical SHA；expected supervision的`operation_anchor_ref`固定引用该non-circular identity SHA，store再持久化由该identity与reservation inputs生成且不含launching parent identity的`expected_supervision_ref`，因此worker ID/nonce/parent restart/supervision均不存在hash cycle。任何extra/missing/null-required field、current store operation/revision/ref不一致均拒绝。B2 acquisition owner refs不进入B1 anchor，C operation document将其作为与B1 anchor并列的closed parents封存，因此严格DAG仍为B1先独立GREEN/review，再B2，再C。

Registry在controller mutex +自身lock内执行严格两步协议。`prepare_benchmark_worker_identity()`只为exact `(run,stage,operation,workflow_revision,task_kind,payload_sha256,handler_payload_source_ref,root-kind)`生成并durable reservation一个worker ID和32-hex execution nonce；payload SHA只从closed source的`handler_payload_sha256`取得，prepare不接受raw handler payload。`benchmark_worker_identity_reservation_v1` exact fields为 `contract_version,authority_kind,run_id,stage,operation_id,workflow_revision,task_kind,payload_sha256,handler_payload_source,handler_payload_source_ref,worker_id,model_request_id,execution_nonce,supervision_inputs_ref,reservation_state,abort_observation_ref,predecessor_content_sha256,content_sha256`；state只能`reserved|anchored|launching|launched|cancelled_before_launch|aborted_before_anchor`，不适用abort ref显式null。Prepare返回`reserved` closed mapping，并把上述closed source document及其ref原子封存在reservation中；source不含case mapping/raw payload，故这是fresh pre-anchor recovery authority而不是handler input。它不得创建process/Event/Job/beacon、设置provider环境、安装handler或取得Qwen lease，也不得把raw case/payload写入reservation/generic journal。`inspect_prepared_benchmark_worker_identity()`在controller mutex→Registry lock内按exact run/stage/operation/root只读返回同一validated reservation deepcopy，绝不读取result、改变state或生成新worker/nonce；fresh crash在reservation后、store anchor前时只能经该inspection取得source，再由current production resolver验证source并重试同一store CAS。Wrong operation/root/source content或多个reservation均FAIL。相同inputs replay返回byte-identical reservation；同operation冲突inputs拒绝且不得第二reservation。B1 composer/validator只用root capability、reservation中已绑定的source ref与source携带的Task5 refs构造closed operation anchor及parent-independent expected supervision，所以B1可在B2/C前独立GREEN/review。只有store anchor成功且下述confirmation已把reservation转为`anchored`后才可调用`launch_prepared_benchmark_worker()`；launch在controller mutex + Registry lock内fresh读取anchored reservation，closed-validate由store传入的current anchor、重算anchor identity/scope/expected supervision并要求其SHA等于store `expected_supervision_ref`，验证下述authoritative payload，再以**当前**Registry parent identity构造actual supervision，随后原子标记`launching`并至多启动一次worker。Fresh observer也必须由C重新读取store current anchor并传入，B1重算parent-independent expected supervision ref，再验证actual supervision/owner的exact supervisor identity；只信journal、只信anchor SHA或由journal自重算均只能pending。

Store B1 anchor CAS成功后，C必须在同一outer controller guard内立即调用`confirm_prepared_benchmark_worker_anchor()`。`benchmark_worker_anchor_confirmation_v1` exact fields为 `contract_version,outcome,reservation_ref,anchored_reservation_ref,operation_anchor_ref,expected_supervision_ref,handler_payload_source_ref,run_id,stage,operation_id,workflow_revision,worker_id,payload_sha256,execution_nonce,prior_state,new_state,predecessor_content_sha256,artifact_is_authorization,execute_binding_enabled,content_sha256`；outcome=`verified_anchor_confirmed`、`prior_state=reserved`、`new_state=anchored`，两个authorization booleans=false。方法closed-validate store-supplied anchor、重算expected supervision，在Registry lock内只允许该transition，replay byte-identical。Crash在store CAS后、confirmation前时，fresh service先读current store anchor并confirm同一reservation，不能调用pre-anchor abort；confirm前不得创建B2 owner或launch。`aborted_before_anchor|launching|launched|cancelled_before_launch`拒绝。该窄confirmation使abort可以机械拒绝已confirmed anchored reservation；对尚未confirmed的`reserved`，B1只能经root-bound getter fresh读取store并生成上述decision，绝不接受caller“anchor absent”自述。

`authoritative_payload`不是payload path/ref，也不是client或journal输入。C production composition持有由启动时已validate provider-corpus singleton生成的opaque、不可序列化case resolver；caller只给closed `provider_case_ref={"case_id","case_content_sha256"}`，若兼容层收到mapping必须先由resolver与singleton case exact canonical-match并立即降为该ref，mapping不得进入store/B1。Current/fresh workflow service从current store中的source ref，经production resolver重新取得sealed provider-safe case，再严格应用上述literal projection并注入Task5 binding/capture；不得从caller request、旧service内存、B1 journal、worker result或持久化raw payload加载。Launch在Registry lock内canonicalize/recompute payload SHA exact等于source、reservation及operation anchor三处，并重新验证reserved marker与source↔Task5 window/capture relation后才写`launching`。Wrong/currently unavailable resolver singleton、corpus/case/rules/source/capture、caller mapping replay、extra/default漂移均zero spawn/provider。Store-anchor后、launch前restart必须丢弃caller与old Registry/service，fresh composition用current store source document/ref→production resolver→same sealed case→same projection重建mapping，再以同worker/nonce单次launch；payload仍不进入任何B1 durable artifact。Source composer/resolver只在C允许文件中实现：复用/窄扩`app/learn/hybrid/benchmark_v2_provider_corpus.py`的validated-corpus case resolver，并在新`benchmark_v2_incumbent_operation.py`封装source composer/projection；B1不新增文件也不解析provider corpus。

`benchmark_worker_store_anchor_decision_v1`是B1在abort内部生成的closed fresh observation，exact fields固定为 `contract_version,authority_kind,store_identity_sha256,store_state_found,current_state_content_sha256,current_revision,current_stage,current_operation_id,current_operation_outcome,current_incumbent_document_ref,current_operation_anchor_ref,run_id,stage,operation_id,workflow_revision,reservation_ref,expected_operation_anchor_ref,reason,outcome,predicate,content_sha256`。`store_state_found=false`时current六字段显式null；否则B1对root-bound `get(run_id)`返回的完整deepcopy按项目canonical JSON取`current_state_content_sha256`，从既有validated state的top-level `revision`、current stage/operation/outcome及exact `stage_execution["benchmark_v2_incumbent"]`读取其document/ref，禁止C另传state shape。`expected_operation_anchor_ref`由B1对传入anchor做closed validation、要求其reservation/source/root exact匹配后重算，caller ref不能替代重算。`outcome`只能`matching_anchor_present|matching_anchor_absent_store_cas_lost|matching_anchor_absent_cancelled|matching_anchor_absent_stale|indeterminate`：matching要求current incumbent document的operation anchor exact等于expected；CAS-lost要求anchor absent且fresh revision/active operation已与requested expected revision/identity冲突；cancelled要求anchor absent且existing current operation outcome是既有closed cancelled/terminal state；stale要求run absent或active stage/operation已被另一closed identity取代；相同revision/identity且anchor absent只可`indeterminate`并要求C重试store CAS，不能abort。Reason与outcome一一对应，任何unvalidated/missing/extra state、getter error或ambiguous field只可抛`LearningStageWorkerError`且reservation不变。Decision不可由caller提供、persisted journal复用或仅以ref重放。

Abort exact order固定为 `service RLock→controller mutex→root-bound store get/decision→Registry _lock→reservation/decision/absence validation→atomic transition`。Controller guard跨store read与Registry mutation持续持有，而所有benchmark store writer也必须先取得同一controller mutex，因此无TOCTOU；Registry lock内严禁调用store getter或任何C callback，`Registry-lock→store`在test seam中必须立即拒绝而不是等待。若decision=`matching_anchor_present`，abort必须以exact `benchmark worker operation anchor already exists`错误退出、reservation byte不变，fresh C随后调用confirm；若decision是三个matching-absent closed outcomes且reason匹配，才继续absence checks；`indeterminate`或reason/outcome mismatch均pending/FAIL。

`benchmark_worker_pre_anchor_abort_receipt_v1` exact fields固定为 `contract_version,outcome,authority_kind,reservation_ref,store_anchor_decision_ref,abort_observation_ref,aborted_reservation_ref,run_id,stage,operation_id,workflow_revision,worker_id,model_request_id,payload_sha256,handler_payload_source_ref,execution_nonce,reason,prior_state,owner_absence_observation_ref,process_event_job_beacon_absence_observation_ref,result_absence_observation_ref,provider_absence_observation_ref,predecessor_content_sha256,artifact_is_authorization,execute_binding_enabled,content_sha256`。`outcome=verified_aborted_before_anchor`、`prior_state=reserved`、reason只能`store_cas_lost|cancelled|stale`，两个authorization booleans为false。`abort_prepared_benchmark_worker_before_anchor()`只接受reservation identity与B1可重算的expected anchor，不接受store state、absence bool或decision/ref。它按上述order fresh读取store并生成decision，之后在Registry lock内reload exact `reserved` reservation，要求decision exact绑定同一reservation/expected anchor/store root，且没有owner journal/process/Event/Job/beacon/result；provider absence只由B1 prepare路径尚未调用B2/provider且无provider owner artifact的closed observation证明。它先原子追加predecessor-linked closed `benchmark_worker_pre_anchor_abort_observation_v1`（含decision ref），再以该ref把同一reservation转为`aborted_before_anchor`，最后写receipt；三个artifacts各自canonical SHA/predecessor exact连接。Crash/retry必须重新调用root getter：若已aborted，只有fresh decision inputs与persisted receipt exact一致才返回byte-identical receipt；若matching anchor出现则拒绝且不得复用旧absence decision。`anchored|launching|launched|cancelled_before_launch`或任一artifact存在时拒绝，不能借cleanup observer、C mapping或caller CAS exception升级。C在pre-anchor store CAS lost、cancel或stale路径只消费这个Registry receipt，不自己声明zero spawn/provider。

Crash/replay/cancel固定如下：prepare前crash无side effect；reservation durable但store CAS前crash时，active operation/revision/inputs仍exact可用同一reservation继续CAS，否则必须调用上述pre-anchor abort并消费其receipt；C不得直接改reservation。Store anchor后、launch前crash由fresh service重建authoritative payload并以同一reservation launch，或由cancel经anchored cleanup path标记`cancelled_before_launch`，不得调用pre-anchor abort或生成新worker ID/nonce；launch标记后crash由B1 owner journal/Job tri-state恢复，绝不第二spawn。prepare/abort/store CAS/launch/cancel并发由同一controller mutex串行，每个operation最多一条reservation chain和一个worker incarnation；abort先赢时后续CAS/launch拒绝，anchor/launch先赢时pre-anchor abort拒绝。

`assign_exact_process_identity_to_scope()` 只可打开 exact PID handle；OpenProcess 前后都要用 create-time复核，assignment后要求 named Job members exact包含该 `{pid,create_time_ns}`，关闭临时 process handle与Job handle，并返回 closed `benchmark_worker_scope_assignment_v1` observation。PID不存在、create-time漂移、Job不可观察、member多于或少于预期、handle close失败均拒绝。

benchmark marker不是caller payload flag。它只来自上述server-only prepare→store anchor→launch protocol；generic `start()` callers继续原路径，caller payload中任何reserved marker拒绝。B1 owner journal的closed phase依次为 `acquiring → identity_published → assignment_proven → gate_released → cleanup_finalization_intent → cleanup_verified`，另有terminal `recovery_required`；每次原子写且predecessor SHA连接。

`benchmark_worker_owner_journal_v1` exact fields固定为 `contract_version,authority_kind,operation_anchor_ref,reservation_ref,supervision_ref,run_id,stage,operation_id,worker_id,model_request_id,payload_sha256,execution_nonce,scope_name,supervisor_process_identity,phase,process_identity,beacon_ref,assignment_observation_ref,job_policy,gate_state,exit_observation_ref,stable_zero_observation_ref,exact_handle_observation_refs,cleanup_finalization_intent,cleanup_receipt_ref,predecessor_content_sha256,content_sha256`。不适用字段必须显式null，不能删除；`gate_state`只能`closed|released|not_released_due_to_failure`。`job_policy`非null时exact为 `kill_on_job_close=true,breakaway_ok=false,silent_breakaway_ok=false,owner_handle_authority=registry_parent`。

`benchmark_worker_cleanup_finalization_intent_v1` exact fields固定为 `contract_version,supervision_ref,assignment_proven_ref,run_id,stage,operation_id,worker_id,supervisor_process_identity,process_identity,scope_name,gate_state,exit_observation_ref,stable_zero_observation_ref,exact_owned_handles,exact_handle_observation_refs,owner_job_handle_close_planned,cleanup_receipt_id,predecessor_content_sha256,content_sha256`；`exact_owned_handles`必须列出 `worker_process,startup_event,beacon_file,owner_job` 四项，每项只能`open|closed_explicitly|closed_by_verified_supervisor_exit`。由于intent必须先于最后Job handle close，same-live normal intent内`owner_job=open`且其raw ref为null；不得预写closed。Registry wrapper是这些真实handles的唯一owner；`closed_explicitly`只能由对应production close API真实调用后的raw observation生成，observation exact记录handle kind/identity、call result或error、observed_at、predecessor/ref，close前预写状态或journal内字符串不能作proof；non-Job close调用成功后测试注入的throw仍保存success observation，close API返回/抛错则保存error且保持pending。`closed_by_verified_supervisor_exit`只能由fresh OS exact PID/create-time probe证明原supervisor incarnation absent后派生。Journal state、自述mapping、global handle count都不是handle closure proof。`owner_job_handle_close_planned=true`。`cleanup_receipt_id`由上述immutable identity canonical SHA确定，restart不得生成第二ID。

`benchmark_worker_cleanup_receipt_v1` exact fields固定为 `contract_version,outcome,operation_anchor_ref,reservation_ref,supervision_ref,run_id,stage,operation_id,worker_id,process_identity,assignment_proven_ref,finalization_intent_ref,exact_handle_observation_refs,job_absence_observation_ref,worker_absence_observation_ref,supervisor_absence_observation_ref,reservation_abort_ref,artifact_is_authorization,execute_binding_enabled,content_sha256`。`outcome`只能为互斥的`verified_exact_worker_exited|verified_not_launched`。前者要求supervision/process/assignment/finalization、non-Job raw handle refs、Job/worker absence refs均non-null且reservation abort null；same-live branch的supervisor absence为null，Job raw close ref允许在success-after-close throw cut为null且不得补造；dead-supervisor branch的supervisor absence必须non-null，缺raw close的handle只能由该fresh exact absence派生。后者只允许launch CAS前cancel赢得、Registry durable把同一reservation标记`cancelled_before_launch`且fresh证明该reservation没有owner journal/process/Event/Job/beacon，要求reservation abort ref non-null并使所有launched-worker字段null。两个authorization booleans为false；C只能消费该Registry production receipt，不能自述zero spawn。

**Windows spawn fence ruling:**

1. parent 在 `process.start()` 前创建 unset startup Event、unique Job与 `acquiring` owner journal；
2. `_run_learning_stage_worker_entry()` 的第一项 benchmark branch只发布 self `{pid,create_time_ns}` beacon并等待 Event；在 Event成功前不得安装 Task5 binding、设置 `AGENT_GUI_MODEL_REQUEST_ID`、加载model profile、调用handler/provider/OCR/UIA；
3. parent验证 beacon与 `process.pid` exact一致，调用 `assign_exact_process_identity_to_scope()`，复核sole Job membership，先持久化 exact owner+journal，再 `event.set()`；
4. gate wait timeout、parent pipe/handle失效或 owner ref漂移时 child直接 `_exit`，不运行handler/provider；
5. 这证明 pre-handler/provider fence，不声称 multiprocessing Python interpreter 是 suspended-created。

`assignment_proven` 必须在gate release前durable保存：supervision contract/ref、recomputed scope name、exact PID/create-time、assignment observation/ref、observed sole member、`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE=true`、breakaway/silent-breakaway均false、owner-handle authority、gate仍closed与predecessor SHA。缺任一字段不能放gate。`cleanup_finalization_intent` 必须在最后owner Job handle close前durable保存：assignment_proven ref、gate state、exit/join observation、exact-owned process/Event/beacon handles状态、原始stable-zero samples/ref、planned owner-handle close和receipt identity/predecessor。Intent写入失败时owner handle保持open且operation pending。

Normal completion顺序固定为：join exact incarnation并验证exit → 对exact process/Event/beacon handles逐一真实close并durable追加raw observations → Job三次stable-zero → 写 `cleanup_finalization_intent`（owner Job仍open）→ close最后owner Job handle并在调用返回时追加raw close success/error observation → fresh检查Job-name absent与exact PID incarnation absent → 以temp-create→write→flush file→fsync parent directory→atomic replace分阶段写cleanup receipt。若Job close真实成功后在raw observation durable前throw，same-live retry只能按下述validated pre-close intent+non-Job raw observations+fresh absences规则恢复，不能把intent里的open改写成自述closed。不得在intent前关闭owner handle，也不得把global handle count或journal state当作primary proof。

Fresh Registry按durable phase执行exact tri-state，禁止从“Job absent”单独升级：

1. **Job可重开：** 从supervision inputs重算name；members只允许assignment_proven的exact singleton，或在fresh probe已证明exact worker incarnation absent时为空，任何foreign/extra identity拒绝。需要cleanup时terminate exact Job并收集stable-zero，先写或重验`cleanup_finalization_intent`，再关闭reopened handle，最后验证Job absent与exact PID incarnation absent。
2. **Job在已验证assignment后absent、同一supervisor仍活：** 只允许normal retry：已有closed-validated pre-close `cleanup_finalization_intent`且其中owner Job仍为open/planned，process/Event/beacon三项均有真实close-success raw observation，intent绑定先前三次stable-zero ref，assignment observation/no-breakaway/KILL_ON_CLOSE/content chain全部重验通过；再fresh证明name absent与exact worker `{pid,create_time_ns}` absent，即可由同一exact live supervisor续写同一`cleanup_receipt_id`。Job raw close-success observation若已durable必须重验；若close真实成功后throw导致该observation缺失，只能由上述fresh named-Job absence证明planned close已生效，不能回写伪raw handle observation或把intent字段改成closed。Receipt temp/write/flush/directory-fsync/replace失败也走此分支；不得因journal状态字符串自行升级。
3. **Job在已验证assignment后absent、原supervisor已退出：** 这是独立dead-supervisor inference分支。phase至少`assignment_proven`、完整assignment/policy/content chain、fresh Job-name absent、fresh exact worker incarnation absent，且fresh OS证明原`supervisor_process_identity` exact incarnation absent时，才可把由该owner持有且没有raw close-success的handles推导为`closed_by_verified_supervisor_exit`、重建finalization intent或续写同一receipt。PID复用只证明旧incarnation absent；任一probe不可观察则pending。
4. **Job在pre-assignment `acquiring|identity_published`时absent：** 即使PID目前不存在也保持`recovery_required`；没有assignment authority时不得签receipt。若beacon给出exact live incarnation，只可双重复核后终止该incarnation并记录negative cleanup，仍不得冒充assigned KILL_ON_CLOSE proof或启动replacement worker。

若parent死在beacon已写但Job assignment之前，fresh Registry只可按beacon的exact PID+create-time双重复核后打开handle并终止该incarnation，再等待identity absent；不得按PID或进程名终止。若`acquiring` journal暂时没有beacon，reconciler等待到child gate timeout加固定margin后重读；仍无beacon或无法证明process absent时保持 `recovery_required`，不得签cleanup receipt或启动replacement worker。若Job已assignment但journal尚未升级，unique scope的observed member identity必须与稍后beacon exact一致后才可terminate；任何不一致永久fail closed。

- [ ] **RED 1 — pre-handler gate:** real Windows spawn在gate closed期间设置一个“handler/provider touched” sentinel会使测试失败；parent只在 exact assignment+journal完成后释放，释放后sentinel恰一次。
- [ ] **RED 2 — real parent-death matrix:** 用独立outer-parent helper持有creator Job/worker，分别在assignment_proven后、gate release后、result write后、stable-zero后、`cleanup_finalization_intent`后、Job close后和receipt atomic replace前由另一process真实`TerminateProcess` parent；fresh Registry按Job可重开、same-live-supervisor retry、dead-supervisor inference或pre-assignment recovery-required exact branch处理，不启动第二worker。仅同process Python exception不计parent-death证据。
- [ ] **RED 3 — close and atomic-receipt stages:** 在同一live supervisor独立注入process/Event/beacon/Job每个close调用的before-call error、API error、真实success后throw，并分别注入receipt temp-create、write、file-flush、directory-fsync、atomic-replace失败；只有validated pre-close intent、所有non-Job raw close-success、先前stable-zero、fresh Job absent+worker incarnation absent的retry可完成同一receipt。Job raw success已落盘时必须匹配；success后throw且尚未落盘时不得补造raw observation，只凭fresh named-Job absence续写。任何non-Job error/missing ref、Job仍可重开或probe不可观察保持pending。dead-supervisor分支另测且不能复用same-parent fixture。
- [ ] **RED 4 — identity/Job/reservation/source:** wrong create-time、PID reuse、foreign Job member、pre-assignment Job absent、duplicated beacon、gate timeout、handle close failure、stable-zero不足全部FAIL；source→prepare→store-anchor→launch每个crash/replay/cancel cut、duplicate reservation、worker/nonce/source/expected-supervision substitution、fresh observer只信journal全部FAIL或pending，且spawn/provider count为expected 0或1。Load-bearing restart必须先由validated corpus resolver+Task5 refs生成source；prepare后/anchor前丢弃caller及原Registry/service时，fresh B1 read-only inspection只返回同一reservation/source且zero mutation，再由current resolver重验并完成anchor；anchor后再丢弃内存，fresh composition从current store source document/ref→current production resolver取same sealed case→literal projection→Task5 sealed capture path重建authoritative payload→fresh Registry同worker/nonce单次launch；wrong corpus file/content、case ID/content、rules/source/payload SHA、source predecessor、provider_mode `qwen|local|local_grounding|api|null`、binding/capture/default/marker、caller mapping replay、journal/client path/ref或raw-payload persistence均FAIL且zero spawn。
- [ ] **RED 5 — generic compatibility:** 没有server-owned benchmark ref的所有现有 worker start/status/cancel bytes与执行顺序不变；caller payload中同名reserved key必须拒绝而不能启用supervision。
- [ ] **RED 6 — namespace/root/store/controller authority:** cross-run/cross-stage/cross-operation/worker/payload/source/nonce/reservation/anchor/expected-supervision substitution、production/test Job或controller mutex namespace互换、pre-existing Job collision、journal内scope-name替换、full supervision/anchor/owner-journal remint、wrong root/store getter/store identity/test capability全部FAIL；两个真实helper Registry并发同一operation，其中A在prepare返回后、store CAS前暂停，B尝试abort/anchor/launch/reconcile，必须因A跨CAS持有的outer controller guard而以literal 5000ms timeout、exact exception、zero mutation；A release后最多一个creator/reopen/abort/reconcile winner。另用真实abandoned-owner helper证明`WAIT_ABANDONED`后fresh store/reservation/OS revalidation；同thread三层递归含middle exception逐层exact release且只outer close；pre-mutation/post-launch分别注入ReleaseMutex/CloseHandle success/error/throw，断言primary→release→close diagnostic、recovery_required、no second spawn及finally exact controller handle absent。Guard跨thread/operation/root复用和Registry-lock→store callback均立即拒绝；Existing Omni/Qwen/VISTA name grammar与tests byte/semantic不变。
- [ ] **RED 7 — store-authoritative pre-anchor abort/anchor confirmation:** production root/test root分别绑定exact store getter；对真实revision conflict、current cancel terminal、stale/missing operation三种fresh store states调用public abort，断言`benchmark_worker_store_anchor_decision_v1`绑定store identity、完整state SHA/revision/stage/op、reservation/expected anchor及closed outcome，再断言absence observations、predecessor-linked `aborted_before_anchor`和byte-identical replay；caller bool/state/decision/ref、cross-store getter/capability、same revision+same operation但anchor absent、getter error均不得abort。Crash在decision/abort observation/reservation transition/receipt atomic stages由fresh getter+Registry完成同一receipt。独立cut在store anchor CAS success后、confirmation前终止controller；fresh abort观察`matching_anchor_present`必须exact失败且reservation不变，fresh service随后confirm同一reservation。Owner/process/Event/Job/beacon/result/provider任一存在、wrong identity/reason/source、以及`anchored|launching|launched|cancelled_before_launch`均拒绝；测试强制exact order `service RLock→controller→store get/decision→Registry lock`，Registry lock内store callback立即FAIL且无死锁；C fixture只消费Registry receipt且不能自写zero-spawn mapping。
- [ ] **Run RED:** `uv run pytest -q tests/test_learn_hybrid_windows_process_scope.py tests/test_learning_workflow_stage_worker.py -k "benchmark_worker or exact_process_identity_to_scope or handler_payload_source or payload_projection or managed_qwen_mode"`。
- [ ] **GREEN 1:** 先实现 exact identity→Job assignment primitive及窄测试。
- [ ] **Run GREEN 1:** `uv run pytest -q tests/test_learn_hybrid_windows_process_scope.py -k "exact_process_identity_to_scope"`。
- [ ] **GREEN 2:** 再实现 Registry owner journal、bootstrap gate、normal/abnormal reconciliation与public cleanup observer。
- [ ] **Run GREEN 2:** `uv run pytest -q tests/test_learning_workflow_stage_worker.py -k "benchmark_worker" && uv run pytest -q tests/test_learn_hybrid_windows_process_scope.py && uv run python -m py_compile app/learn/hybrid/windows_process_scope.py app/learn/workflow_worker.py && git diff --check`。

**Cleanup:** 每个real-spawn test的outer `finally`都从store fresh读取exact operation anchor，再调用production `observe_benchmark_worker_cleanup(worker/run/stage/operation, terminate=True, expected_operation_anchor=anchor, supervision_root=production_root)`；primary assertions逐个引用Registry-owned real handle的raw close-success observation或fresh exact supervisor-absence proof，证明worker process、startup Event、beacon/file、creator/reopened Job及controller mutex handles均release/closed，并证明expected PID-create-time absent且recomputed named Job absent。Pre-anchor tests最终消费public abort receipt。Process-wide handle count只记录为diagnostic，不作为PASS/FAIL authority。禁止宽泛按进程名kill。

**Independent review gate:** reviewer手工追一条pre-anchor abort receipt、一条anchor后fresh authoritative-payload launch、一条parent crash-before-gate与一条result-after-gate路径；用两个真实controller helper验证named mutex排除双owner，确认无raw payload persistence/client ref、handler/provider fence、exact Job membership、restart无新worker及所有process/Event/Job/mutex handles关闭；输出 `task-10b-slice-6-prerequisite-b1-review.md`。

**Commit:** `feat(learning-worker): supervise benchmark worker incarnation`

---

### Prerequisite B2: Durable production Qwen cleanup receipt for normal and abnormal worker exits

**Depends on:** Prerequisite B1 PASS + independent review PASS。

**Allowed files:**
- Modify `app/core/model_server.py`
- Modify `app/learn/workflow_worker.py`
- Modify `tests/test_model_request_cancellation.py`
- Modify `tests/test_learning_workflow_stage_worker.py`

**Interfaces:**

```python
def prepare_qwen_model_request_acquisition_owner(
    request_id: str, *, runtime_owner_ref: Mapping[str, object]
) -> dict[str, Any]: ...

def abort_qwen_model_request_acquisition(
    request_id: str, *, acquisition_intent_ref: Mapping[str, object],
    runtime_owner_ref: Mapping[str, object], reason: str,
) -> dict[str, Any]: ...

def observe_qwen_model_request_cleanup(
    request_id: str,
) -> dict[str, Any]: ...

class LearningStageWorkerRegistry:
    def prepare_benchmark_provider_acquisition(
        self,
        *, reservation_ref: Mapping[str, object],
        runtime_owner_ref: Mapping[str, object],
    ) -> dict[str, Any]: ...

    def reconcile_benchmark_provider_cleanup(
        self,
        *, worker_id: str, run_id: str, stage: str, operation_id: str,
    ) -> dict[str, Any]: ...
```

`model_server.py` 在现有 owner tombstone之外写独立 sealed sidecar `qwen_model_request_cleanup_receipt_v1`。Sidecar exact fields固定为 `contract_version,outcome,model_request_id,acquisition_intent_ref,runtime_owner_ref,lease_ref,profile_ref,server_process_identity,socket_ref,job_scope_ref,finalization_token,lease_state_ref,owner_tombstone_ref,release_reason,termination_observation_ref,scope_stable_zero_ref,listener_stable_zero_ref,no_active_lease_observation_ref,no_owned_runtime_observation_ref,content_sha256`。`outcome`只能是互斥的 `verified_exact_process_exited|verified_not_acquired`；不适用字段必须显式null。`verified_exact_process_exited`由 production `_release_exact_qwen_lease()` 的 exact lease与release result生成，绑定owner request、lease/incarnation/profile、server PID+create-time/socket/Job、finalization token、lease-state/tombstone SHA、release reason、server termination和scope/listener stable-zero observation；`no_owned_runtime_observation_ref`为null。

`benchmark_provider_runtime_owner_v1`由Registry从B1 reservation生成，exact fields为 `contract_version,authority_kind,run_id,stage,operation_id,worker_id,model_request_id,reservation_ref,payload_sha256,content_sha256`；B2 production prepare返回closed `benchmark_provider_acquisition_owner_v1`，exact fields为 `contract_version,model_request_id,runtime_owner_ref,acquisition_intent_ref,owner_state,content_sha256`，`owner_state=acquisition_prepared`。两者都不含lease/process/listener/Job或provider profile。C operation document将这套refs与B1 operation anchor并列封存；跨worker/request/reservation substitution拒绝。Prepare primitive还必须在production Qwen acquisition lock内原子创建一个仅供benchmark使用的production materialization ledger，初态为`prepared_never_materialized`；此prepare不得加载profile、取得lease、创建process/listener/Job或产生这些资源的任何side effect。

Materialization ledger是单调三态：`prepared_never_materialized --abort--> aborted_never_materialized`，或`prepared_never_materialized --launch--> materialization_possible`。Abort与launch transition必须共用同一个cross-process Qwen acquisition lock并且只有一个winner。每条benchmark Qwen materialization或adoption路径都必须在首个可能的Process/listener/Job side effect之前durably提交`materialization_possible`；提交后即使cleanup、failure或restart也不可逆。`aborted_never_materialized`只证明该owner历史上从未materialize；`materialization_possible`不是lease acquired的同义词。Missing、legacy、corrupt或drifted ledger evidence一律保持`cleanup_pending/indeterminate`。既有generic process-before-lease regression仍是有效的cleanup compatibility覆盖，但必须分类为materialized-without-lease，不能授权任一success outcome。

该ledger是独立durable internal artifact，contract literal为`qwen_model_request_materialization_ledger_v1`，exact fields固定为 `contract_version,model_request_id,acquisition_intent_ref,runtime_owner_ref,state,revision,transition,predecessor_content_sha256,content_sha256`。Revision 0是唯一prepare head：`state=prepared_never_materialized`、`revision=0`、`transition=prepare`、`predecessor_content_sha256=null`。Revision 1只能是唯一winner：`transition=abort,state=aborted_never_materialized`或`transition=launch,state=materialization_possible`，`revision=1`且`predecessor_content_sha256`必须exact等于revision-0 `content_sha256`。`content_sha256`按其余exact fields的canonical JSON bytes计算；artifact不含timestamp或任何non-deterministic field。同一合法transition replay必须返回byte-identical current head；reversal、conflicting transition、request/owner/intent substitution、missing/wrong predecessor、revision gap、stale rollback以及malformed/missing/legacy ledger全部fail closed并保持pending。此internal artifact及其ref不新增或改写`qwen_model_request_cleanup_receipt_v1`字段/outcome、既有owner tombstone bytes/schema或`cancel_model_request()` response。

`verified_not_acquired`只能由production既有aborted-acquisition owner/tombstone primitive在materialization ledger已durably成为`aborted_never_materialized`时生成：必须绑定exact `model_request_id`、durable acquisition-intent ref、runtime-owner ref、sealed aborted-owner tombstone ref，并证明该runtime owner历史上从未拥有process identity、socket listener或Job member；它不是“当前无lease”或“cleanup后stable-zero”的别名。其`lease_ref,profile_ref,server_process_identity,socket_ref,job_scope_ref,termination_observation_ref,scope_stable_zero_ref,listener_stable_zero_ref`均为null，`no_active_lease_observation_ref`和绑定historical never-owned truth的`no_owned_runtime_observation_ref`均non-null；只有`aborted_never_materialized`可封存后一个ref并签发该outcome。若缺acquisition intent/runtime owner/tombstone/ledger、ledger为legacy/corrupt/drifted、ledger已是`materialization_possible`、或historical never-owned truth不可验证，则保持pending；不得由`request_not_active`、无文件、无current lease、current stable-zero或test mapping补造。`materialization_possible`但尚无durable lease时，即使verified cleanup/current stable-zero也只能`cleanup_pending/indeterminate`。Acquired lease路径只能按现有exact field shape生成`verified_exact_process_exited`。两个outcome的validator互相拒绝字段形状，不能把not-acquired升级为process-exited，也不新增第三个cleanup receipt outcome。既有owner tombstone bytes/schema与 `cancel_model_request()` response必须不变；legacy tombstone无sidecar时对benchmark只返回 `cleanup_pending/indeterminate`。

`observe_qwen_model_request_cleanup()` 的锁顺序冻结为先`_qwen_acquisition_lock()`、再嵌套`_qwen_lease_lock()`，与现有`acquire_qwen_model_lease()` production顺序一致，任何路径不得反转。一个observation使用的materialization ledger head、acquisition owner/owner tombstone、lease state/cleanup receipt及fresh absence evidence必须在该锁序下形成同一coherent snapshot，或由等价的single atomic snapshot证明；不得跨lock release拼接revision。Mixed revisions、predecessor不连贯、读取中head变化或其他non-coherent snapshot只返回pending/retry，绝不签terminal receipt。在该snapshot内，exact lease必须不再active；acquired owner的sole server必须有same-incarnation termination、socket listener zero、Job stable-zero，并且只能观察为`verified_exact_process_exited`；只有`aborted_never_materialized` owner可满足上述`verified_not_acquired`全套historical negative ownership observations。`materialization_possible`且无durable lease、或ledger malformed/missing/legacy/corrupt/drifted时，无论current stable-zero如何均返回`cleanup_pending/indeterminate`。`shared_server_retained`可作为通用observer状态，但 C 的benchmark terminal gate只接受与ledger/lease状态相容的`verified_exact_process_exited`或`verified_not_acquired`；因此acquired benchmark tests和未来actual run必须使用isolated owner，不把ambient/shared server冒充zero residue。

只有B1 operation anchor CAS成功后，C才经同一Registry调用`prepare_benchmark_provider_acquisition()`；它用anchored reservation内durable `model_request_id`调用production“prepare acquisition owner”窄primitive，只写acquisition intent/runtime owner并在同一production lock内创建`prepared_never_materialized` ledger，不创建lease/process/listener/Job、不加载profile/provider。C先以第二个expected-revision CAS把这两个refs与B1 anchor并列封存，再允许B1 launch；因此pre-anchor CAS lost/cancel/stale只走B1 abort receipt，B1无需观察或终止B2 owner。Crash在anchor CAS后、B2 prepare前时，fresh C从anchored reservation重试同一production prepare；crash在B2 prepare后、refs CAS前时，production prepare idempotently返回同一owner bytes并验证同一ledger bytes后再完成CAS。Cancel在materialization transition前的这些cuts，必须先确保同一owner refs已durable封存，再与launch transition在同一cross-process acquisition lock内single-winner地提交`aborted_never_materialized`，然后才取得byte-identical `verified_not_acquired`；在owner refs落盘前不能签cancel terminal。若phase声称owner prepared但refs或ledger missing/漂移则保持pending，不能事后补造。normal path：每个benchmark Qwen materialization/adoption入口先durably提交`materialization_possible`，再允许首个Process/listener/Job side effect；benchmark worker handler完成且existing lease release结束后，worker entry调用production observer，把现有exact-shape `verified_exact_process_exited` receipt写入result reserved evidence，Registry A primitive只投影其SHA ref。abnormal path：B1 supervisor先固定outer-worker cancel intent，再用durable `model_request_id`调现有exact cancel/release；仅当abort赢得`prepared_never_materialized` transition时走production aborted-acquisition owner/tombstone并观察`verified_not_acquired`；materialization transition已提交但尚无durable lease时保持`cleanup_pending/indeterminate`，lease已取得时只观察`verified_exact_process_exited`，重复调用只返回同一state-compatible receipt或pending。Registry journal只保存receipt/ref，不复制或改写truth。Fresh Registry从worker owner journal + Qwen sidecar/materialization ledger恢复，无需raw payload或live process handle。

- [ ] **RED 1 — production sidecar:** real harmless test-owned Qwen-compatible process、真实 lease state/socket/Job 走 existing acquire/release；要求 sidecar由production writer生成，observer返回 exact process exit且三次stable-zero。测试不可patch observer或直接写receipt。
- [ ] **RED 2 — compatibility:** release前后existing owner tombstone bytes/schema、`cancel_model_request()` public response和nonbenchmark model lifecycle assertions保持不变；新增sidecar不进入API response。
- [ ] **RED 3 — cancel/acquisition crash matrix:** 用fresh Registry分别覆盖pre-gate（已有parent-prepared acquisition intent/runtime owner但无lease）、post-gate/pre-acquire、materialization transition提交前后、acquire-intent durable、lease-acquired、request in flight、body complete、release started、tombstone written、sidecar written；所有pre-materialization abort cuts最终byte-identical `verified_not_acquired`，`materialization_possible`已提交但无durable lease的cuts即使verified cleanup/current stable-zero仍保持`cleanup_pending/indeterminate`，acquired cuts最终`verified_exact_process_exited`。另以删除/漂移intent或ledger的负控证明missing/legacy/corrupt/drifted evidence始终pending；全矩阵不启动replacement provider/worker。
- [ ] **RED 4 — no fake proof:** PID alone、`request_not_active`、missing/edited sidecar、wrong request/acquisition-intent/runtime-owner/tombstone/lease/incarnation/socket/Job、PID reuse、listener残留、lease仍active、曾owned process却声称not-acquired、shared server、test-authored mapping全部不能使benchmark cleanup verified；两个outcome字段互换也FAIL。
- [ ] **RED 5 — ledger lineage/atomic observer:** 锁定revision-0 prepare与两个互斥revision-1 heads的exact canonical bytes、predecessor和byte-identical replay；reversal、conflicting transition、request/owner/intent substitution、missing/wrong predecessor、revision gap、stale rollback、timestamp/extra field、malformed/missing/legacy ledger均FAIL或pending且zero terminal receipt。并用instrumented production locks断言`_qwen_acquisition_lock()`→`_qwen_lease_lock()`唯一顺序，强制mixed-revision/non-coherent snapshot返回pending/retry，不能由current stable-zero补签。
- [ ] **Run RED:** `uv run pytest -q tests/test_model_request_cancellation.py tests/test_learning_workflow_stage_worker.py -k "qwen_cleanup_sidecar or benchmark_provider_cleanup"`。
- [ ] **GREEN 1:** 实现sidecar write/read/closed verifier并保持existing tombstone/response不变。
- [ ] **Run GREEN 1:** `uv run pytest -q tests/test_model_request_cancellation.py -k "qwen_cleanup_sidecar or owner_tombstone or request_cancellation"`。
- [ ] **GREEN 2:** 将benchmark-only normal result evidence与abnormal Registry reconciliation接到同一production observer；A 的 provider ref变为non-null且与sidecar SHA exact相等。
- [ ] **Run GREEN 2:** `uv run pytest -q tests/test_learning_workflow_stage_worker.py -k "completed_result_identity or benchmark_provider_cleanup or qwen" && uv run pytest -q tests/test_model_request_cancellation.py -k "qwen" && uv run python -m py_compile app/core/model_server.py app/learn/workflow_worker.py && git diff --check`。

**Cleanup:** 测试 finally通过exact lease/request/Job owner执行production release/reconcile；随后断言worker PID、Qwen PID-create-time、socket listener、Job member、lease state、临时handle为零。Sidecar保留在tmp lease root供restart验证，测试结束才删除tmp root。

**Independent review gate:** reviewer不得接受fake/test-only helper output；必须从production ledger/owner/lease/sidecar与raw OS observation按`_qwen_acquisition_lock()`→`_qwen_lease_lock()` coherent snapshot手工重建三个authoritative branches并逐项对照exact ledger lineage：① revision-1 `aborted_never_materialized`加historical never-owned lineage是唯一可签`verified_not_acquired`的路径；② revision-1 `materialization_possible`但无durable lease是mandatory pending negative control，cleanup/current stable-zero后仍不得签任何terminal receipt；③ acquired lease只能在exact process/incarnation termination、socket listener zero与Job stable-zero evidence齐全后签`verified_exact_process_exited`。Reviewer还必须演示一个mixed-revision或wrong-predecessor snapshot只返回pending/retry，并确认cleanup receipt fields/outcomes、owner tombstone bytes/schema与public cancel response未变；输出 `task-10b-slice-6-prerequisite-b2-review.md`。

**Commit:** `feat(model-server): retain exact qwen cleanup receipt`

---

### Task 6 Amendment C: Durable incumbent cut-point and complete panel compatibility surface

**Depends on:** A、B1、B2及三份独立review全部 PASS。此 task 替代原 Task 6 brief 中“五入口”和缺失pre-adopt/cleanup primitive的假设；其余 Task 6 success criteria继续有效。

**Allowed files:**
- Create `app/learn/hybrid/benchmark_v2_incumbent_operation.py`
- Modify `app/learn/hybrid/benchmark_v2_provider_corpus.py` only to expose an opaque resolver over the already validated production corpus singleton; no corpus bytes/schema/partition change
- Modify `app/learn/workflow_service.py`
- Modify `app/api/panel.py`
- Create `tests/test_portfolio_hybrid_v1_1_benchmark_v2_incumbent.py`
- Modify `tests/test_learning_workflow_stage_execution.py` only for guarded dependency seam、八入口 byte/semantic compatibility和static no-direct-Registry assertions

**Composition and complete interfaces:** 保留 canonical Task 6 的 `BenchmarkV2IncumbentWorkflowService` 与 `get_production_benchmark_v2_workflow_service()`，并冻结一个pair object，禁止分别传递可能错配的store/Registry：

```python
@dataclass(frozen=True)
class LearningWorkflowServiceComposition:
    store: LearningWorkflowRunStore
    worker_registry: LearningStageWorkerRegistry
    project_root: Path
    composition_kind: Literal["production", "test"]
    benchmark_supervision_root: BenchmarkWorkerSupervisionRoot | None
    provider_case_resolver: object | None

def get_production_learning_workflow_service_composition(
) -> LearningWorkflowServiceComposition:
    pass

def compose_test_learning_workflow_service(
    *, store: LearningWorkflowRunStore,
    worker_registry: LearningStageWorkerRegistry,
    project_root: str | Path,
    benchmark_supervision_root: BenchmarkWorkerSupervisionRoot | None = None,
    provider_case_resolver: object | None = None,
) -> LearningWorkflowServiceComposition:
    pass

def start_guarded_learning_stage_worker(
    *, composition: LearningWorkflowServiceComposition,
    run_id: str, expected_revision: int, stage: str, operation_id: str,
    task_kind: str, payload: Mapping[str, object],
    reuse_active_identical: bool = False,
) -> dict[str, Any]:
    pass

def status_guarded_learning_stage_worker(
    *, composition: LearningWorkflowServiceComposition,
    worker_id: str, run_id: str, operation_id: str,
) -> dict[str, Any]:
    pass

def adopt_guarded_learning_stage_worker_result(
    *, composition: LearningWorkflowServiceComposition,
    worker_id: str, run_id: str, expected_revision: int,
    stage: str, operation_id: str,
) -> dict[str, Any]:
    pass

def continue_guarded_learning_stage_worker_result(
    *, composition: LearningWorkflowServiceComposition,
    run_id: str, expected_revision: int, stage: str,
    operation_id: str, worker_id: str, now: datetime | None = None,
) -> dict[str, Any]:
    pass

def cancel_guarded_learning_workflow_stage_operation(
    *, composition: LearningWorkflowServiceComposition,
    run_id: str, expected_revision: int, stage: str,
    operation_id: str, reason: str, now: datetime | None = None,
) -> dict[str, Any]:
    pass

def heartbeat_guarded_learning_workflow_stage_operation(
    *, composition: LearningWorkflowServiceComposition,
    run_id: str, expected_revision: int, stage: str,
    operation_id: str, lease_seconds: int = 600,
    now: datetime | None = None,
) -> dict[str, Any]:
    pass

def finish_guarded_learning_workflow_stage_operation(
    *, composition: LearningWorkflowServiceComposition,
    run_id: str, expected_revision: int, stage: str,
    operation_id: str, outcome: str, reason: str = "",
    evidence_refs: Mapping[str, object] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    pass

def recover_guarded_learning_workflow_stage_operation(
    *, composition: LearningWorkflowServiceComposition,
    run_id: str, expected_revision: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    pass

def project_guarded_learning_workflow_runtime_attachment(
    *, composition: LearningWorkflowServiceComposition,
    workflow_state: Mapping[str, object],
) -> dict[str, Any]:
    pass
```

Production composition getter lazy-bind且稳定返回exact module singleton pair、B1 production supervision root/factory capability和由已validate provider-corpus singleton创建的opaque production case resolver；root内部store authority必须exact绑定该pair的同一store singleton，否则composition构造即FAIL。它不是per-operation authority，不接受caller dependency/path/case mapping override。每次operation的anchor/source都只能来自该composition的store current document和resolver current validated singleton。Test constructor只接受显式tmp pair；默认`benchmark_supervision_root=None,provider_case_resolver=None`，因此只能测nonbenchmark compatibility。需要测benchmark时必须同时传B1 `test_only` root（其read-only authority exact绑定同一test store）与由同一test validated corpus产生的opaque test resolver；单传一个、cross-store/root/resolver/corpus substitution、production/test混搭全部FAIL。所得contract/name/journal root与production disjoint，且任何panel production branch拒绝test composition。Panel可保留store/Registry monkeypatch aliases，但先一次性组装pair再传wrapper；callee/helper与endpoint都不得直接调用Registry method。

**Return and exception contracts:** nonbenchmark return必须是现有callee返回dict的deep-equal value，不增加wrapper字段：start/status是Registry public record；adopt是generic adoption；continue/heartbeat/finish/recover/runtime attachment是现有service dict；cancel是现有cancel dict并保留`worker_termination`。Exception集合和precedence固定为：start=`LearningStageWorkerError | LearningWorkflowStageOperationError | LearningWorkflowTransitionError`；status=`LearningStageWorkerError`；adopt同start；continue=`LearningStageWorkerContinuationError | LearningStageWorkerError | LearningWorkflowEvidenceError | LearningWorkflowStageOperationError | LearningWorkflowTransitionError`；cancel同start；heartbeat/recover=`LearningWorkflowStageOperationError | LearningWorkflowTransitionError`；finish先`LearningWorkflowEvidenceError`，再stage/transition；runtime attachment保持现有projection的exception/return语义。Benchmark internal pending/SAFE_STOP使用`LearningWorkflowStageOperationError`，不得引入新panel exception class。所有九个wrapper只能从同一个`LearningWorkflowServiceComposition`取store/Registry/root；production无dependency参数，test只能通过上述pair constructor注入，不能单独替换某一callee。

**Closed durable schemas:** `stage_execution["benchmark_v2_incumbent"]`只接受 `benchmark_v2_incumbent_operation_v1`。Exact fields固定为：

| Field | Closed value |
|---|---|
| `contract_version` | literal `benchmark_v2_incumbent_operation_v1` |
| `mode` | literal `benchmark_v2_incumbent_single_observe` |
| `run_id,stage,operation_id` | 与active store operation exact相等的nonempty strings |
| `operation_anchor_ref` | exact `{"content_sha256": lower_sha256}` |
| `reservation_ref,supervision_inputs_ref,expected_supervision_ref` | B1 closed one-key refs；prepared起均non-null且与store operation anchor exact相等 |
| `acquisition_intent_ref,runtime_owner_ref` | B2 production prepared-owner closed refs；`prepared`时均null，`provider_owner_prepared`起均non-null |
| `prepared_revision,current_document_revision` | nonnegative int；每次CAS exact predecessor+1 |
| `task_kind` | literal `vision_observe_screen` |
| `handler_payload_source,handler_payload_source_ref,handler_payload_sha256` | full closed source document及其ref从B1 reservation exact复制并贯穿anchor/supervision；lower SHA-256必须等于source；source不含case mapping/raw payload |
| `window_binding_ref,capture_ref` | Task5 closed refs |
| `execution_nonce` | B1 32-char lowercase hex |
| `phase` | `prepared|provider_owner_prepared|worker_starting|worker_bound|result_ready|terminal_intent|adopted|cancel_intent|cleanup_pending|complete|cancelled|safe_stopped` |
| `worker_ref` | exact closed `worker_id,model_request_id,payload_sha256,execution_nonce,reservation_ref,supervision_ref`；prepared起non-null，`supervision_ref`可在launch前为null |
| `result_identity_ref` | null或A exact snapshot mapping |
| `window_adoption_ref` | null或Task5 rebuild ref |
| `worker_cleanup_ref` | null或B1 receipt ref |
| `provider_cleanup_ref` | null或B2 sidecar receipt ref |
| `terminal_intent,cancel_intent` | 互斥；只允许下述closed mapping或null |
| `generic_adoption_ref` | null或Registry adoption receipt ref，SHA必须等于A |
| `terminal_receipt` | null或下述closed terminal mapping |
| `predecessor_content_sha256,content_sha256` | predecessor为首document时null，否则lower SHA；current SHA按canonical bytes重算 |

`benchmark_v2_incumbent_terminal_intent_v1` exact fields为 `contract_version,run_id,stage,operation_id,worker_id,model_request_id,payload_sha256,result_sha256,normal_binding_evidence_ref,provider_cleanup_evidence_ref,worker_cleanup_evidence_ref,intent_revision,intent_at,predecessor_content_sha256,content_sha256`。`intent_at`只在winning CAS前生成一次并持久化。

`benchmark_v2_incumbent_cancel_intent_v1` exact fields为 `contract_version,run_id,stage,operation_id,worker_id,model_request_id,payload_sha256,execution_nonce,reservation_ref,operation_anchor_ref,acquisition_intent_ref,runtime_owner_ref,process_identity,scope_name,assignment_proven_ref,reason,intent_revision,intent_at,predecessor_content_sha256,content_sha256`。prelaunch/gate前允许后三个B1 process fields为null；reservation与anchor必须non-null。B2 acquisition refs在正常prepared owner上non-null；为durably记录损坏/旧状态的cancel可为null，但此时必须保持cleanup pending，不能terminal cancelled或补造owner。

`benchmark_v2_incumbent_terminal_receipt_v1` exact fields为 `contract_version,outcome,run_id,stage,operation_id,worker_id,model_request_id,payload_sha256,result_sha256,terminal_intent_ref,cancel_intent_ref,generic_adoption_ref,window_adoption_ref,worker_cleanup_ref,provider_cleanup_ref,provider_cleanup_outcome,terminal_at,artifact_is_authorization,execute_binding_enabled,predecessor_content_sha256,content_sha256`。`outcome`只能`benchmark_v2_incumbent_observe_complete|benchmark_v2_incumbent_cancelled`；complete要求terminal/result/adoption四ref非null、provider outcome=`verified_exact_process_exited`且cancel ref null；cancelled要求cancel/B1/B2三ref非null、terminal/result/adoption ref null，B2 closed receipt outcome只能是与materialization ledger/lease状态相容的`verified_not_acquired|verified_exact_process_exited`。`materialization_possible`但无durable lease时没有可供C转换的第三种receipt，必须保持`cleanup_pending`。两个provider outcomes互斥且不得由C转换。两个authorization booleans固定false。Terminal replay直接deepcopy persisted mapping，不重打timestamp或重算不同revision bytes。

**Closed transition table:**

| From | Event/required parents | To | Forbidden |
|---|---|---|---|
| absent | production resolver exact解析closed case ref → C source composer一次 → B1 identity reservation一次 → server CAS source/B1 anchor/reservation/expected supervision/Task5 refs → B1 anchor confirmation | `prepared` | caller case mapping/raw payload、CAS失败后无store-authoritative B1 abort receipt、未confirm却继续、spawn/lease/provider、second source/reservation |
| `prepared` | B2 acquisition owner一次（zero provider）+ production ledger=`prepared_never_materialized` → CAS exact owner refs | `provider_owner_prepared` | launch、lease/provider、self-minted absent-owner proof |
| `provider_owner_prepared` | fresh store source ref → current production resolver sealed case → literal projection/Task5 capture → B1 launch以store expected supervision ref启动exact once | `worker_starting` | old/caller case mapping、wrong corpus/case/rules/source、client/journal/raw payload、different worker/nonce |
| `worker_starting` | exact one Registry worker + assignment_proven | `worker_bound` | second/different worker |
| `worker_bound` | A snapshot + B1/B2 refs available | `result_ready` | interpreter/next worker |
| `result_ready` | winning complete CAS | `terminal_intent` | simultaneous cancel intent |
| `terminal_intent` | Registry adopt SHA=A | `adopted` | adopt different result |
| `adopted` | Task5 rebuild + B1/B2 verified | `complete` | caller evidence替换 |
| `prepared|provider_owner_prepared|worker_starting|worker_bound|result_ready` | winning cancel CAS；prepared先幂等完成B2 owner refs | `cancel_intent` | simultaneous terminal intent、missing owner terminal proof |
| `cancel_intent` | one or both cleanup receipts pending | `cleanup_pending` | cancelled terminal |
| `cancel_intent|cleanup_pending` | B1 verified + B2 state-compatible `verified_not_acquired`或`verified_exact_process_exited` | `cancelled` | missing/drifted materialization ledger、materialized-without-lease、missing acquisition intent、result adopt/continuation |
| any nonterminal | ref drift/ambiguity/unobservable ownership | `safe_stopped` | replacement worker或自动恢复到running |
| `complete|cancelled|safe_stopped` | any wrapper/restart/recover | same byte-identical state | revision increment/side effect |

每次running→running CAS必须复制所有已有refs和predecessor；不在表内的edge拒绝且revision不变。`terminal_intent xor cancel_intent` invariant在每次load和write前重验。

**Guarded wrapper exact call order/call-count contract:**

| Wrapper | Exact successful order | Failure call count and side effect |
|---|---|---|
| start | stage active-operation/revision precheck once → nonbenchmark `Registry.start` once；benchmark在同controller guard内production resolver closed case-ref resolve once → source compose once → B1 identity prepare once → store source+B1 anchor CAS once → B1 anchor confirmation once → B2 acquisition-owner prepare once → store owner-ref CAS once → current store source-ref/current resolver/Task5重建authoritative payload once → B1 launch once → stage current-operation postcheck once | precheck fail：resolver/source/Registry/store/launch=0；case/source fail：prepare/store/owner/launch=0；identity prepare fail：store/owner/launch=0；anchor CAS conflict且fresh B1 decision证实closed absent predicate：B1 pre-anchor abort once且C只消费receipt，owner/launch=0；CAS I/O/ambiguous但same revision/op anchor absent：abort=0并重试CAS；CAS success/confirmation前crash：fresh abort见matching anchor必须拒绝，再只confirm；confirmation fail：owner/launch=0；owner prepare或owner-ref CAS fail：anchor保留prepared、launch=0并fresh幂等resume；resolver/source/payload重建或validation fail：launch side effect=0；launch fail：不得second launch；postcheck fail：已启动generic worker时exact compensating `Registry.cancel` once，benchmark按anchored cancel状态机清理，随后抛原stage/transition error |
| status | `Registry.status` once | worker error后store/stage=0；valid Registry status不得被store missing抢先覆盖 |
| adopt | stage active-operation/revision precheck once → `Registry.adopt_result` once | precheck fail：adopt=0；adopt fail：stage mutation/continuation=0；无postcheck/compensating adoption |
| continue | continuation precheck/loader once → Registry inspection/adoption primitives按既有callee exact once → evidence validation once → stage transition once | 任一步失败时后续call=0；已存在generic adoption按既有idempotency replay，不新增compensation或next worker |
| cancel | active-operation/revision precheck once → Registry cancel once → stage cancel transition once | precheck fail：Registry=0；Registry fail：stage cancel=0；stage fail保留既有worker termination result且不重发第二cancel；benchmark intent cleanup按durable replay |
| heartbeat | stage heartbeat once | failure无Registry/store外额外mutation；intent/terminal precheck拒绝时heartbeat call=0 |
| finish | evidence validation once → stage finish once | evidence fail：stage=0；stage/transition fail不重跑evidence writer或Registry |
| recover | stage recovery once | failure无Registry call、worker spawn/cancel或额外CAS |
| runtime attachment | existing pure projection once | composition mismatch在projection前fail；Registry/store mutation=0 |

start的benchmark two-step是现有start语义内的受控替代；outer controller guard跨越全部步骤，外层顺序严格为`stage precheck → production resolver case-ref validation → source compose → Registry identity prepare → store source+anchor CAS / [仅冲突时root-bound fresh store decision→Registry abort] → Registry anchor confirmation → B2 owner prepare → store owner refs → current resolver authoritative payload rebuild → Registry launch → stage postcheck/compensation`；abort子序严格`service RLock→controller mutex→store get/decision→Registry lock`，绝不Registry lock→store；adopt严格为`stage precheck → Registry`。任何实现或测试不得采用worker→stage顺序。

**Panel API compatibility/error precedence matrix:**

| Entry | Success message / data | Error precedence and exact existing code |
|---|---|---|
| start worker | `Learning stage worker started` / existing Registry record | stage/transition precheck→Registry→stage/transition postcheck；失败均映射`learning_stage_worker_start_invalid`，postcheck失败执行上述exact一次compensation |
| status | `Learning stage worker status` / existing public record | worker only, `learning_stage_worker_status_invalid`；store missing不能抢先覆盖valid Registry status |
| adopt | `Learning stage worker result adopted` / existing adoption | stage/transition precheck→Registry adopt；失败映射`learning_stage_worker_result_adoption_invalid`，precheck失败adopt call count=0 |
| continue | `Learning stage worker result continued` / existing continuation | continuation→worker→evidence→stage→transition, `learning_stage_worker_result_continuation_invalid` |
| cancel | `Learning workflow stage operation cancelled` / existing cancel + `worker_termination` | active-operation check→worker cancel→stage cancel；worker→stage→transition, `learning_workflow_stage_operation_cancel_invalid` |
| heartbeat | `Learning workflow stage operation heartbeat accepted` / existing result | stage→transition, `learning_workflow_stage_operation_heartbeat_invalid` |
| finish | `Learning workflow stage operation finished` / existing result | evidence first=`learning_workflow_evidence_invalid`; otherwise stage→transition=`learning_workflow_stage_operation_finish_invalid` |
| recover | `Learning workflow stage operation recovery checked` / existing result | stage→transition, `learning_workflow_stage_operation_recovery_invalid` |
| runtime attachment | existing projection dict | no API envelope change；composition mismatch fail closed before Registry access |

Compatibility RED每行至少覆盖success、每个列出的异常点、stale revision、not-found/invalid operation与backend/callee error；status额外覆盖store missing但Registry valid的旧precedence，finish额外覆盖evidence优先，start独立覆盖precheck/Registry/postcheck/compensation，adopt独立覆盖precheck/Registry。断言完整`APIResponse.model_dump()` bytes、exact callee call count/order、异常映射和无额外store/Registry mutation，不只比较error code。

**Fixed lock/order:** 所有路径先取`(id(store),run_id,operation_id)` RLock，再取得并跨完整start orchestration持有B1 controller guard；B1调用内部最后取Registry lock，任何Registry lock内不得回调store。Start顺序为store precheck→production resolver验证case ref并compose source→B1 identity reservation→store source+anchor CAS；只有fresh root-bound store authority判定closed CAS conflict/cancel/stale且matching anchor absent时，abort按controller→store get/decision→Registry lock执行；matching anchor存在则abort拒绝并fresh confirm，同revision/op anchor absent则重试CAS→B1 anchor confirmation→B2 acquisition-owner prepare→store owner-ref CAS→fresh store source/current resolver/Task5 payload rebuild→B1 launch→store postcheck/compensation；每次Registry call结束只释放internal lock/reentrant mutex level，outer controller guard仍持有，最终durable launch/abort/compensation后才release/close。Adopt为store precheck→Registry adopt，无postcheck。Fresh B1 observer没有service RLock时仍必须先取同一controller mutex。Restart/recover若先缺operation ID，只能在lock-map guard下读取active operation，取得exact operation lock和controller guard后重新读取并CAS。

**Complete:** A inspection → 将A current SHA与store-anchored reservation/expected supervision、Task5 server binding/adoption parent、B1 assignment/cleanup和B2 production sidecar parent联合验证 → CAS terminal intent → exact `adopt_result()`并要求SHA一致 → Task5 server adoption rebuild → CAS terminal receipt。**Cancel:** CAS cancel intent（包含reservation/anchor、可空B1 process identity与B2 request/acquisition owner refs）→ B1 `verified_not_launched|verified_exact_worker_exited` + B2 state-compatible `verified_not_acquired|verified_exact_process_exited`的合法组合 → CAS cancelled receipt。B2仅在ledger=`aborted_never_materialized`时允许not-acquired，已lease时必须exact-process-exited；ledger=`materialization_possible`但无durable lease时即使cleanup/current stable-zero也保持pending。状态与outcome不匹配FAIL。任一cleanup、missing intent或missing/legacy/corrupt/drifted ledger evidence保持intent pending。Terminal replay只读persisted canonical receipt。

- [ ] **RED 1 — eight-entry race:** start/status/adopt/continue/cancel/heartbeat/finish/recover与specialized terminalizer并发竞争；complete/cancel intent恰一winner，finish/recover不得覆盖，status不得旁路composition，heartbeat在intent后revision不变。
- [ ] **RED 2 — crash cuts:** complete 的 inspection/intent/adopt/Task5 rebuild/terminal及cancel的intent/outer cleanup/provider cleanup/terminal每个cut crash+fresh composition；只resume同一worker/result/receipt，byte-identical replay，zero new worker/provider。
- [ ] **RED 3 — provenance/source/remint:** 手工result path read、self-minted SHA、PID/is_alive、request_not_active、fake cleanup mapping、wrong provider corpus file/content、case ID/content、projection rules/source/default/capture/predecessor、provider_mode `qwen|local|local_grounding|api|null`、Task5 binding/Qwen/Job/operation-anchor/expected-supervision ref、caller provider-case mapping replay全部FAIL；fresh restart必须丢弃caller/old service并由current store source document/ref+current production resolver重建exact payload。Same-identity合法self-hash remint使A报告changed current SHA，但C把它与store-anchored Task5/B1/B2 parent chain联合时必须FAIL。此fixture只在A/B1/B2已GREEN后存在，不回灌A slice。
- [ ] **RED 4 — no cascade/no action:** generic interpreter、`_ensure_next_managed_stage_operation`、`_start_next_managed_stage_worker`、next-worker和specialized continuation mutation count都为零；无 action/Runtime/click/publish import或artifact authority。
- [ ] **RED 5 — compatibility:** 按上表逐入口覆盖success、stale revision、not-found/invalid operation、每个backend/callee error和明确precedence；start exact验证precheck→Registry prepare/launch→postcheck/compensation，adopt exact验证precheck→Registry。Tracked incumbent/Hybrid完整`APIResponse.model_dump()` bytes、callee order/count、side effects与continuation graph等于pre-amendment fixture。Static AST/callgraph scan同时覆盖panel endpoint、panel helper与workflow-service wrapper/callee，确认除single composition owner外无direct Registry method call。
- [ ] **RED 6 — cancel before lease:** fresh composition在pre-gate、post-gate/pre-acquire、materialization transition前后、acquisition-intent、lease-acquired cuts分别恢复；pre-materialization abort winner最终消费byte-identical B2 `verified_not_acquired`，`materialization_possible`已提交但无durable lease时保持pending，lease-acquired消费`verified_exact_process_exited`，B1按launch state消费对应receipt；missing intent或missing/legacy/corrupt/drifted ledger evidence保持pending，zero replacement worker/provider，terminal replay byte-identical。
- [ ] **Run RED:** `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_incumbent.py tests/test_learning_workflow_stage_execution.py -k "benchmark_v2 or guarded or incumbent or hybrid or payload_projection or managed_qwen_mode"`。
- [ ] **GREEN 1:** 实现closed durable document、single getter、shared lock和pure-fake CAS/race state machine。
- [ ] **Run GREEN 1:** `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_incumbent.py -k "document or lock or intent or replay"`。
- [ ] **GREEN 2:** 接八个guarded wrappers、panel wiring与compatibility seam；先通过nonbenchmark equivalence再启用benchmark branch。
- [ ] **Run GREEN 2:** `uv run pytest -q tests/test_learning_workflow_stage_execution.py -k "incumbent or hybrid or guarded"`。
- [ ] **GREEN 3:** 接A inspection、B1/B2 cleanup与Task5 adoption，完成real Registry/spawn + harmless recorded Qwen response E2E；不运行真实model inference。
- [ ] **Run GREEN 3:** `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_incumbent.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_worker_binding.py tests/test_learning_workflow_stage_worker.py tests/test_model_request_cancellation.py tests/test_learning_workflow_stage_execution.py -k "benchmark_v2 or incumbent or hybrid or qwen or payload_projection or managed_qwen_mode" && uv run python -m py_compile app/learn/hybrid/benchmark_v2_incumbent_operation.py app/learn/hybrid/benchmark_v2_provider_corpus.py app/learn/workflow_service.py app/api/panel.py && git diff --check`。

**Cleanup:** E2E outer finally依次resume pending intent、exact provider cleanup、exact worker cleanup、Task4 window cleanup、store close；最终独立扫描 PID-create-time/Job/socket/listener/lease/HWND/handle 全部为零。若cleanup indeterminate，test必须FAIL并保留journals，不能删除证据后报PASS。

**Independent review gate:** reviewer trace生产 singleton composition、八入口同锁、A→intent→adopt、cancel→B1/B2、每个crash cut、Task5 provenance、no-cascade与compatibility；输出原约定 `task-10b-slice-6-review.md`。Critical/Important为零后才允许 Task 7。

**Commit:** `feat(benchmark-v2): terminalize incumbent after qwen observe`

---

## Task 7 alignment: consume journals, do not duplicate lifecycle

Task 7 的 `verify_lifecycle_from_raw()` 输入必须将下列production journals当作唯一 owner/cleanup parents：

- B1 reservation/operation-anchor/expected-supervision chain、scope assignment observation、raw handle-close observations与normal/abnormal/not-launched worker cleanup receipt；
- B2 Qwen acquisition-intent/runtime-owner/monotonic materialization ledger/lease state ref、aborted或released owner tombstone、state-compatible `verified_not_acquired|verified_exact_process_exited` sidecar与适用的scope/listener stable-zero receipt；materialized-without-lease没有terminal receipt并保持pending；
- Task 4 exact window owner/finalization journals；
- Task 5 binding normal-clear/adoption refs；
- raw `nvidia-smi` transcripts 与 OS PID create-time samples。

Task 7 只验证 lineage、时间区间、owned multiset、VRAM与probe coverage，输出derived verifier receipt；它不得重新assign/terminate owner、重新读取worker result、调用Qwen release、把missing journal填成zero、或创建平行 cleanup receipt。Task 7 tests使用A/B生成的fixture journals，篡改predecessor、跨operation混合、sidecar缺失、outer cleanup missing、PID reuse与duplicate owner都FAIL。

Task 7 的 RED/GREEN命令在 canonical plan 基础上追加：

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle.py tests/test_learning_workflow_stage_worker.py tests/test_model_request_cancellation.py -k "lifecycle or benchmark_worker or qwen_cleanup_sidecar"
```

## Final amendment acceptance

- [ ] A/B1/B2/C 每个slice均有独立 commit、fresh tests、独立review；不得squash成无法单独审查的giant diff。
- [ ] Canonical Task 6 不再引用“五入口”，而是exact八入口+runtime attachment seam。
- [ ] 任何 result/cleanup proof 都能追到 Registry、production model_server或raw OS journal；service/tests没有self-mint。
- [ ] A的claim只覆盖current validated envelope locked snapshot；same-identity semantic remint只由Task5/B1/B2/C parents拒绝。
- [ ] C production resolver先从validated corpus+Task5 refs生成closed handler-payload source；B1 reservation原子封存source且只读inspection可恢复pre-anchor crash；source→identity reservation→store operation anchor/parent-independent expected supervision→B2 zero-provider acquisition owner→fresh current-resolver authoritative-payload launch协议无source/worker/nonce/parent-restart cycle、最多一次spawn；raw case/payload不持久化，fresh observer以store source/expected supervision refs再验证actual parent owner。
- [ ] B1 root-bound read-only store authority exact绑定production/test store；public pre-anchor abort按controller→fresh store decision→Registry lock且仅允许matching anchor absent的三个closed predicates下`reserved→aborted_before_anchor`，decision/absence/predecessor/byte replay通过；matching anchor存在必拒绝并fresh confirm，same revision/op absent只重试CAS；C/caller不self-mint store/zero-spawn/provider truth。
- [ ] B1 per-operation production/test controller mutex覆盖prepare/launch/abort/Job reopen/cleanup observer；literal 5000ms timeout、real dual/abandoned helper、same-thread recursion、pre/post-mutation ReleaseMutex/CloseHandle combined diagnostics、recovery_required和Registry-lock→store prohibition RED通过。
- [ ] B1 `assignment_proven`和`cleanup_finalization_intent`顺序、Job可重开/same-live retry/dead-supervisor inference/pre-assignment recovery branches、raw real handle observations与real outer-parent termination/receipt-stage crash matrix通过。
- [ ] B1 production/test root capability、scope namespace/name formula和closed operation anchor全部closed且disjoint，composition不持有per-operation authority。
- [ ] B2 internal `qwen_model_request_materialization_ledger_v1` exact九字段、deterministic revision-0 prepare、单一predecessor-bound revision-1 abort/launch、byte-identical replay与substitution/reversal/conflict/gap/rollback/malformed rejection通过；production prepare在同一cross-process acquisition lock下创建`prepared_never_materialized`，abort/launch single-winner地单调转为`aborted_never_materialized|materialization_possible`，且后者在cleanup/failure/restart后不可逆。Observer固定`_qwen_acquisition_lock()`→`_qwen_lease_lock()`并只消费coherent snapshot；mixed revision保持pending/retry。只有historical never-owned的aborted state可由production owner/tombstone签`verified_not_acquired`，materialized-without-lease不得签terminal receipt，acquired path仅在exact-process cleanup evidence后签现有exact-shape `verified_exact_process_exited`；missing/legacy/corrupt/drifted ledger evidence保持pending，receipt/tombstone/cancel public schemas不变。
- [ ] C九wrapper signatures、store/root/resolver test-pair injection、source/operation/intents/receipt schemas、transition table与API error precedence/call-count/side-effect matrix逐项通过；start为precheck→resolver/source→Registry→postcheck/compensation，adopt为precheck→Registry。
- [ ] spawn claim明确限定为pre-handler/provider gate，不夸大为OS suspended interpreter launch。
- [ ] nonbenchmark incumbent/Hybrid compatibility fresh tests通过。
- [ ] actual/provider/holdout/action仍未执行。
- [ ] Task 7消费A/B journals而不重复lifecycle ownership。

## Round 1 amendment review fix evidence

Consumed review: `.superpowers/sdd/2026-08-25-portfolio-hybrid-v1-1-implementation-plan/task-10b-task6-amendment-review.md`。本节是planning-only fix report；未授权或执行source/test/actual/provider/holdout/action。

| Review finding | Planning closure in this revision |
|---|---|
| Critical C1 Job lifetime | B1新增durable `assignment_proven`和handle-close前`cleanup_finalization_intent`；restart冻结Job可重开、assignment-proven后Job absent+exact incarnation absent、pre-assignment absent三分支；真实outer-parent termination覆盖assignment/gate/stable-zero/Job-close/receipt-replace cuts。 |
| Important I1 A overclaim | A限定为Registry lock内同一次validated envelope exact-byte snapshot；删除A拒绝same-identity semantic remint的不可证明谓词，明确由Task5/B1/B2/C parent evidence下游拒绝。 |
| Important I2 authority/name | B1冻结`benchmark_worker_supervision_v1`、production/test opaque authority、server operation anchor、execution nonce与独立`benchmark_worker_scope_name_v1`公式，并加入substitution/collision/full-remint negatives。 |
| Important I3 DAG/release drift | Canonical exact DAG改为Task5→A→B1→B2→C/Task6→Task7；Task12 manifest加入五份reviews、production/test source SHA与direct result refs；final verification加入A/B direct selectors/modules。 |
| Important I4 C interface/schema | C冻结single composition/test-pair injection、九wrapper完整signatures/returns/exceptions、operation/intents/terminal receipt closed schemas、transition table和八入口APIResponse/error precedence matrix。 |
| Minor authority/handles | Canonical移除旧模糊supervisor签发措辞，统一为B1+B2+Task4；handle checks以exact owned handles为primary，global count仅diagnostic。 |

Planning verification evidence after this fix：strict UTF-8 decode PASS；LF/no BOM/replacement character PASS；placeholder/conflict-marker/trailing-whitespace scan PASS；required existing paths与heading order PASS；C1/I1-I4 required-closure assertion PASS；tracked `git diff --check` PASS；untracked amendment `git diff --no-index --check` PASS。只检查docs，没有运行pytest、source compile、process、UI、provider、actual、holdout或action。

Round 1修订仍需新的独立plan review PASS后才授权Prerequisite A；本fix report本身不把checkbox或review gate升级为PASS。

## Round 2 amendment review fix evidence

Consumed full review: `.superpowers/sdd/2026-08-25-portfolio-hybrid-v1-1-implementation-plan/task-10b-task6-amendment-review-round-2.md`。本节仅记录planning修正；未修改source/test，未运行pytest/process/UI/provider/actual/holdout/action，也不把任何slice或review gate升级为PASS。

| Round 2 finding | Planning closure in this revision |
|---|---|
| B1 same-live-parent receipt retry | Job-absent恢复拆为validated intent+raw real handle close observations的same-live-supervisor retry与fresh exact supervisor absence的dead-supervisor inference；process/Event/beacon/Job close success/error及receipt temp/write/flush/directory-fsync/replace分别RED。 |
| A cross-slice test dependency | A RED 4只证明changed current SHA和nonclaim；Task5/B1/B2联合remint rejection完整移入C RED 3/E2E。 |
| B1 root/anchor/nonce cycle | Composition只持有production root/factory capability；冻结closed operation anchor、reservation、parent-independent expected supervision与launch-time actual supervision schemas；采用Registry identity reservation→store anchor/expected supervision→B2 zero-provider owner→authoritative-payload launch，store后/launch前fresh parent无需remint，且定义每个crash/replay/cancel cut与fresh store-anchor observer。 |
| C compatibility order | Composition/test seam改用root capability；九wrapper冻结exact call order/count/side effects。Start严格stage precheck→Registry prepare/launch→postcheck/compensation，adopt严格precheck→Registry，APIResponse/error mappings保持既有值。 |
| B2 cancel before lease | Production acquisition owner在gate前只封存intent、zero provider并创建`prepared_never_materialized`；同一cross-process lock下abort/launch单winner，只有转为`aborted_never_materialized`的historical never-owned owner可签disjoint `verified_not_acquired`，转为`materialization_possible`后无lease也必须pending，acquired path只签existing `verified_exact_process_exited`；C cancelled只接受state-compatible B2 outcome，missing/legacy/corrupt/drifted evidence pending。 |
| exact owned handle truth | Registry是真实handle owner；`closed_explicitly`只源自production close call raw observation，`closed_by_verified_supervisor_exit`只源自fresh exact PID/create-time absence，journal字段与global count不构成proof。 |

Round 2 planning-only verification实际结果：strict UTF-8 decode PASS；LF/no BOM/replacement character PASS；placeholder/conflict marker/trailing whitespace PASS；referenced existing paths与heading order PASS；上述六项required-closure assertions PASS；tracked `git diff --check` PASS；untracked amendment `git diff --no-index --check` PASS。只有下一轮独立plan review关闭Critical/Important后，才可授权Prerequisite A；B1/B2/C仍按各自DAG review gate逐slice授权。

## B1 preflight critical closure evidence

Consumed preflight: `.superpowers/sdd/2026-08-25-portfolio-hybrid-v1-1-implementation-plan/task-10b-slice-6-prerequisite-b1-preflight.md`。本节只机械修正规划接口；未修改source/tests，未运行process/UI/provider/actual/holdout/action，未授权B1实施。

| Preflight finding | Mechanical plan closure |
|---|---|
| Critical C1 authoritative restart payload | `launch_prepared_benchmark_worker`新增server-owned mapping；Registry lock内canonical SHA exact匹配source/reservation/anchor并重验B1 reserved keys和Task5 binding/capture。Fresh service从current store source document/ref、current validated-corpus resolver与Task5 parents重建；client/journal/path/ref及raw-payload persistence全部禁止并有restart RED。 |
| Critical C2 missing abort transition | 新增public `abort_prepared_benchmark_worker_before_anchor`和closed receipt；限`reserved→aborted_before_anchor`、三个closed reasons、全absence observations、predecessor-linked atomic/idempotent replay，anchored及以后拒绝。Store CAS success后以同guard调用anchor confirmation；CAS/confirm crash由fresh store-read后confirm。C CAS-lost/cancel/stale只消费Registry receipt。 |
| Important cross-process controller race | 选择独立per-operation named mutex作为最小可验证authority；冻结production/test grammar、lock order、timeout、`WAIT_ABANDONED` fresh revalidation、raw handle release/close与双helper RED。Process-local RLock不再承担跨进程proof。 |

该closure不新增文件、不改变Task5→A→B1→B2→C/Task6→Task7 DAG，也不把payload或abort truth移入B2/C。完成本轮document checks后必须等待独立plan review；review PASS前不得开始B1 source/test实现。

B1 preflight planning-only checks：strict UTF-8/LF/no BOM/U+FFFD PASS；Markdown fence balance PASS；referenced existing paths PASS；两份plan docs scoped `git diff --check` PASS。未运行pytest/compile/process/UI/provider/actual/holdout/action。

## B1 round-1 closure review fix evidence

Consumed review: `.superpowers/sdd/2026-08-25-portfolio-hybrid-v1-1-implementation-plan/task-10b-slice-6-prerequisite-b1-plan-review.md`。本节仅记录planning修正；未修改source/tests，未运行pytest、process、UI、provider、actual、holdout或action，也未授权B1实施。

| Review finding | Mechanical closure in this revision |
|---|---|
| Critical C1 durable payload reconstruction | 冻结先于reservation的`benchmark_v2_incumbent_handler_payload_source_v1`、exact provider corpus/case/projection/Task5 refs和literal `ObserveScreenTaskInput` projection。Source ref贯穿reservation、anchor identity、expected/actual supervision与C document；production composition持validated-corpus opaque resolver，fresh restart丢弃caller/old service，从current store source ref重新resolve sealed case并重建payload。实现位置限定为既有`benchmark_v2_provider_corpus.py` resolver和C `benchmark_v2_incumbent_operation.py` composer，B1不新增文件。 |
| Critical C2 independent store-anchor absence | B1 production/test root绑定不可序列化read-only store authority，复用existing `LearningWorkflowRunStore.get`；abort内部在controller guard内先fresh store read/closed decision，再取Registry lock，只有matching-anchor absent且conflict/cancel/stale predicate成立才转移。Matching anchor存在拒绝并fresh confirm；same revision/op absent重试CAS；caller/C mapping/ref不能自证。 |
| Important I1 mutex semantics | Default timeout literal固定5000ms；WAIT_TIMEOUT exact exception/zero business mutation、WAIT_ABANDONED fresh revalidation、same-thread recursion、ReleaseMutex/CloseHandle primary+cleanup precedence、pre/post-mutation recovery_required和real dual/abandoned helper/finally handle controls全部冻结。Lock order统一`service RLock→controller mutex→store read/decision→Registry lock`，Registry lock内store callback立即拒绝。 |

该closure保持Task5→A→B1→B2→C/Task6→Task7 DAG及no actual/provider/holdout/action边界。完成静态document checks后仍必须等待新独立plan review PASS；本节或doc检查不得升级任何review/implementation checkbox。

## B1 round-2 closure review fix evidence

Consumed review: `.superpowers/sdd/2026-08-25-portfolio-hybrid-v1-1-implementation-plan/task-10b-slice-6-prerequisite-b1-plan-review-round-2.md`。本节仅记录planning修正；未修改source/tests，未运行pytest、process、UI、provider、actual、holdout或action，也未授权B1实施。

- Critical C1 literal mode：projection唯一sealed值改为production已支持的`provider_mode="local_understanding"`；它沿existing managed observe path取得并绑定B2 exact Qwen lease，不扩factory/allowlist。旧`"qwen"`及`local|local_grounding|api|null` substitutions全部FAIL；rules canonical SHA、source/payload SHA、RED与final selectors同步要求重算/拒绝旧SHA。
- Minor predecessor：`benchmark_v2_incumbent_handler_payload_source_v1.predecessor_content_sha256`唯一公式固定为同document的`provider_corpus_file_ref.content_sha256`；`file_sha256`、`source_parent_ref`、null和任意wrong SHA均拒绝。

完成静态checks后仍必须等待round-3独立plan review PASS；本节不升级任何review/implementation checkbox。
