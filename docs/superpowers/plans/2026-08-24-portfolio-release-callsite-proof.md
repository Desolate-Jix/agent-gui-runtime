# Portfolio v1 Release Callsite Proof Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove deterministically that the exact published Portfolio v1 release asset is consumed through the loopback local Agent Runtime callsite and production current-evidence composition, reaches exactly one fake `open_apply_flow` dispatch after server-owned confirmation, verifies the Apply Entry destination, and terminates with a durable `SAFE_STOP / stop_boundary` receipt.

**Architecture:** Package a sanitized, content-addressed snapshot of the exact release workflow, CAS object, and the two unique human-review image blobs as reproducible test fixtures. Build a temporary canonical workflow registry and CAS store from that package, then exercise the real `/runtime/agent` routes, `LocalAgentRuntimeCallsite`, `build_existing_windows_live_controller`, `ExistingWindowsCurrentEvidenceAdapter`, state resolution, action projection, grounding, Gate, visibility, durable claim/receipt stores, and post-state verification. Only external Windows/perception boundaries and the output backend are deterministic doubles; dispatch must use `DeterministicFakeBackend`, never physical Windows input.

**Tech Stack:** Python 3, FastAPI `TestClient`, pytest, Pydantic runtime contracts, repository CAS/claim/receipt stores, Pillow for PNG metadata inspection, Git small-step checkpoints.

**Spec:** `PROJECT_SUMMARY.md`, `ARCHITECTURE.md`, `CURRENT_STATE.md`, `NEXT_STEPS.md`, and the frozen Portfolio v1 release state recorded below.

## Global Constraints

- Do not read, copy, modify, stage, delete, or recommend committing the inherited untracked `tests/test_agent_runtime_actual_adapter_portfolio_v1.py`; it is outside this plan and must remain untouched.
- Do not run a physical Windows or SEEK click. `ExistingWindowsBackendAdapter` must not be instantiated by the acceptance test; use `DeterministicFakeBackend` only.
- Keep the production perception/current-evidence path intact: do not replace `ExistingWindowsCurrentEvidenceAdapter`, `ReviewedWorkflowGateAdapter`, `LiveController`, `RuntimeIntentClaimStore`, or `RuntimeReceiptStore` with a fake.
- Deterministic doubles may replace only the external window, screenshot, origin, UIA, recognition, visibility-fact, and output-dispatch boundaries needed to avoid physical I/O.
- The client request remains geometry-free. It may submit only the strict empty start body, the four Intent IDs, and confirmation ID plus decision.
- Human review evidence and the reviewed CAS artifact remain non-authorizing. Confirmation must not bypass fresh capture, current state resolution, re-grounding, Gate, pre-dispatch visibility, or fresh post-state verification.
- Portfolio v1 permits only `open_apply_flow` to the application-entry boundary. `fill_field`, `continue_next_step`, upload, `final_submit`, send, confirm, payment, ATS traversal, and form mutation are forbidden.
- Do not add a second real Desktop I/O backend, backend router, multi-active-asset selector, remote/MCP transport, panel runtime UI, or live SEEK proof in this plan.
- Do not change production code merely to make the proof convenient. If the RED test exposes a genuine common-layer failure, stop, record the violated invariant, and create a separately reviewed implementation plan before editing `app/`.
- Preserve UTF-8, existing newline style, and unrelated dirty changes. Do not stage any file not listed in the current task.
- Use small, single-purpose commits. Run the focused validation for each task before committing. Never push from this plan.

---

## Frozen Release Identity

The proof must reject any fixture whose identity differs from these values:

```text
asset_id = workflow_portfolio_v1_seek_apply_entry_fe297b5738f8c17790429e925ceab6f0
asset_content_sha256 = a9eb42d9439568770735f69ff109e6d93b86085507414d62ee49cfef33bb1d1b
source_workflow_id = portfolio_v1_seek_apply_entry
source_workflow_sha256 = 9ca9de68ae7a6dcd9f18c10384f2cefb63b6d83648ea10a95e1c5ef9c4283968
reviewed_revision_hash = 8e512cb94091ad8fd1c67afeba55ff68477c542da28de9da8f05de6416ce4ed7
current_revision_hash = 8e512cb94091ad8fd1c67afeba55ff68477c542da28de9da8f05de6416ce4ed7
evidence_sha256 = a201d537ebba727167bc0005e1a246213a5b6aa4a105fdbfb2ea011078a41fab
job_detail_node_revision_hash = 4d58e3774612275359a5627753e159697b036c66c614103d272b44c7612432c1
source_screenshot_sha256 = 274658095317e1aed1a9a68d6a3e7a80a6edddcde2e3d94bb11937932258ff1b
human_review_overlay_sha256 = 27478cff6c05724a6e5929c7b725764d79f2c5864ecf9c7d61bef503fac877cb
application_identity_key = web:nz.seek.com
canonical_origin = https://nz.seek.com
```

Required semantic shape:

```text
job_detail  -> availability=reviewed
apply_entry -> availability=stop_boundary
only transition -> semantic_action=open_apply_flow
transition requires_user_confirmation=true
transition target -> apply_entry
human_approved_node_ids -> [job_detail]
```

The release workflow ID and compiled asset ID are deliberately different and must remain distinct in `WorkflowRefV1`.

---

## Planned File Structure

Files this implementation will create:

```text
tests/fixtures/portfolio_v1_release_callsite/manifest.json
tests/fixtures/portfolio_v1_release_callsite/reviewed_workflow.json
tests/fixtures/portfolio_v1_release_callsite/reviewed_workflow_asset_v2.json
tests/fixtures/portfolio_v1_release_callsite/source_screenshot.png
tests/fixtures/portfolio_v1_release_callsite/human_review_overlay.png
tests/test_portfolio_v1_release_callsite.py
```

Files this implementation may update only after the proof passes:

```text
CURRENT_STATE.md
NEXT_STEPS.md
PROJECT_SUMMARY.md     # 仅在顶部 Portfolio 状态仍陈旧时修改
README.md              # 仅审查；只有公开状态陈旧时才修改
```

No `app/` file is expected to change.

Fixture responsibilities:

- `manifest.json`: immutable identity, hash, semantic-shape, application-identity, evidence-copy mapping, and non-authorization assertions.
- `reviewed_workflow.json`: byte-exact sanitized source workflow whose SHA-256 is the frozen source workflow hash.
- `reviewed_workflow_asset_v2.json`: byte-exact CAS object whose SHA-256 is the frozen asset content hash.
- `source_screenshot.png`: the one unique sanitized source image blob copied at test setup to both source-image paths declared by the reviewed workflow.
- `human_review_overlay.png`: the one unique reviewed overlay blob copied at test setup to both overlay paths declared by the reviewed workflow.
- `tests/test_portfolio_v1_release_callsite.py`: fixture integrity, temporary package construction, route-level confirmation/execution/verification, restart/idempotence, and negative-control assertions.

---

### Task 1: Package and verify the exact sanitized release fixture

**Files:**
- Create: `tests/fixtures/portfolio_v1_release_callsite/manifest.json`
- Create: `tests/fixtures/portfolio_v1_release_callsite/reviewed_workflow.json`
- Create: `tests/fixtures/portfolio_v1_release_callsite/reviewed_workflow_asset_v2.json`
- Create: `tests/fixtures/portfolio_v1_release_callsite/source_screenshot.png`
- Create: `tests/fixtures/portfolio_v1_release_callsite/human_review_overlay.png`
- Create: `tests/test_portfolio_v1_release_callsite.py`

**Interfaces:**
- Consumes: the frozen hashes and semantic shape above; `app.agent.reviewed_workflow_asset.validate_reviewed_workflow_asset`; `content_sha256`.
- Produces: `_load_release_fixture() -> tuple[dict[str, object], dict[str, object], dict[str, object]]` and `_materialize_release_project(tmp_path: Path) -> tuple[dict[str, object], ReviewedWorkflowAssetStore]` for later route-level tasks.

- [ ] **Step 1: Confirm the inherited dirty-file boundary without reading it**

Run:

```powershell
git status --short --untracked-files=all
```

Expected: `tests/test_agent_runtime_actual_adapter_portfolio_v1.py` may appear as inherited untracked state. Record its presence only. Do not open it and do not include it in any `git add` command.

- [ ] **Step 2: Write the failing fixture integrity test before copying fixtures**

Create `tests/test_portfolio_v1_release_callsite.py` with explicit constants and a test equivalent to:

```python
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from app.agent.reviewed_workflow_asset import (
    content_sha256,
    validate_reviewed_workflow_asset,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "portfolio_v1_release_callsite"
ASSET_ID = "workflow_portfolio_v1_seek_apply_entry_fe297b5738f8c17790429e925ceab6f0"
ASSET_SHA256 = "a9eb42d9439568770735f69ff109e6d93b86085507414d62ee49cfef33bb1d1b"
SOURCE_WORKFLOW_ID = "portfolio_v1_seek_apply_entry"
SOURCE_WORKFLOW_SHA256 = "9ca9de68ae7a6dcd9f18c10384f2cefb63b6d83648ea10a95e1c5ef9c4283968"
SOURCE_SCREENSHOT_SHA256 = "274658095317e1aed1a9a68d6a3e7a80a6edddcde2e3d94bb11937932258ff1b"
HUMAN_REVIEW_OVERLAY_SHA256 = "27478cff6c05724a6e5929c7b725764d79f2c5864ecf9c7d61bef503fac877cb"


def _json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    assert isinstance(value, dict)
    return value


def test_exact_portfolio_release_fixture_is_content_addressed_and_non_authorizing() -> None:
    manifest_path = FIXTURE_ROOT / "manifest.json"
    workflow_path = FIXTURE_ROOT / "reviewed_workflow.json"
    asset_path = FIXTURE_ROOT / "reviewed_workflow_asset_v2.json"
    source_path = FIXTURE_ROOT / "source_screenshot.png"
    overlay_path = FIXTURE_ROOT / "human_review_overlay.png"

    manifest = _json(manifest_path)
    workflow = _json(workflow_path)
    asset = validate_reviewed_workflow_asset(_json(asset_path))
    assert sha256(workflow_path.read_bytes()).hexdigest() == SOURCE_WORKFLOW_SHA256
    assert sha256(asset_path.read_bytes()).hexdigest() == ASSET_SHA256
    assert content_sha256(asset) == ASSET_SHA256
    assert sha256(source_path.read_bytes()).hexdigest() == SOURCE_SCREENSHOT_SHA256
    assert sha256(overlay_path.read_bytes()).hexdigest() == HUMAN_REVIEW_OVERLAY_SHA256
    assert manifest["asset_id"] == asset["asset_id"] == ASSET_ID
    assert asset["source_review_lineage"]["source_workflow_id"] == SOURCE_WORKFLOW_ID
    assert asset["source_review_lineage"]["source_workflow_sha256"] == SOURCE_WORKFLOW_SHA256
    assert asset["safety"] == {
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
        "fresh_grounding_required": True,
        "historical_coordinates_used": False,
        "post_action_verification_required": True,
        "real_action_requires_gate": True,
    }
    assert workflow["workflow"]["workflow_id"] == SOURCE_WORKFLOW_ID
```

- [ ] **Step 3: Run the test to prove RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_portfolio_v1_release_callsite.py::test_exact_portfolio_release_fixture_is_content_addressed_and_non_authorizing
```

Expected: FAIL because the fixture files do not yet exist. A different failure must be diagnosed before continuing.

- [ ] **Step 4: Create the byte-exact fixture package**

Copy only the five sanitized fixture files listed in this task. Do not copy runtime claims, receipts, browser profiles, raw traces, absolute-path registry JSON, credentials, or unrelated artifacts. `manifest.json` must contain these explicit fields:

Use these exact source-to-fixture mappings; verify every source hash before copying:

```text
runtime_state/reviewed-workflow-assets-v2/objects/a9eb42d9439568770735f69ff109e6d93b86085507414d62ee49cfef33bb1d1b.json
  -> tests/fixtures/portfolio_v1_release_callsite/reviewed_workflow_asset_v2.json

artifacts/interface-workflow-reviews/portfolio_v1_seek_apply_entry/reviewed_workflow.json
  -> tests/fixtures/portfolio_v1_release_callsite/reviewed_workflow.json

artifacts/interface-workflow-reviews/portfolio_v1_seek_apply_entry/node-evidence/job_detail/source_screenshot_path.png
  -> tests/fixtures/portfolio_v1_release_callsite/source_screenshot.png

artifacts/interface-workflow-reviews/portfolio_v1_seek_apply_entry/node-evidence/job_detail/human_review_overlay_path.png
  -> tests/fixtures/portfolio_v1_release_callsite/human_review_overlay.png

create from the frozen JSON below
  -> tests/fixtures/portfolio_v1_release_callsite/manifest.json
```

The workflow references a second source-image path and a second overlay path with the same hashes. Do not commit duplicate PNG blobs; Task 2 copies each unique fixture blob to both canonical temporary evidence paths.

```json
{
  "contract_version": "portfolio_v1_release_callsite_fixture_v1",
  "asset_id": "workflow_portfolio_v1_seek_apply_entry_fe297b5738f8c17790429e925ceab6f0",
  "asset_content_sha256": "a9eb42d9439568770735f69ff109e6d93b86085507414d62ee49cfef33bb1d1b",
  "source_workflow_id": "portfolio_v1_seek_apply_entry",
  "source_workflow_sha256": "9ca9de68ae7a6dcd9f18c10384f2cefb63b6d83648ea10a95e1c5ef9c4283968",
  "reviewed_revision_hash": "8e512cb94091ad8fd1c67afeba55ff68477c542da28de9da8f05de6416ce4ed7",
  "current_revision_hash": "8e512cb94091ad8fd1c67afeba55ff68477c542da28de9da8f05de6416ce4ed7",
  "evidence_sha256": "a201d537ebba727167bc0005e1a246213a5b6aa4a105fdbfb2ea011078a41fab",
  "job_detail_node_revision_hash": "4d58e3774612275359a5627753e159697b036c66c614103d272b44c7612432c1",
  "source_screenshot_sha256": "274658095317e1aed1a9a68d6a3e7a80a6edddcde2e3d94bb11937932258ff1b",
  "human_review_overlay_sha256": "27478cff6c05724a6e5929c7b725764d79f2c5864ecf9c7d61bef503fac877cb",
  "application_identity_key": "web:nz.seek.com",
  "canonical_origin": "https://nz.seek.com",
  "application_identity": {
    "contract_version": "application_identity_v1",
    "identity_schema_version": 1,
    "kind": "web",
    "identity_key": "web:nz.seek.com",
    "identity_status": "resolved",
    "name": "nz.seek.com",
    "display_name": "nz.seek.com",
    "canonical_domain": "nz.seek.com",
    "canonical_origin": "https://nz.seek.com",
    "executable_identity": null,
    "product_identity": null,
    "source_evidence": {
      "url_or_domain_provided": true,
      "browser_process_detected": false
    },
    "artifact_is_authorization": false
  },
  "human_approved_node_ids": ["job_detail"],
  "reviewed_state_source_node_id": "job_detail",
  "stop_boundary_source_node_id": "apply_entry",
  "semantic_action": "open_apply_flow",
  "requires_user_confirmation": true,
  "artifact_is_authorization": false,
  "execute_binding_enabled": false,
  "fixture_is_live_proof": false
}
```

- [ ] **Step 5: Extend the fixture integrity test with semantic-shape assertions**

Add assertions that:

```python
states = {item["source_node_id"]: item for item in asset["states"]}
assert states["job_detail"]["availability"] == "reviewed"
assert states["apply_entry"]["availability"] == "stop_boundary"
assert states["apply_entry"]["allowed_transition_ids"] == []
assert len(asset["transitions"]) == 1
transition = asset["transitions"][0]
assert transition["semantic_action"] == "open_apply_flow"
assert transition["source_state_id"] == states["job_detail"]["state_id"]
assert transition["target_state_id"] == states["apply_entry"]["state_id"]
assert transition["risk_policy"]["requires_user_confirmation"] is True
assert transition["risk_policy"]["automatic_execution_allowed"] is False
assert asset["source_review_lineage"]["human_approved_node_ids"] == ["job_detail"]
assert ASSET_ID != SOURCE_WORKFLOW_ID
```

- [ ] **Step 6: Run fixture integrity GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_portfolio_v1_release_callsite.py::test_exact_portfolio_release_fixture_is_content_addressed_and_non_authorizing
```

Expected: `1 passed`.

- [ ] **Step 7: Run privacy, metadata, and secret checks before staging**

First render both PNGs with the repository image-viewing tool and confirm visually that they contain no name, email, phone number, account identifier, resume, address, browser profile, authentication data, or unrelated private UI.

Run PNG metadata inspection:

```powershell
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe -c "from pathlib import Path; from PIL import Image; root=Path('tests/fixtures/portfolio_v1_release_callsite'); [(lambda im,p: (print(p, im.size, im.mode, sorted(im.text)), (_ for _ in ()).throw(AssertionError(f'text metadata in {p}')) if im.text else None, (_ for _ in ()).throw(AssertionError(f'EXIF metadata in {p}')) if len(im.getexif()) else None))(Image.open(p),p) for p in [root/'source_screenshot.png',root/'human_review_overlay.png']]"
```

Expected: both files print dimensions/mode with an empty text-key list and no assertion.

Run text fixture scan:

```powershell
rg -n -i --glob '*.json' '(C:\\Users\\|DesolateJix|Bearer[[:space:]]+[A-Za-z0-9._-]+|api[_-]?key|secret|password|token)' tests/fixtures/portfolio_v1_release_callsite
```

Expected: no matches. If a semantic field name such as `artifact_is_authorization` is the only false positive, narrow the expression and rerun; never waive a value-level credential match.

- [ ] **Step 8: Commit the fixture contract atomically**

Run:

```powershell
git add -- tests/fixtures/portfolio_v1_release_callsite tests/test_portfolio_v1_release_callsite.py
git diff --cached --check
git diff --cached --name-only
git commit -m "test(runtime): add portfolio release fixture contract"
```

Expected staged paths: only the six Task 1 paths. The inherited untracked test and unrelated dirty files must not be staged.

---

### Task 2: Materialize the release package in an isolated temporary project

**Files:**
- Modify: `tests/test_portfolio_v1_release_callsite.py`

**Interfaces:**
- Consumes: Task 1 fixture package; `ReviewedWorkflowAssetStore.publish`; `load_interface_workflow_agent_context`.
- Produces: a tmp project whose canonical reviewed-workflow registry, evidence paths, source workflow bytes, and active CAS object validate exactly like the release package.

- [ ] **Step 1: Write a failing materialization test**

Add `test_release_fixture_materializes_exact_active_asset_and_agent_context(tmp_path)` before writing its helper. It must require:

```python
asset, store = _materialize_release_project(tmp_path)
registry = store.registry()
assert registry["registry_revision"] == 1
assert registry["active_by_asset"] == {ASSET_ID: ASSET_SHA256}
assert content_sha256(store.load_active(ASSET_ID)) == ASSET_SHA256
context = load_interface_workflow_agent_context(
    project_root=tmp_path,
    application_identity_key="web:nz.seek.com",
)
assert context["artifact_is_authorization"] is False
assert context["execute_binding_enabled"] is False
assert context["agent_usable_interfaces"] == [{
    "workflow_id": SOURCE_WORKFLOW_ID,
    "interface_id": "job_detail",
    "display_name": "Job Detail",
    "agent_usable": True,
}]
assert any(
    item.get("interface_id") == "apply_entry"
    for item in context["blocked_interfaces"]
)
```

- [ ] **Step 2: Run the materialization test to prove RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_portfolio_v1_release_callsite.py::test_release_fixture_materializes_exact_active_asset_and_agent_context
```

Expected: FAIL because `_materialize_release_project` is not defined.

- [ ] **Step 3: Implement temporary canonical layout without weakening integrity**

The helper must:

1. copy `reviewed_workflow.json` byte-for-byte to `artifacts/interface-workflow-reviews/portfolio_v1_seek_apply_entry/reviewed_workflow.json`;
2. copy `source_screenshot.png` to both source-image paths already declared by the workflow;
3. copy `human_review_overlay.png` to both overlay paths already declared by the workflow;
4. write a minimal `interface_workflow_library_registry_v1` containing only `web:nz.seek.com` and `portfolio_v1_seek_apply_entry`;
5. keep the exact source SHA, reviewed node revision hash, and evidence-provenance hashes from the manifest;
6. use an absolute workflow path only inside the temporary registry, never inside a committed fixture;
7. publish the exact asset with `ReviewedWorkflowAssetStore(project_root=tmp_path).publish(asset, expected_registry_revision=0)`;
8. assert publish status is `published`, object SHA is `ASSET_SHA256`, and the input asset was not mutated.

The minimal registry must have exactly this outer shape:

```python
registry = {
    "contract_version": "interface_workflow_library_registry_v1",
    "registry_revision": 1,
    "applications": {
        "web:nz.seek.com": {
            "application_identity": manifest["application_identity"],
            "workflow_ids": [SOURCE_WORKFLOW_ID],
            "artifact_is_authorization": False,
        }
    },
    "workflows": {
        SOURCE_WORKFLOW_ID: {
            "path": str(materialized_workflow_path),
            "application_identity_key": "web:nz.seek.com",
            "goal": workflow["workflow"]["goal"],
            "node_count": 2,
            "edge_count": 1,
            "reviewed_node_revision_hashes": {
                "job_detail": manifest["job_detail_node_revision_hash"],
            },
            "reviewed_node_evidence_sha256": {
                "job_detail": {
                    "source_paths_sha256": expected_source_paths_sha256,
                    "human_review_overlay_path": HUMAN_REVIEW_OVERLAY_SHA256,
                    "review_revision_human_review_overlay_path": HUMAN_REVIEW_OVERLAY_SHA256,
                    "review_revision_source_screenshot_path": SOURCE_SCREENSHOT_SHA256,
                    "source_screenshot_path": SOURCE_SCREENSHOT_SHA256,
                }
            },
            "source_asset_sha256": SOURCE_WORKFLOW_SHA256,
            "review_status": "needs_human_review",
            "published": False,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    },
    "artifact_is_authorization": False,
}
```

Calculate `expected_source_paths_sha256` from the ordered `job_detail.source_paths` array with compact UTF-8 JSON, exactly as `_node_evidence_provenance` does; do not hard-code or bypass the integrity function.

- [ ] **Step 4: Run materialization and complete-file tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_portfolio_v1_release_callsite.py
```

Expected: both fixture tests pass.

- [ ] **Step 5: Commit the materialization harness**

Run:

```powershell
git add -- tests/test_portfolio_v1_release_callsite.py
git diff --cached --check
git diff --cached --name-only
git commit -m "test(runtime): materialize portfolio release package"
```

Expected staged path: only `tests/test_portfolio_v1_release_callsite.py`.

---

### Task 3: Prove route-level confirmation, one dispatch, Apply Entry verification, and restart idempotence

**Files:**
- Modify: `tests/test_portfolio_v1_release_callsite.py`

**Interfaces:**
- Consumes: Task 2 temporary release project; `LocalAgentRuntimeCallsite`; `/runtime/agent/session/start`, `/intent/submit`, `/confirmation/decide`; production composition factory.
- Produces: one deterministic end-to-end release-callsite proof with a durable terminal receipt and zero physical input.

- [ ] **Step 1: Write the failing route-level acceptance test**

Add:

```python
def test_exact_release_asset_runs_through_local_callsite_and_safe_stops(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset, asset_store = _materialize_release_project(tmp_path)
    assert asset["asset_id"] == ASSET_ID
    assert content_sha256(asset_store.load_active(ASSET_ID)) == ASSET_SHA256
```

The test must use `LocalAgentRuntimeCallsite` without passing a custom `controller_factory`. This is what proves the default `build_existing_windows_live_controller` path is used.

The test may monkeypatch only these external boundaries before the callsite creates its controller:

```text
app.core.screenshot.screenshot_service
app.core.window_manager.window_manager
app.operation.screen_reading.uia_provider.uia_provider
app.agent.live_runtime_composition.WindowsUIAOriginReader
app.agent.live_runtime_composition._run_existing_read_only_recognition
app.agent.live_runtime_composition.ExistingWindowsBackendAdapter
```

The last symbol must return the single test-owned `DeterministicFakeBackend`; it must never return the real Windows adapter.

- [ ] **Step 2: Prepare deterministic current-evidence sequences**

The sequence must represent:

```text
capture 1: initial Job Detail observation
capture 2: fresh Job Detail observation before confirmation is requested
capture 3: fresh Job Detail observation after approved confirmation
capture 4: exact-pixel pre-dispatch freshness check for capture 3
capture 5: fresh Apply Entry post-dispatch observation
```

Recognition results must be generated from the exact asset anchor IDs and must yield:

```text
Job Detail -> unique state resolution
Quick apply -> unique current top candidate with adequate confidence/margin
Apply Entry -> unique stop-boundary state resolution
```

The screenshot bytes for capture 3 and capture 4 must be identical. Capture 5 must differ from capture 4. All captures remain local test files under `tmp_path`.

- [ ] **Step 3: Run the acceptance test to prove RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_portfolio_v1_release_callsite.py::test_exact_release_asset_runs_through_local_callsite_and_safe_stops
```

Expected: FAIL until the deterministic harness supplies the complete current-evidence sequence and default composition dependency patching.

- [ ] **Step 4: Implement route client and strict start assertions**

Create a minimal FastAPI app that includes only `app.api.agent_runtime.router`, and override `get_agent_runtime_callsite` with the current test-owned callsite. Use a loopback TestClient address.

Call:

```python
started = client.post("/runtime/agent/session/start", json={})
```

Assert HTTP 200 and:

```python
observation["workflow"] == {
    "workflow_id": SOURCE_WORKFLOW_ID,
    "asset_id": ASSET_ID,
    "asset_content_sha256": ASSET_SHA256,
    "source_workflow_sha256": SOURCE_WORKFLOW_SHA256,
    "reviewed_revision_hash": "8e512cb94091ad8fd1c67afeba55ff68477c542da28de9da8f05de6416ce4ed7",
}
assert observation["workflow"]["workflow_id"] != observation["workflow"]["asset_id"]
assert observation["state"]["source_interface_id"] == "job_detail"
assert [item["semantic_action"] for item in observation["available_actions"]] == [
    "open_apply_flow",
    "safe_stop",
]
```

The selected action ID must be the opaque compiled transition ID, not the string `open_apply_flow`.

- [ ] **Step 5: Prove server-owned confirmation with zero pre-approval dispatch**

Submit exactly:

```python
intent_payload = {
    "intent_id": "intent.portfolio-release-open-apply",
    "session_id": observation["session_id"],
    "observation_id": observation["observation_id"],
    "action_id": open_apply_action["action_id"],
}
```

Assert the request has exactly four keys and the response is:

```text
status = NEEDS_REVIEW
reason_code = human_confirmation_required
confirmation_id = non-empty
```

At this point:

```python
assert fake_backend.attempt_count == 0
assert fake_backend.dispatch_count == 0
assert fake_backend.commands == []
```

- [ ] **Step 6: Simulate process-local callsite restart before approval**

Discard the first `LocalAgentRuntimeCallsite` and route dependency override. Construct a fresh callsite from the same temporary asset store, durable claim store root, deterministic external-boundary sequence, and fake backend. Do not reuse in-memory session/observation fields from the first callsite except the client-owned four Intent IDs and returned confirmation ID.

This is a deterministic service-reconstruction proof, not a claim of a physical OS process restart or live browser recovery.

- [ ] **Step 7: Approve with only confirmation ID and decision**

Call:

```python
approved = restarted_client.post(
    "/runtime/agent/confirmation/decide",
    json={"confirmation_id": confirmation_id, "decision": "approved"},
)
```

Assert HTTP 200 and the exact terminal semantics:

```python
assert receipt["workflow"] == observation["workflow"]
assert receipt["action"] == {
    "action_id": open_apply_action["action_id"],
    "semantic_action": "open_apply_flow",
}
assert receipt["outcome"] == "SAFE_STOP"
assert receipt["reason_code"] == "stop_boundary"
assert receipt["attempt_count"] == 1
assert receipt["gate_status"] == "allowed"
assert receipt["dispatch_status"] == "dispatched"
assert receipt["effect_status"] == "verified"
assert receipt["destination_status"] == "verified"
assert receipt["safe_stop"] == {
    "required": True,
    "reason_code": "stop_boundary",
}
assert receipt["next_observation_id"]
```

All six receipt evidence references must be non-empty:

```text
state_resolution_ref
selection_ref
candidate_ref
gate_decision_ref
backend_receipt_ref
verification_ref
```

- [ ] **Step 8: Prove exactly one fake dispatch and current-coordinate lineage**

Assert:

```python
assert fake_backend.attempt_count == 1
assert fake_backend.dispatch_count == 1
assert len(fake_backend.commands) == 1
command = fake_backend.commands[0]
assert command.semantic_action == "open_apply_flow"
assert command.target_window_handle == 4242
assert command.capture_id in receipt["evidence"]["candidate_ref"]
assert command.candidate_id in receipt["evidence"]["candidate_ref"]
```

The stable window double must record exactly one pre-dispatch point-visibility check matching `command.click_point`.

- [ ] **Step 9: Prove durable receipt, Apply Entry boundary, and forbidden-action absence**

Reload the terminal record from `RuntimeReceiptStore(project_root=tmp_path)`. Assert:

```python
assert persisted.runtime_receipt.model_dump(mode="json") == receipt
assert persisted.backend_receipt.receipt_ref == receipt["evidence"]["backend_receipt_ref"]
assert persisted.verification_evidence["status"] == "verified"
assert persisted.verification_evidence["post_state_resolution"]["state_id"] == apply_entry_state_id
assert persisted.next_observation.observation_id == receipt["next_observation_id"]
assert persisted.next_observation.state.status == "stop_boundary"
assert persisted.next_observation.state.state_availability == "stop_boundary"
assert [item.semantic_action for item in persisted.next_observation.available_actions] == ["safe_stop"]
```

Serialize the receipt plus next observation with `ensure_ascii=False` and assert none of these strings appears:

```text
fill_field
continue_next_step
final_submit
submit_application
upload_document
```

- [ ] **Step 10: Prove terminal replay idempotence after another callsite reconstruction**

Create a third callsite over the same stores. Repeat both approval and Intent requests. Both responses must equal the exact persisted receipt. Capture count, recognition count, fake backend attempt count, and fake backend dispatch count must remain unchanged.

- [ ] **Step 11: Run the focused route proof GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_portfolio_v1_release_callsite.py::test_exact_release_asset_runs_through_local_callsite_and_safe_stops
```

Expected: `1 passed`, with no physical input or network access.

- [ ] **Step 12: Run the complete new proof file**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_portfolio_v1_release_callsite.py
```

Expected: every fixture/materialization/route assertion passes.

- [ ] **Step 13: Commit the route proof atomically**

Run:

```powershell
git add -- tests/test_portfolio_v1_release_callsite.py
git diff --cached --check
git diff --cached --name-only
git commit -m "test(runtime): prove portfolio callsite safe stop"
```

Expected staged path: only `tests/test_portfolio_v1_release_callsite.py`.

---

### Task 4: Run adjacent regressions and independent safety review

**Files:**
- No production-file changes expected.
- Modify `tests/test_portfolio_v1_release_callsite.py` only if the new proof itself is defective.

**Interfaces:**
- Consumes: completed release proof.
- Produces: regression evidence that the proof did not weaken contracts, Gate, backend authority, claim recovery, receipt pairing, or prior Portfolio composition.

- [ ] **Step 1: Run the focused and adjacent Python matrix**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_portfolio_v1_release_callsite.py `
  tests/test_agent_runtime_api_v1.py `
  tests/test_live_controller_portfolio_confirmation_v1.py `
  tests/test_live_runtime_composition_w3b.py `
  tests/test_portfolio_v1_reviewed_asset.py `
  tests/test_agent_observation_adapter_v1.py `
  tests/test_reviewed_workflow_replay_v2.py `
  tests/test_desktop_backend_w4.py `
  tests/test_runtime_intent_claim_store_w3b.py `
  tests/test_runtime_receipt_store_w3b.py
```

Expected: all selected tests pass. Do not label this a full-repository baseline.

- [ ] **Step 2: Compile the touched production import surface without changing it**

Run:

```powershell
.\.venv\Scripts\python.exe -m py_compile `
  app/api/agent_runtime.py `
  app/agent/live_controller.py `
  app/agent/live_runtime_composition.py `
  app/agent/agent_observation_adapter.py `
  app/agent/reviewed_workflow_replay.py `
  app/agent/reviewed_workflow_gate.py `
  app/agent/desktop_backend.py `
  app/agent/runtime_intent_claim_store.py `
  app/agent/runtime_receipt_store.py
```

Expected: exit code 0.

- [ ] **Step 3: Review exact diff and safety invariants**

Review must confirm:

```text
exact release asset ID/hash is asserted
source workflow ID remains distinct from asset ID
default LocalAgentRuntimeCallsite controller factory is exercised
production ExistingWindowsCurrentEvidenceAdapter remains in the path
DeterministicFakeBackend is the only dispatch backend
confirmation produces zero pre-approval dispatch
approval repeats fresh runtime checks
exactly one fake dispatch occurs
fresh Apply Entry C2 verifies destination
terminal result is SAFE_STOP/stop_boundary
duplicate/restart requests produce zero redispatch
no forbidden form/Continue/final-submit action is projected
fixtures contain no secrets or personal information
```

- [ ] **Step 4: Commit only if review requires a proof-only correction**

If the review finds a defect in the new proof, fix only the proof file, rerun Tasks 3 and 4, then commit:

```powershell
git add -- tests/test_portfolio_v1_release_callsite.py
git diff --cached --check
git commit -m "test(runtime): tighten release callsite proof"
```

If review passes without changes, create no empty commit.

---

### Task 5: Synchronize truthful release status documentation

**Files:**
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`
- Review and conditionally modify: `PROJECT_SUMMARY.md`
- Review and conditionally modify: `README.md`

**Interfaces:**
- Consumes: exact test commands and results from Tasks 1–4.
- Produces: an evidence-bounded status update that distinguishes deterministic production-adapter composition from physical/live proof.

- [ ] **Step 1: Update current-state wording**

Replace only stale top-level claims that say the release asset actual-adapter `open_apply_flow` path is unproven. Record:

```text
exact Portfolio release asset + loopback LocalAgentRuntimeCallsite
production ExistingWindowsCurrentEvidenceAdapter
server-owned confirmation and restart recovery
exactly one DeterministicFakeBackend dispatch
fresh C2 Apply Entry verification
SAFE_STOP / stop_boundary terminal receipt
duplicate/restart zero redispatch
```

The same paragraph must state:

```text
deterministic external-boundary doubles
fake output backend
no physical Windows input
no live SEEK proof
no provider-accuracy proof
no form fill, Continue/Next, upload, or final submit
```

- [ ] **Step 2: Update next-step ordering**

Move the release-callsite deterministic proof from pending to complete. The next ordered item becomes controlled live SEEK proof with matched current-capture, Gate, dispatch, verification, and receipt evidence, followed by W6 close-out. Do not broaden the live target beyond already-open Job Detail → Quick Apply entry → Safe Stop.

- [ ] **Step 3: Review public documents for stale claims**

Change `PROJECT_SUMMARY.md` only if its top Portfolio summary still says this exact deterministic proof is missing. Change `README.md` only if its Current Status or Demo/Evidence section contains the same stale statement. Do not add production-ready, unattended, model-accuracy, or live-demo claims.

- [ ] **Step 4: Validate documentation and focused proof together**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_portfolio_v1_release_callsite.py
git diff --check
```

Expected: tests pass and Git reports no whitespace errors.

- [ ] **Step 5: Commit documentation separately**

Run:

```powershell
$trackedDocs = @()
foreach ($path in @('PROJECT_SUMMARY.md', 'README.md')) {
  git ls-files --error-unmatch -- $path 2>$null | Out-Null
  if ($LASTEXITCODE -eq 0 -and (git diff --name-only -- $path)) {
    $trackedDocs += $path
  }
}
if ($trackedDocs.Count -gt 0) {
  git add -- $trackedDocs
}
git diff --cached --check
git diff --cached --name-only
if ($trackedDocs.Count -gt 0) {
  git commit -m "docs(runtime): record release callsite proof"
}
```

Before committing, verify the staged list contains only documentation intentionally changed in this task. `CURRENT_STATE.md` and `NEXT_STEPS.md` are local ignored status documents in the current repository; update them locally, do not force-add them, and report their paths and validation. If neither tracked public document changes, create no empty documentation commit.

---

## Final Acceptance Checklist

- [ ] Exact release asset SHA is asserted from raw fixture bytes and canonical asset validation.
- [ ] Exact reviewed workflow SHA and source workflow ID are asserted.
- [ ] Sanitized image hashes and absence of embedded metadata are verified.
- [ ] Fixture registry validates Job Detail as Agent-usable and Apply Entry as a blocked/unreviewed stop boundary.
- [ ] Local route start resolves the sole active asset and a current positive HWND/PID.
- [ ] Initial Observation exposes only `open_apply_flow` plus `safe_stop`.
- [ ] Client Intent contains exactly four IDs and no geometry/authority/provider/backend/path data.
- [ ] First Intent submission produces human confirmation and zero dispatch.
- [ ] Fresh callsite reconstructs the durable confirmation claim.
- [ ] Approval contains only confirmation ID and decision.
- [ ] Fresh capture/state/re-ground/Gate/pixel-freshness/visibility runs after approval.
- [ ] Fake backend attempts and dispatches exactly once.
- [ ] Fresh C2 resolves Apply Entry and verifies the target state.
- [ ] Receipt is durable `SAFE_STOP / stop_boundary`, not merely `DISPATCHED`.
- [ ] Next Observation exposes only `safe_stop`.
- [ ] Duplicate Intent and approval after reconstruction return the exact terminal receipt with zero additional capture, recognition, attempt, or dispatch.
- [ ] No physical Windows/SEEK action occurred.
- [ ] No form mutation or terminal action entered the projection or receipt.
- [ ] Focused and adjacent tests pass.
- [ ] Documentation reflects deterministic fake-I/O proof only.
- [ ] Inherited untracked `tests/test_agent_runtime_actual_adapter_portfolio_v1.py` remains untouched and unstaged.

## Atomic Commit Strategy

Expected implementation commits, each only after its focused validation passes:

```text
test(runtime): add portfolio release fixture contract
test(runtime): materialize portfolio release package
test(runtime): prove portfolio callsite safe stop
test(runtime): tighten release callsite proof        # 仅在独立审查要求修正时
docs(runtime): record release callsite proof
```

Do not squash these checkpoints during implementation. Do not push automatically. Final reporting must list every created commit hash, message, files, and exact test results.

## Explicitly Out of Scope

- Physical `ExistingWindowsBackendAdapter` dispatch.
- Real SEEK navigation or browser state mutation.
- Homepage/results traversal or `open_detail` expansion.
- Form fill, document upload, Continue/Next, final submit, send, confirm, or payment.
- Perception/provider accuracy benchmarking.
- A second Desktop I/O backend or backend capability router.
- Multi-active-asset selection or remote/MCP Agent transport.
- Panel execution UI.
- Production readiness, unattended reliability, or Controlled Live Workflow completion claims.
