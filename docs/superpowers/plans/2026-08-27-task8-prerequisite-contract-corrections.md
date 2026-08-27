# Task 8 前置 Contract 修正实施计划

> **状态：已冻结，可执行。** 本计划只修复会导致错误 benchmark 或 fake-only adapter 的两个阻塞点，然后立即返回 canonical Task 8。它不新增模型、provider、runner、supervisor、桌面后端、HTTP/action surface，也不扩大 B1/B2 threat model。

## 1. 主线裁决

最新主线保持不变：

```text
B1 FINAL PASS
→ B2 FINAL PASS
→ Task 6 PASS
→ Task 7 PASS
→ 本前置 T（opaque target identity）
→ 本前置 S（WorkflowService 高层 façade）
→ Task 8
→ Task 9–12 deterministic runway
→ Task 13 actual provider benchmark
→ Task 14–16 holdout
→ unknown native/web acceptance
→ freeze Hybrid v1.1
```

Ruling：canonical Task 8 当前两文件 allowlist 无法诚实完成 production adapter。原因是：

1. public prediction 要求 provider 无法知道的 private `target_id`；
2. 当前 Task 6 façade 不返回 authoritative post-start revision，也不返回已经验证的 adopted response body；
3. 若在 Task 8 内绕过，会被迫猜 revision、读取 store/Registry/result internals，或只做 fake service。

这两个问题都可能产生错误 benchmark，属于 stop-loss 规则中的 **必须修**，不是额外 hardening。

---

## 2. Amendment T：公开链路只使用 opaque `case_id`

### 2.1 冻结边界

- `case_id` 是唯一公开 target join identity；不新增 `target_key`，不公开、复制、hash alias 或猜测 private `target_id`。
- 自动 prediction 行键固定为：

```text
(case_id, arm_id, candidate_id, vista_request_ref)
```

- paired arms identity 固定为：

```text
(case_id, candidate_id, vista_request_ref)
```

- `sealed_target_binding_v3` 与 `sealed_vista_request_v3` 不含 `target_id`；legacy/extra `target_id` fail closed。
- provider child schema不变；Gold parent和24张截图 bytes不变。
- 当前 release ID 保留，因为已验证 production holdout file/registry claim roots 均不存在；若实施期间发现 durable authorization/claim，则 fail closed，不覆盖它。

### 2.2 私有正确性 metric

冻结 `private_unique_target_center_containment_v1`：

1. private scorer 按 opaque `case_id` join private case；
2. 在同一五 target `screen_group` 内，用 exact rational 计算每个 target 所有 acceptable region 的中心；
3. selected candidate bbox 以 half-open 规则包含某 target 至少一个 Gold region center，则视为匹配该 target；
4. 仅当恰好匹配一个 target，且该 target 的 `case_id` 等于当前 row `case_id` 时正确；
5. zero match、different target、multiple targets 都是 wrong；release gate 仍要求 `wrong_target_count == 0`。

该 metric 与 VISTA point gain 分离：semantic target correctness 看 candidate bbox 是否唯一包含正确 Gold target center；point baseline 仍看 candidate bbox center 是否命中 acceptable region。因而 bbox 可语义选对但中心偏移，VISTA 仍可产生真实 `+1`。

### 2.3 Exact allowed files

- Modify `configs/benchmarks/portfolio_hybrid_v1_1_estimand.v2.json`
- Modify `app/learn/hybrid/benchmark_v2_predictions.py`
- Modify `app/learn/hybrid/benchmark_scorer_v2.py`
- Modify `app/learn/hybrid/benchmark_v2_privileged_projector.py` only to centralize opaque case/screen-group identity helpers
- Modify `tests/test_portfolio_hybrid_v1_1_benchmark_v2_estimand.py`
- Modify `tests/test_portfolio_hybrid_v1_1_benchmark_v2_scoring.py`
- Modify `tests/test_portfolio_hybrid_v1_1_benchmark_v2_isolation.py`

不得读取或修改真实 Gold/corpus contents；不得修改 provider corpus schema、WorkflowService、Task 7、Task 8、runner、model/provider/action code。

### 2.4 TDD acceptance

- RED：estimand/Prediction schema中 `target_id` 消失；注入 legacy field拒绝。
- RED：正确 unique target、different target、multiple target、zero target 四类私有 geometry test。
- RED：metric separation 证明 candidate bbox 唯一包含正确 target center，但 bbox center miss；VISTA validated point hit 后 gain 为正。
- RED：cross-case/binding/request/candidate/bbox/pair lineage 继续 fail closed。
- RED：provider child、automatic artifacts、scorer public stdout/ref 不泄漏 `target_id` 或 private target label/id。
- GREEN：实现最小 closed-contract migration；不做 legacy migration。

Focused verification：

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_estimand.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_scoring.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_isolation.py
uv run python -m py_compile app/learn/hybrid/benchmark_v2_predictions.py app/learn/hybrid/benchmark_scorer_v2.py app/learn/hybrid/benchmark_v2_privileged_projector.py
git diff --check
```

单一原子 commit：

```text
fix(benchmark-v2): score opaque targets by private geometry
```

---

## 3. Amendment S：唯一 WorkflowService 高层 façade

### 3.1 Exact allowed files

- Modify `app/learn/workflow_service.py`
- Modify `app/learn/hybrid/benchmark_v2_incumbent_operation.py`
- Create `tests/test_portfolio_hybrid_v1_1_benchmark_v2_workflow_service_port.py`

Adjacent tests只运行、不修改：

- `tests/test_portfolio_hybrid_v1_1_benchmark_v2_incumbent.py`
- `tests/test_portfolio_hybrid_v1_1_benchmark_v2_worker_binding.py`
- `tests/test_learning_workflow_stage_execution.py`

若实现要求修改 Registry/store/Task 4/5/6 state machine/Task 7/Task 8/runner/panel/handler/provider/model，立即停止该方案；不允许把 orchestration 移出既有 WorkflowService owner。

### 3.2 Exact public surface

现有 `get_production_benchmark_v2_workflow_service()` singleton 返回对象补齐且仅补齐 canonical 六方法：

```python
start_hybrid_operation(*, screen_group, window_binding)
continue_hybrid_operation(*, operation_ref)
start_incumbent_observe(*, provider_case_ref, window_binding)
poll_incumbent_observe(*, operation_ref)
adopt_and_terminalize_incumbent(*, operation_ref, worker_ref)
cancel_operation(*, operation_ref)
```

保留旧 `start/resume/cancel` 只为 Task 6 compatibility；Task 8 AST 禁止调用它们或读取 `.composition`。

六方法不得接收 `store`、Registry、composition、`expected_revision`、`task_kind`、next payload、handler/model/provider/action参数。

### 3.3 Closed service refs

Service签发 `benchmark_v2_workflow_service_operation_ref_v1`，至少闭合：

```text
contract_version
mode = hybrid_v1_1 | incumbent_qwen_only
run_id
stage
operation_id
workflow_state_ref          # current authoritative revision + canonical state SHA
stage_execution_ref
request_ref
window_binding_ref
capture_ref
worker_ref
status
predecessor_content_sha256
artifact_is_authorization = false
execute_binding_enabled = false
content_sha256
```

Service step固定为 `benchmark_v2_workflow_service_step_v1`，返回当前 operation/worker refs、read-only `observed_task_kind`、本次至多一个 `adopted_result_projection`、terminal/cleanup refs和non-authorizing safety。

`benchmark_v2_adopted_result_projection_v1` 必须把 adopted response canonical bytes/SHA 与 exact run/stage/operation/worker/model-request/payload/result/adoption refs绑定。Incumbent terminal projection还绑定 terminal receipt、Task 5 window adoption和B1/B2 cleanup parents。Digest或worker success flag不能替代 response body。

### 3.4 S1：Contract/validators

RED：

- 六方法 exact signatures；production getter identity稳定；
- start/operation/step/adopted-projection extra/missing/resealed/stale字段拒绝；
- caller无法传 task kind/revision/store/Registry/composition；
- safety固定non-authorizing。

GREEN：加入 closed validators/composers和六方法 contract skeleton，不改变worker/provider行为。

Commit：

```text
feat(benchmark-v2): expose workflow service operation port
```

### 3.5 S2：Incumbent authoritative revision/result projection

RED：

- high-level start内部固定 single `vision_observe_screen`，caller不选 task；
- start后从 current durable store投影真实 revision/operation，不使用 `R+n`；
- poll running零mutation；
- terminalize/replay返回 byte-identical adopted response projection与Task 6 terminal/cleanup parents；
- wrong/stale/cross-case/window/capture/worker/result在副作用前拒绝；
- concurrent generic entry仍命中Task 6同锁guard，zero downstream worker/provider。

GREEN：只包装现有 Task 6 start/status/resume/cancel；service-owned projector只读并复验已经adopted exact response，不更改complete/cancel状态机。

Commit：

```text
feat(benchmark-v2): project incumbent service results
```

### 3.6 S3：Hybrid service-owned single-step continuation

RED：

- one screen group start恰好一次；initial builder而非benchmark选择首 task；
- continue只接 latest exact `operation_ref`，一次最多推进一个 producer；
- observed order exact Omni → Qwen → Fusion → Calibration → Review；
- duplicate start/continue byte-identical且zero second worker/provider；
- stale predecessor/revision/worker/window/capture fail closed；
- terminal replay不要求active adoption，不启动generic下一stage；
- cancel/reconcile清零fake resources；AST拒绝handler/provider/model/action imports/calls。

GREEN：只调用现有 stage start/status/adopt/continue/cancel链；不得复制 interpreter、next-worker builder或handler logic。

Commit：

```text
feat(benchmark-v2): expose managed hybrid service continuation
```

### 3.7 Focused verification

每个slice：

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_workflow_service_port.py
```

S2 gate：

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_workflow_service_port.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_incumbent.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_worker_binding.py
```

S3 integration gate：

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark_v2_workflow_service_port.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_incumbent.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_worker_binding.py tests/test_learning_workflow_stage_execution.py -k "benchmark_v2 or hybrid_managed_worker_order or hybrid_calibration_continues_only or duplicate_hybrid_continue or public_hybrid_review_continuation"
uv run python -m py_compile app/learn/workflow_service.py app/learn/hybrid/benchmark_v2_incumbent_operation.py tests/test_portfolio_hybrid_v1_1_benchmark_v2_workflow_service_port.py
git diff --check
```

---

## 4. 独立 review gate

Amendment T 后一个 independent review，检查：

- no Gold/private target leak；
- unique containment metric不与point gain合并；
- wrong_target=0仍是hard gate；
- existing pair/no-cherry-pick/isolation不变量保持。

Amendment S 后一个 independent review，trace：

- one production getter → one composition；
- Hybrid start/每次single-step continue/terminal replay；
- incumbent start→poll→atomic terminalize→response projection→replay；
- stale/cancel/terminal race和zero downstream incumbent worker；
- no action/API/model/provider expansion。

只有 Critical/Important 的错误 benchmark、cross-run/cross-worker pairing、duplicate provider、false success或residue问题继续修；命名、通用化、额外tamper/OS hardening记录延期。

---

## 5. 三小时止损

如果 Amendment T + S 在约三小时仍未闭环：

- 会导致 wrong benchmark、cross-run/result、duplicate provider、false lifecycle或residue：继续最小修复；
- heartbeat generalization、whole-process通用reattach、local-admin抗篡改、通用supervisor/router/backend：记录 limitation，延期；
- 不提交 fake-only Task 8，不猜revision，不读取Registry/store/private result；
- 保留精确失败test并停在最小未解决的service-owned projection。

---

## 6. Task 8 恢复条件

必须同时满足：

1. Amendment T focused tests + independent review PASS；
2. Amendment S focused/adjacent tests + independent review PASS；
3. canonical Task 8 仍只修改：
   - `app/learn/hybrid/benchmark_v2_actual.py`
   - `tests/test_portfolio_hybrid_v1_1_benchmark_v2_actual.py`
4. 无actual model/provider/GPU/holdout/UI/action在deterministic runway中启动。

满足后立即执行 Task 8，不再新增第五、第六种可替换层或继续建设 Benchmark infrastructure。
