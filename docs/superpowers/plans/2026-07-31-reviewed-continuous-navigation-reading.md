# Reviewed Continuous Navigation And Reading Plan

> Status: active implementation plan. Form filling is intentionally out of scope.

## Goal

Allow the Agent to consume human-reviewed interface assets and repeatedly:

1. identify the current learned interface from a fresh observation;
2. choose one reviewed semantic transition or read action;
3. resolve the target again from the current capture;
4. pass Gate before any real click or scroll;
5. verify the action effect and next interface;
6. continue until the information goal is satisfied or a safe stop is required.

The learned graph remains guidance only. It never authorizes execution and never
provides reusable runtime coordinates.

## Task 1: Generic Agent Decision Context

**Files**

- Create: `app/agent/navigation_reading.py`
- Create: `tests/test_navigation_reading.py`

**Requirements**

- Accept only `agent_evidence_context_v1` interface evidence.
- Require `readiness.status == agent_usable` for automatic continuation.
- Expose reviewed transitions and on-demand read regions as semantic choices.
- Keep finite-detail and infinite-collection read strategies distinct.
- Require a current `capture_id`, screenshot checksum, and trace path.
- Reject final-submit/send/confirm/payment decisions.
- Return semantic plans only; omit bbox, click point, and historical coordinates.

## Task 2: Read Completion Semantics

**Files**

- Modify: `app/operation/reading.py`
- Modify: `app/gate/dataflow.py`
- Modify: `tests/test_read_region_batch.py`
- Modify: `tests/test_runtime_contracts.py`

**Requirements**

- Preserve separate stop reasons:
  `reached_bottom`, `no_new_content`, `max_captures`,
  `captures_exhausted`, and `wrong_scope_detected`.
- A finite detail read is complete only with explicit `reached_bottom`.
- `no_new_content` is stalled evidence, not proof of bottom.
- Infinite collections stop by a configured budget or no-new-content policy and
  remain resumable.
- The latest detail snapshot records the actual terminal state.

## Task 3: Continuous Session Integration

**Files**

- Modify: `app/agent/continuous_task_session.py`
- Modify: `tests/test_continuous_task_session.py`

**Requirements**

- Record generic Agent decisions without SEEK-specific vocabulary.
- Record read and scroll results independently from click transitions.
- Keep action dispatch and effect verification separate.
- Failed effect verification moves the session to human review.
- Successful verified navigation returns to observation.
- Successful read can remain on the same interface for another Agent decision.

## Task 4: Documentation And Verification

**Files**

- Modify: `ARCHITECTURE.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`

**Verification**

```powershell
uv run pytest tests/test_navigation_reading.py -q
uv run pytest tests/test_read_region_batch.py tests/test_runtime_contracts.py -q
uv run pytest tests/test_continuous_task_session.py -q
uv run pytest tests/test_agent_evidence.py tests/test_application_interface_graph.py -q
uv run python -m py_compile app/agent/navigation_reading.py app/agent/continuous_task_session.py app/operation/reading.py app/gate/dataflow.py
```

No live click or live scroll is required for this implementation checkpoint.
Fixture and trace-replay validation must pass before a real multi-interface run.

## Task 5: Generic Multi-Step Replay Contract

**Files**

- Create: `app/agent/navigation_reading_replay.py`
- Create: `tests/test_navigation_reading_replay.py`

**Requirements**

- Load only checksum-valid `single_interface_asset_v1` files whose human review
  compiles to `readiness.status=agent_usable`.
- Build a fresh `navigation_reading_agent_context_v1` for every observation.
- Consume recorded Agent choices as semantic decisions, not as operation
  coordinates.
- Require every transition result to carry separate Gate, dispatch, and
  destination-observation evidence.
- Require every read/scroll result to carry dispatch and effect evidence.
- Continue from the newly observed interface until the manifest goal is
  satisfied, a safe stop occurs, or a failure requires human review.
- Record per-layer results without one combined success-rate claim.

## Task 6: Replay Manifest And CLI

**Files**

- Create: `scripts/run_navigation_reading_replay.py`
- Create: `tests/fixtures/navigation_reading_replay/`
- Create: `tests/fixtures/navigation_reading_replay_manifest_v1.json`
- Modify: `tests/test_navigation_reading_replay.py`

**Requirements**

- Cover at least one multi-interface transition chain.
- Cover finite detail reading with explicit `reached_bottom`.
- Cover infinite collection scrolling with verified content change and bounded
  stop.
- Cover wrong-scope scrolling as `safe_stop`.
- Cover missing or stale reviewed assets as invalid fixtures excluded from
  attempted-session denominators.
- Save a UTF-8 JSON report with case outcomes, layer metrics, event history, and
  source artifact paths.
