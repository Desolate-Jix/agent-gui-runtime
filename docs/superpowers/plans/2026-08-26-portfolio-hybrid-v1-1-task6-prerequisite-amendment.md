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

def get_production_benchmark_worker_supervision_root(
) -> BenchmarkWorkerSupervisionRoot: ...

def compose_test_benchmark_worker_supervision_root(
    *, journal_root: Path, test_capability: object
) -> BenchmarkWorkerSupervisionRoot: ...

def benchmark_worker_scope_name_v1(
    *, authority_kind: Literal["production_workflow_service", "test_only"],
    run_id: str, stage: str, operation_id: str, worker_id: str,
    payload_sha256: str, execution_nonce: str,
) -> str: ...

def compose_benchmark_worker_operation_anchor_v1(
    *, supervision_root: BenchmarkWorkerSupervisionRoot,
    reservation: Mapping[str, object],
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
        payload: Mapping[str, object],
        supervision_root: BenchmarkWorkerSupervisionRoot,
    ) -> dict[str, Any]: ...

    def launch_prepared_benchmark_worker(
        self,
        *, reservation_ref: Mapping[str, object],
        expected_operation_anchor: Mapping[str, object],
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

Store锚定的是不含launch-time parent incarnation的`benchmark_worker_expected_supervision_v1`，其exact fields固定为 `contract_version,authority_kind,operation_anchor_ref,reservation_ref,supervision_inputs_ref,run_id,stage,operation_id,workflow_revision,worker_id,task_kind,payload_sha256,execution_nonce,scope_name,startup_gate_timeout_ms,artifact_is_authorization,execute_binding_enabled,content_sha256`。实际launch后写`benchmark_worker_supervision_v1`，exact fields固定为 `contract_version,authority_kind,expected_supervision_ref,operation_anchor_ref,reservation_ref,supervision_inputs_ref,run_id,stage,operation_id,workflow_revision,worker_id,task_kind,payload_sha256,execution_nonce,scope_name,supervisor_process_identity,startup_gate_timeout_ms,artifact_is_authorization,execute_binding_enabled,content_sha256`。`expected_supervision_ref`必须等于store anchor；`supervisor_process_identity`是实际持有creator Job/Event/process handles的launching Registry parent exact PID/create-time。expected contract故意不含该launch-time identity，使store-anchor后、launch调用前的server restart可由fresh exact parent使用同一reservation；实际supervision及owner chain再绑定新parent，不能remint expected inputs。`task_kind`必须是`vision_observe_screen`；nonce必须是Registry在任何spawn前reservation阶段生成并首次持久化的32位lowercase hex；两个authorization boolean必须为false。任何extra/missing field拒绝。

Scope-name input是canonical JSON `{"contract_version":"benchmark_worker_scope_name_v1","authority_kind","run_id","stage","operation_id","worker_id","payload_sha256","execution_nonce"}`，name为production `Local\\AgentGuiBenchmarkWorker-<sha256>` 或 test `Local\\AgentGuiBenchmarkWorkerTest-<sha256>`。Fresh Registry必须从sealed inputs重算，不能相信journal内name。该grammar独立于且不得放宽现有 `Local\\AgentGuiHybrid-(omni|qwen|vista)-<sha>` provider namespace。existing same-name Job一律collision FAIL，绝不attach或生成新nonce重试。

Composition只持有长期的production root/factory capability，不持有per-operation authority。`get_production_benchmark_worker_supervision_root()`在B1内即可用且只返回production Registry的稳定journal root与不可序列化opaque root capability；panel/client mapping不能构造或替换它。Test root要求per-test opaque capability、`authority_kind=test_only`和tmp journal root；production Registry validator硬拒绝test root，test Registry也硬拒绝production root。Cross-kind contract、root/path替换、mapping remint或capability substitution不能启用另一分支。

`benchmark_worker_operation_anchor_v1` 是store持有的closed server-read document，exact fields为 `contract_version,run_id,stage,operation_id,workflow_revision,task_kind,payload_sha256,worker_id,execution_nonce,reservation_ref,supervision_inputs_ref,expected_supervision_ref,window_binding_ref,capture_ref,anchor_identity_sha256,predecessor_content_sha256,content_sha256`。`anchor_identity_sha256`只对exact immutable subset `contract_version,run_id,stage,operation_id,workflow_revision,task_kind,payload_sha256,worker_id,execution_nonce,reservation_ref,supervision_inputs_ref,window_binding_ref,capture_ref`取canonical SHA；expected supervision的`operation_anchor_ref`固定引用该non-circular identity SHA，store再持久化由该identity与reservation inputs生成且不含launching parent identity的`expected_supervision_ref`，因此worker ID/nonce/parent restart/supervision均不存在hash cycle。任何extra/missing/null-required field、current store operation/revision/ref不一致均拒绝。B2 acquisition owner refs不进入B1 anchor，C operation document将其作为与B1 anchor并列的closed parents封存，因此严格DAG仍为B1先独立GREEN/review，再B2，再C。

Registry在自身lock内执行严格两步协议。`prepare_benchmark_worker_identity()`只为exact `(run,stage,operation,workflow_revision,task_kind,payload_sha256,root-kind)`生成并durable reservation一个worker ID和32-hex execution nonce。`benchmark_worker_identity_reservation_v1` exact fields为 `contract_version,authority_kind,run_id,stage,operation_id,workflow_revision,task_kind,payload_sha256,worker_id,model_request_id,execution_nonce,supervision_inputs_ref,reservation_state,abort_observation_ref,predecessor_content_sha256,content_sha256`；state只能`reserved|anchored|launching|launched|cancelled_before_launch|aborted_before_anchor`，不适用abort ref显式null。Prepare返回`reserved` closed mapping；它不得创建process/Event/Job/beacon、设置provider环境、安装handler或取得Qwen lease。同一inputs replay返回byte-identical reservation；同operation冲突inputs拒绝且不得第二reservation。B1 production composer/validator只用root capability、reservation与Task5 refs构造closed operation anchor及parent-independent expected supervision，所以B1可在B2/C前独立GREEN/review；C稍后把B1 anchor与B2 closed acquisition parents一起做expected-revision CAS。Store anchor成功后才可调用`launch_prepared_benchmark_worker()`；launch在Registry lock内fresh读取reservation，closed-validate由store传入的current anchor、重算anchor identity/scope/expected supervision并要求其SHA等于store `expected_supervision_ref`，再以**当前**Registry parent identity构造实际 supervision，随后原子标记`launching`并至多启动一次worker。Fresh observer也必须由C重新读取store current anchor并传入，B1重算parent-independent expected supervision ref，再验证actual supervision/owner的exact supervisor identity；只信journal、只信anchor SHA或由journal自重算均只能pending。

Crash/replay/cancel固定如下：prepare前crash无side effect；reservation durable但store CAS前crash时，恢复只能在active operation/revision/inputs仍exact时用同一reservation完成CAS，否则把reservation标记`aborted_before_anchor`且证明无spawn/provider；store anchor后、launch前crash必须以同一reservation launch或由cancel原子标记`cancelled_before_launch`，不得新worker ID/nonce；launch标记后crash由B1 owner journal/Job tri-state恢复，绝不第二spawn。prepare、store CAS、launch和cancel并发时，每个operation最多一条reservation chain和一个worker incarnation；cancel先赢时launch返回既有cancel state且spawn/provider call count为零。

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
- [ ] **RED 4 — identity/Job/reservation:** wrong create-time、PID reuse、foreign Job member、pre-assignment Job absent、duplicated beacon、gate timeout、handle close failure、stable-zero不足全部FAIL；prepare→store-anchor→launch每个crash/replay/cancel cut、duplicate reservation、worker/nonce/expected-supervision substitution、fresh observer只信journal全部FAIL或pending，且spawn/provider count为expected 0或1。
- [ ] **RED 5 — generic compatibility:** 没有server-owned benchmark ref的所有现有 worker start/status/cancel bytes与执行顺序不变；caller payload中同名reserved key必须拒绝而不能启用supervision。
- [ ] **RED 6 — namespace/root authority:** cross-run/cross-stage/cross-operation/worker/payload/nonce/reservation/anchor/expected-supervision substitution、production/test namespace互换、pre-existing Job collision、journal内scope-name替换、full supervision/anchor/owner-journal remint、wrong root capability全部FAIL；existing Omni/Qwen/VISTA name grammar与tests byte/semantic不变。
- [ ] **Run RED:** `uv run pytest -q tests/test_learn_hybrid_windows_process_scope.py tests/test_learning_workflow_stage_worker.py -k "benchmark_worker or exact_process_identity_to_scope"`。
- [ ] **GREEN 1:** 先实现 exact identity→Job assignment primitive及窄测试。
- [ ] **Run GREEN 1:** `uv run pytest -q tests/test_learn_hybrid_windows_process_scope.py -k "exact_process_identity_to_scope"`。
- [ ] **GREEN 2:** 再实现 Registry owner journal、bootstrap gate、normal/abnormal reconciliation与public cleanup observer。
- [ ] **Run GREEN 2:** `uv run pytest -q tests/test_learning_workflow_stage_worker.py -k "benchmark_worker" && uv run pytest -q tests/test_learn_hybrid_windows_process_scope.py && uv run python -m py_compile app/learn/hybrid/windows_process_scope.py app/learn/workflow_worker.py && git diff --check`。

**Cleanup:** 每个real-spawn test的outer `finally`都从store fresh读取exact operation anchor，再调用production `observe_benchmark_worker_cleanup(worker/run/stage/operation, terminate=True, expected_operation_anchor=anchor, supervision_root=production_root)`；primary assertions逐个引用Registry-owned real handle的raw close-success observation或fresh exact supervisor-absence proof，证明worker process、startup Event、beacon/file、creator/reopened Job handles均closed，并证明expected PID-create-time absent且recomputed named Job absent。Process-wide handle count只记录为diagnostic，不作为PASS/FAIL authority。禁止宽泛按进程名kill。

**Independent review gate:** reviewer手工追一条 parent crash-before-gate 与一条 result-after-gate路径，确认 handler/provider fence、exact Job membership、restart无新worker、process/Job handles关闭；输出 `task-10b-slice-6-prerequisite-b1-review.md`。

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

`benchmark_provider_runtime_owner_v1`由Registry从B1 reservation生成，exact fields为 `contract_version,authority_kind,run_id,stage,operation_id,worker_id,model_request_id,reservation_ref,payload_sha256,content_sha256`；B2 production prepare返回closed `benchmark_provider_acquisition_owner_v1`，exact fields为 `contract_version,model_request_id,runtime_owner_ref,acquisition_intent_ref,owner_state,content_sha256`，`owner_state=acquisition_prepared`。两者都不含lease/process/listener/Job或provider profile。C operation document将这套refs与B1 operation anchor并列封存；跨worker/request/reservation substitution拒绝。

`verified_not_acquired`只能由production既有aborted-acquisition owner/tombstone primitive生成：必须绑定exact `model_request_id`、durable acquisition-intent ref、runtime-owner ref、sealed aborted-owner tombstone ref，并fresh证明该request无active lease且该runtime owner从未拥有process identity、socket listener或Job member；其`lease_ref,profile_ref,server_process_identity,socket_ref,job_scope_ref,termination_observation_ref,scope_stable_zero_ref,listener_stable_zero_ref`均为null，`no_active_lease_observation_ref`和绑定“无owned process/listener/Job”的`no_owned_runtime_observation_ref`均non-null。若缺acquisition intent/runtime owner/tombstone、owner曾取得lease、或任何owned process/listener/Job不可观察，则保持pending；不得由`request_not_active`、无文件或test mapping补造。两个outcome的validator互相拒绝字段形状，不能把not-acquired升级为process-exited。既有 tombstone bytes与 `cancel_model_request()` response必须不变；legacy tombstone无sidecar时对benchmark只返回 `cleanup_pending/indeterminate`。

`observe_qwen_model_request_cleanup()` 在 production Qwen file lock下读取并closed-validate sidecar、owner tombstone和现存lease state：exact lease必须不再active；acquired owner的sole server必须有same-incarnation termination、socket listener zero、Job stable-zero；aborted-before-lease owner必须满足上述`verified_not_acquired`全套negative ownership observations。`shared_server_retained`可作为通用observer状态，但 C 的benchmark terminal gate只接受 `verified_exact_process_exited`或`verified_not_acquired`；因此acquired benchmark tests和未来actual run必须使用isolated owner，不把ambient/shared server冒充zero residue。

在B1 reservation之后、C store CAS之前，C经同一Registry调用`prepare_benchmark_provider_acquisition()`；它用reservation内durable `model_request_id`调用production“prepare acquisition owner”窄primitive，只写acquisition intent/runtime owner，不创建lease/process/listener/Job、不加载profile/provider。C operation document必须把这两个refs与B1 anchor同时封存；因此任何store-anchored `prepared`状态都已有可abort owner，合法prelaunch/pre-gate cancel不会落入missing-intent hole。若crash或CAS失败发生在owner prepared后但store document CAS前，fresh Registry只按同一reservation/owner执行production abort并把reservation标记`aborted_before_anchor`；不得spawn/provider。若store中refs missing/漂移则视为损坏并保持pending，不能事后补造。normal path：benchmark worker handler完成且existing lease release结束后，worker entry调用 production observer，把完整receipt写入 result reserved evidence；Registry A primitive只投影其 SHA ref。abnormal path：B1 supervisor先固定 outer-worker cancel intent，再用 durable `model_request_id` 调现有 exact cancel/release；acquisition intent已存在但lease未取得时走production aborted-acquisition owner/tombstone并观察`verified_not_acquired`，lease已取得时观察`verified_exact_process_exited`，重复调用只返回同一receipt。Registry journal只保存receipt/ref，不复制或改写 truth。Fresh Registry从worker owner journal + Qwen sidecar恢复，无需raw payload或live process handle。

- [ ] **RED 1 — production sidecar:** real harmless test-owned Qwen-compatible process、真实 lease state/socket/Job 走 existing acquire/release；要求 sidecar由production writer生成，observer返回 exact process exit且三次stable-zero。测试不可patch observer或直接写receipt。
- [ ] **RED 2 — compatibility:** release前后existing owner tombstone bytes/schema、`cancel_model_request()` public response和nonbenchmark model lifecycle assertions保持不变；新增sidecar不进入API response。
- [ ] **RED 3 — cancel/acquisition crash matrix:** 用fresh Registry分别覆盖pre-gate（已有parent-prepared acquisition intent/runtime owner但无lease）、post-gate/pre-acquire、acquire-intent durable、lease-acquired、request in flight、body complete、release started、tombstone written、sidecar written；未lease的可达cuts最终byte-identical `verified_not_acquired`，acquired cuts最终`verified_exact_process_exited`。另以删除/漂移intent的负控证明missing intent始终pending；全矩阵不启动replacement provider/worker。
- [ ] **RED 4 — no fake proof:** PID alone、`request_not_active`、missing/edited sidecar、wrong request/acquisition-intent/runtime-owner/tombstone/lease/incarnation/socket/Job、PID reuse、listener残留、lease仍active、曾owned process却声称not-acquired、shared server、test-authored mapping全部不能使benchmark cleanup verified；两个outcome字段互换也FAIL。
- [ ] **Run RED:** `uv run pytest -q tests/test_model_request_cancellation.py tests/test_learning_workflow_stage_worker.py -k "qwen_cleanup_sidecar or benchmark_provider_cleanup"`。
- [ ] **GREEN 1:** 实现sidecar write/read/closed verifier并保持existing tombstone/response不变。
- [ ] **Run GREEN 1:** `uv run pytest -q tests/test_model_request_cancellation.py -k "qwen_cleanup_sidecar or owner_tombstone or request_cancellation"`。
- [ ] **GREEN 2:** 将benchmark-only normal result evidence与abnormal Registry reconciliation接到同一production observer；A 的 provider ref变为non-null且与sidecar SHA exact相等。
- [ ] **Run GREEN 2:** `uv run pytest -q tests/test_learning_workflow_stage_worker.py -k "completed_result_identity or benchmark_provider_cleanup or qwen" && uv run pytest -q tests/test_model_request_cancellation.py -k "qwen" && uv run python -m py_compile app/core/model_server.py app/learn/workflow_worker.py && git diff --check`。

**Cleanup:** 测试 finally通过exact lease/request/Job owner执行production release/reconcile；随后断言worker PID、Qwen PID-create-time、socket listener、Job member、lease state、临时handle为零。Sidecar保留在tmp lease root供restart验证，测试结束才删除tmp root。

**Independent review gate:** reviewer不得接受 fake/test-only helper output；必须从production lease state、owner tombstone、sidecar、OS PID/socket/Job observation手工重建normal和abnormal各一条；输出 `task-10b-slice-6-prerequisite-b2-review.md`。

**Commit:** `feat(model-server): retain exact qwen cleanup receipt`

---

### Task 6 Amendment C: Durable incumbent cut-point and complete panel compatibility surface

**Depends on:** A、B1、B2及三份独立review全部 PASS。此 task 替代原 Task 6 brief 中“五入口”和缺失pre-adopt/cleanup primitive的假设；其余 Task 6 success criteria继续有效。

**Allowed files:**
- Create `app/learn/hybrid/benchmark_v2_incumbent_operation.py`
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

def get_production_learning_workflow_service_composition(
) -> LearningWorkflowServiceComposition:
    pass

def compose_test_learning_workflow_service(
    *, store: LearningWorkflowRunStore,
    worker_registry: LearningStageWorkerRegistry,
    project_root: str | Path,
    benchmark_supervision_root: BenchmarkWorkerSupervisionRoot | None = None,
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

Production composition getter lazy-bind且稳定返回exact module singleton pair和B1 production supervision root/factory capability；它不是per-operation authority，不接受caller dependency/path override。每次operation的anchor都只能来自该composition的store current document。Test constructor只接受显式tmp pair；默认`benchmark_supervision_root=None`，因此只能测nonbenchmark compatibility。需要测benchmark时必须传B1 `test_only` root，所得contract/name/journal root与production disjoint，且任何panel production branch拒绝test composition。Panel可保留store/Registry monkeypatch aliases，但先一次性组装pair再传wrapper；callee/helper与endpoint都不得直接调用Registry method。

**Return and exception contracts:** nonbenchmark return必须是现有callee返回dict的deep-equal value，不增加wrapper字段：start/status是Registry public record；adopt是generic adoption；continue/heartbeat/finish/recover/runtime attachment是现有service dict；cancel是现有cancel dict并保留`worker_termination`。Exception集合和precedence固定为：start=`LearningStageWorkerError | LearningWorkflowStageOperationError | LearningWorkflowTransitionError`；status=`LearningStageWorkerError`；adopt同start；continue=`LearningStageWorkerContinuationError | LearningStageWorkerError | LearningWorkflowEvidenceError | LearningWorkflowStageOperationError | LearningWorkflowTransitionError`；cancel同start；heartbeat/recover=`LearningWorkflowStageOperationError | LearningWorkflowTransitionError`；finish先`LearningWorkflowEvidenceError`，再stage/transition；runtime attachment保持现有projection的exception/return语义。Benchmark internal pending/SAFE_STOP使用`LearningWorkflowStageOperationError`，不得引入新panel exception class。所有九个wrapper只能从同一个`LearningWorkflowServiceComposition`取store/Registry/root；production无dependency参数，test只能通过上述pair constructor注入，不能单独替换某一callee。

**Closed durable schemas:** `stage_execution["benchmark_v2_incumbent"]`只接受 `benchmark_v2_incumbent_operation_v1`。Exact fields固定为：

| Field | Closed value |
|---|---|
| `contract_version` | literal `benchmark_v2_incumbent_operation_v1` |
| `mode` | literal `benchmark_v2_incumbent_single_observe` |
| `run_id,stage,operation_id` | 与active store operation exact相等的nonempty strings |
| `operation_anchor_ref` | exact `{"content_sha256": lower_sha256}` |
| `reservation_ref,supervision_inputs_ref,expected_supervision_ref` | B1 closed one-key refs；prepared起均non-null且与store operation anchor exact相等 |
| `acquisition_intent_ref,runtime_owner_ref` | B2 production prepared-owner closed refs；store anchor CAS前生成，prepared起non-null |
| `prepared_revision,current_document_revision` | nonnegative int；每次CAS exact predecessor+1 |
| `task_kind` | literal `vision_observe_screen` |
| `handler_payload_sha256` | lower SHA-256；payload不持久化进该document |
| `window_binding_ref,capture_ref` | Task5 closed refs |
| `execution_nonce` | B1 32-char lowercase hex |
| `phase` | `prepared|worker_starting|worker_bound|result_ready|terminal_intent|adopted|cancel_intent|cleanup_pending|complete|cancelled|safe_stopped` |
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

`benchmark_v2_incumbent_terminal_receipt_v1` exact fields为 `contract_version,outcome,run_id,stage,operation_id,worker_id,model_request_id,payload_sha256,result_sha256,terminal_intent_ref,cancel_intent_ref,generic_adoption_ref,window_adoption_ref,worker_cleanup_ref,provider_cleanup_ref,provider_cleanup_outcome,terminal_at,artifact_is_authorization,execute_binding_enabled,predecessor_content_sha256,content_sha256`。`outcome`只能`benchmark_v2_incumbent_observe_complete|benchmark_v2_incumbent_cancelled`；complete要求terminal/result/adoption四ref非null、provider outcome=`verified_exact_process_exited`且cancel ref null；cancelled要求cancel/B1/B2三ref非null、terminal/result/adoption ref null，B2 closed receipt outcome只能`verified_not_acquired|verified_exact_process_exited`。两个provider outcomes互斥且不得由C转换。两个authorization booleans固定false。Terminal replay直接deepcopy persisted mapping，不重打timestamp或重算不同revision bytes。

**Closed transition table:**

| From | Event/required parents | To | Forbidden |
|---|---|---|---|
| absent | B1 identity reservation一次 → B2 acquisition owner一次（zero provider）→ server CAS anchor/reservation/expected supervision/Task5 refs | `prepared` | caller mode/key启用、spawn/lease/provider、second reservation/owner |
| `prepared` | B1 `launch_prepared_benchmark_worker`以store expected supervision ref启动exact once | `worker_starting` | direct generic start、different worker/nonce |
| `worker_starting` | exact one Registry worker + assignment_proven | `worker_bound` | second/different worker |
| `worker_bound` | A snapshot + B1/B2 refs available | `result_ready` | interpreter/next worker |
| `result_ready` | winning complete CAS | `terminal_intent` | simultaneous cancel intent |
| `terminal_intent` | Registry adopt SHA=A | `adopted` | adopt different result |
| `adopted` | Task5 rebuild + B1/B2 verified | `complete` | caller evidence替换 |
| `prepared|worker_starting|worker_bound|result_ready` | winning cancel CAS | `cancel_intent` | simultaneous terminal intent |
| `cancel_intent` | one or both cleanup receipts pending | `cleanup_pending` | cancelled terminal |
| `cancel_intent|cleanup_pending` | B1 verified + B2 `verified_not_acquired`或`verified_exact_process_exited` | `cancelled` | missing acquisition intent、result adopt/continuation |
| any nonterminal | ref drift/ambiguity/unobservable ownership | `safe_stopped` | replacement worker或自动恢复到running |
| `complete|cancelled|safe_stopped` | any wrapper/restart/recover | same byte-identical state | revision increment/side effect |

每次running→running CAS必须复制所有已有refs和predecessor；不在表内的edge拒绝且revision不变。`terminal_intent xor cancel_intent` invariant在每次load和write前重验。

**Guarded wrapper exact call order/call-count contract:**

| Wrapper | Exact successful order | Failure call count and side effect |
|---|---|---|
| start | stage active-operation/revision precheck once → nonbenchmark `Registry.start` once；benchmark则B1 identity prepare once → B2 acquisition-owner prepare once → store anchor CAS once → B1 launch once → stage current-operation postcheck once | precheck fail：Registry prepares/launch=0；identity prepare fail：owner/store/launch=0；owner prepare fail：store/launch=0且reservation exact abort；anchor CAS fail：launch=0且same reservation/owner走production abort；launch fail：不得second launch；postcheck fail：已启动generic worker时exact compensating `Registry.cancel` once，benchmark按anchored cancel状态机清理，随后抛原stage/transition error |
| status | `Registry.status` once | worker error后store/stage=0；valid Registry status不得被store missing抢先覆盖 |
| adopt | stage active-operation/revision precheck once → `Registry.adopt_result` once | precheck fail：adopt=0；adopt fail：stage mutation/continuation=0；无postcheck/compensating adoption |
| continue | continuation precheck/loader once → Registry inspection/adoption primitives按既有callee exact once → evidence validation once → stage transition once | 任一步失败时后续call=0；已存在generic adoption按既有idempotency replay，不新增compensation或next worker |
| cancel | active-operation/revision precheck once → Registry cancel once → stage cancel transition once | precheck fail：Registry=0；Registry fail：stage cancel=0；stage fail保留既有worker termination result且不重发第二cancel；benchmark intent cleanup按durable replay |
| heartbeat | stage heartbeat once | failure无Registry/store外额外mutation；intent/terminal precheck拒绝时heartbeat call=0 |
| finish | evidence validation once → stage finish once | evidence fail：stage=0；stage/transition fail不重跑evidence writer或Registry |
| recover | stage recovery once | failure无Registry call、worker spawn/cancel或额外CAS |
| runtime attachment | existing pure projection once | composition mismatch在projection前fail；Registry/store mutation=0 |

start的benchmark two-step是现有start语义内的受控替代；B2 acquisition-owner prepare也是同一Registry-owned path且zero provider，外层顺序仍严格为`stage precheck → Registry-owned identity/owner prepare + launch path → stage postcheck/compensation`；adopt严格为`stage precheck → Registry`。任何实现或测试不得采用worker→stage顺序。

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

**Fixed lock/order:** 所有路径先取`(id(store),run_id,operation_id)` RLock；普通mutation遵循store precheck/get/CAS→Registry public primitive且不得在Registry internal lock回调store。start是经审查的唯一交错：store precheck→Registry identity reservation→Registry/B2 acquisition-owner prepare→store anchor CAS→Registry launch→store postcheck/compensation，所有步骤仍在同一operation lock内且每次Registry call结束释放其internal lock后才访问store。adopt为store precheck→Registry adopt，无postcheck。restart/recover若先缺operation ID，只能在lock-map guard下读取active operation，取得exact operation lock后重新读取并CAS。

**Complete:** A inspection → 将A current SHA与store-anchored reservation/expected supervision、Task5 server binding/adoption parent、B1 assignment/cleanup和B2 production sidecar parent联合验证 → CAS terminal intent → exact `adopt_result()`并要求SHA一致 → Task5 server adoption rebuild → CAS terminal receipt。**Cancel:** CAS cancel intent（包含reservation/anchor、可空B1 process identity与B2 request/acquisition owner refs）→ B1 `verified_not_launched|verified_exact_worker_exited` + B2 `verified_not_acquired|verified_exact_process_exited`的合法组合 → CAS cancelled receipt。已launch时B1必须exact-worker-exited；已lease时B2必须exact-process-exited；状态与outcome不匹配FAIL。任一cleanup/missing intent pending保持intent pending。Terminal replay只读persisted canonical receipt。

- [ ] **RED 1 — eight-entry race:** start/status/adopt/continue/cancel/heartbeat/finish/recover与specialized terminalizer并发竞争；complete/cancel intent恰一winner，finish/recover不得覆盖，status不得旁路composition，heartbeat在intent后revision不变。
- [ ] **RED 2 — crash cuts:** complete 的 inspection/intent/adopt/Task5 rebuild/terminal及cancel的intent/outer cleanup/provider cleanup/terminal每个cut crash+fresh composition；只resume同一worker/result/receipt，byte-identical replay，zero new worker/provider。
- [ ] **RED 3 — provenance/remint:** 手工result path read、self-minted SHA、PID/is_alive、request_not_active、fake cleanup mapping、wrong Task5 binding/Qwen/Job/operation-anchor/expected-supervision ref全部FAIL；same-identity合法self-hash remint使A报告changed current SHA，但C把它与store-anchored Task5/B1/B2 parent chain联合时必须FAIL。此fixture只在A/B1/B2已GREEN后存在，不回灌A slice。
- [ ] **RED 4 — no cascade/no action:** generic interpreter、`_ensure_next_managed_stage_operation`、`_start_next_managed_stage_worker`、next-worker和specialized continuation mutation count都为零；无 action/Runtime/click/publish import或artifact authority。
- [ ] **RED 5 — compatibility:** 按上表逐入口覆盖success、stale revision、not-found/invalid operation、每个backend/callee error和明确precedence；start exact验证precheck→Registry prepare/launch→postcheck/compensation，adopt exact验证precheck→Registry。Tracked incumbent/Hybrid完整`APIResponse.model_dump()` bytes、callee order/count、side effects与continuation graph等于pre-amendment fixture。Static AST/callgraph scan同时覆盖panel endpoint、panel helper与workflow-service wrapper/callee，确认除single composition owner外无direct Registry method call。
- [ ] **RED 6 — cancel before lease:** fresh composition在pre-gate、post-gate/pre-acquire、acquisition-intent、lease-acquired cuts分别恢复；前三区合法owner最终消费B2 `verified_not_acquired`，lease-acquired消费`verified_exact_process_exited`，B1按launch state消费对应receipt；missing intent保持pending，zero replacement worker/provider，terminal replay byte-identical。
- [ ] **Run RED:** `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_incumbent.py tests/test_learning_workflow_stage_execution.py -k "benchmark_v2 or guarded or incumbent or hybrid"`。
- [ ] **GREEN 1:** 实现closed durable document、single getter、shared lock和pure-fake CAS/race state machine。
- [ ] **Run GREEN 1:** `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_incumbent.py -k "document or lock or intent or replay"`。
- [ ] **GREEN 2:** 接八个guarded wrappers、panel wiring与compatibility seam；先通过nonbenchmark equivalence再启用benchmark branch。
- [ ] **Run GREEN 2:** `uv run pytest -q tests/test_learning_workflow_stage_execution.py -k "incumbent or hybrid or guarded"`。
- [ ] **GREEN 3:** 接A inspection、B1/B2 cleanup与Task5 adoption，完成real Registry/spawn + harmless recorded Qwen response E2E；不运行真实model inference。
- [ ] **Run GREEN 3:** `uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_incumbent.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_worker_binding.py tests/test_learning_workflow_stage_worker.py tests/test_model_request_cancellation.py tests/test_learning_workflow_stage_execution.py -k "benchmark_v2 or incumbent or hybrid or qwen" && uv run python -m py_compile app/learn/hybrid/benchmark_v2_incumbent_operation.py app/learn/workflow_service.py app/api/panel.py && git diff --check`。

**Cleanup:** E2E outer finally依次resume pending intent、exact provider cleanup、exact worker cleanup、Task4 window cleanup、store close；最终独立扫描 PID-create-time/Job/socket/listener/lease/HWND/handle 全部为零。若cleanup indeterminate，test必须FAIL并保留journals，不能删除证据后报PASS。

**Independent review gate:** reviewer trace生产 singleton composition、八入口同锁、A→intent→adopt、cancel→B1/B2、每个crash cut、Task5 provenance、no-cascade与compatibility；输出原约定 `task-10b-slice-6-review.md`。Critical/Important为零后才允许 Task 7。

**Commit:** `feat(benchmark-v2): terminalize incumbent after qwen observe`

---

## Task 7 alignment: consume journals, do not duplicate lifecycle

Task 7 的 `verify_lifecycle_from_raw()` 输入必须将下列production journals当作唯一 owner/cleanup parents：

- B1 reservation/operation-anchor/expected-supervision chain、scope assignment observation、raw handle-close observations与normal/abnormal/not-launched worker cleanup receipt；
- B2 Qwen acquisition-intent/runtime-owner/lease state ref、aborted或released owner tombstone、`verified_not_acquired|verified_exact_process_exited` sidecar与适用的scope/listener stable-zero receipt；
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
- [ ] B1 identity reservation→B2 zero-provider acquisition owner→store operation anchor/parent-independent expected supervision→launch协议无worker/nonce/parent-restart cycle、最多一次spawn，fresh observer以store expected supervision ref再验证actual parent owner。
- [ ] B1 `assignment_proven`和`cleanup_finalization_intent`顺序、Job可重开/same-live retry/dead-supervisor inference/pre-assignment recovery branches、raw real handle observations与real outer-parent termination/receipt-stage crash matrix通过。
- [ ] B1 production/test root capability、scope namespace/name formula和closed operation anchor全部closed且disjoint，composition不持有per-operation authority。
- [ ] B2 cancel-before-lease以production aborted-acquisition owner/tombstone签`verified_not_acquired`，acquired path签`verified_exact_process_exited`，missing intent保持pending。
- [ ] C九wrapper signatures、factory/root test-pair injection、operation/intents/receipt schemas、transition table与API error precedence/call-count/side-effect matrix逐项通过；start为precheck→Registry→postcheck/compensation，adopt为precheck→Registry。
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
| B1 root/anchor/nonce cycle | Composition只持有production root/factory capability；冻结closed operation anchor、reservation、parent-independent expected supervision与launch-time actual supervision schemas；采用Registry identity reservation→B2 zero-provider owner→store anchor/expected supervision→launch，store后/launch前fresh parent无需remint，且定义每个crash/replay/cancel cut与fresh store-anchor observer。 |
| C compatibility order | Composition/test seam改用root capability；九wrapper冻结exact call order/count/side effects。Start严格stage precheck→Registry prepare/launch→postcheck/compensation，adopt严格precheck→Registry，APIResponse/error mappings保持既有值。 |
| B2 cancel before lease | Production acquisition owner在gate前只封存intent、zero provider；aborted tombstone签disjoint `verified_not_acquired`并绑定request/intent/runtime owner/no active lease/no owned process/listener/Job；C cancelled接受与lease state匹配的两种B2 outcome，missing intent pending。 |
| exact owned handle truth | Registry是真实handle owner；`closed_explicitly`只源自production close call raw observation，`closed_by_verified_supervisor_exit`只源自fresh exact PID/create-time absence，journal字段与global count不构成proof。 |

Round 2 planning-only verification实际结果：strict UTF-8 decode PASS；LF/no BOM/replacement character PASS；placeholder/conflict marker/trailing whitespace PASS；referenced existing paths与heading order PASS；上述六项required-closure assertions PASS；tracked `git diff --check` PASS；untracked amendment `git diff --no-index --check` PASS。只有下一轮独立plan review关闭Critical/Important后，才可授权Prerequisite A；B1/B2/C仍按各自DAG review gate逐slice授权。
