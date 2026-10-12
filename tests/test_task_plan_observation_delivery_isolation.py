"""真实审核包的当前图、祖先重放与拒绝路径都不能初始化桌面 COM。"""
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def evidence_scene(root):
    root.mkdir()
    def reference(path):
        return {"path": path.relative_to(root).as_posix(), "sha256": sha256(path.read_bytes()).hexdigest()}
    def save(name, value):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return reference(path)
    def frame(name, color, role):
        path = root / "task-plan-observations" / (name + ".png")
        path.parent.mkdir(exist_ok=True)
        Image.new("RGB", (8, 6), color).save(path)
        return {"capture_id": name, "image_path": str(path), "sha256": reference(path)["sha256"],
            "window_identity": {"handle": 11, "process_id": 22, "process_create_time": 33.0}, "role": role}
    original = frame("original", "black", "after")
    source_ref = save("source.json", {"schema": "offline-evidence-source"})
    refs = [reference(Path(original["image_path"]))]
    base = {"schema": "review_packet.v2", "run_id": "run-one", "step_id": "step-one",
        "execution_request_id": "execution-one", "wait_id": "wait-one", "plan_id": "plan-one",
        "plan_sha256": "a" * 64, "source_ref": source_ref, "owner_id": "owner-one",
        "session_directory": str(root), "target_identity": deepcopy(original["window_identity"]),
        "goal": "Read the visible detail", "step_goal": "Open the detail", "remaining_plan": [],
        "expected_condition": "The detail is visible.", "original_input_status": "completed",
        "action_executed": True, "reason": "agent_review_required", "suggested_verdict": "uncertain",
        "policy_snapshot": {}, "profile_sha256": None, "budget": None, "assessment": None,
        "after": original, "evidence_refs": refs, "input_evidence_refs": deepcopy(refs),
        "artifact_refs": deepcopy(refs), "artifact_set_sha256": digest(refs),
        "evidence_set_sha256": digest(refs), "assessment_round": 0, "assessment_ref": None,
        "allowed_controls": ["review", "cancel"], "automatic_retry_allowed": False,
        "authorizes_action": False, "original_receipt_sha256": "b" * 64}
    base["packet_sha256"] = digest(base)
    entries = {"requests": {}, "revisions": []}
    previous, outcomes = base, []
    for number, color in ((1, "blue"), (2, "green")):
        observed = frame("manual-" + str(number), color, "observation")
        request = {"action": "observe", "run_id": "run-one", "step_id": "step-one",
            "execution_request_id": "execution-one", "wait_id": "wait-one",
            "observation_request_id": "manual-" + str(number), "review_packet_sha256": previous["packet_sha256"],
            "evidence_set_sha256": previous["evidence_set_sha256"], "assessment_round": 0}
        budget = {"limit": 2, "used": number, "remaining": 2 - number}
        previous_ref = save("records/previous-" + str(number) + ".json", previous)
        record = {"schema": "task_plan_manual_observation_record.v1", "request": request,
            "frame": observed, "image_ref": reference(Path(observed["image_path"])),
            "elapsed_ns": 1, "capture_elapsed_ms": 0.001, "capture_budget": budget}
        record_ref = save("records/capture-" + str(number) + ".json", record)
        inputs = [*previous["input_evidence_refs"], record["image_ref"]]
        refs = [*previous["evidence_refs"], previous_ref, record["image_ref"], record_ref]
        packet = {key: deepcopy(value) for key, value in previous.items() if key != "packet_sha256"}
        packet.update(schema="review_packet.v3", latest_observation=observed, packet_revision=number,
            previous_packet_sha256=previous["packet_sha256"],
            packet_ancestors=[*previous.get("packet_ancestors", []), previous["packet_sha256"]],
            assessment_basis=deepcopy(previous.get("assessment_basis", {"packet_sha256": previous["packet_sha256"],
                "evidence_set_sha256": previous["evidence_set_sha256"], "assessment_round": 0})),
            input_evidence_refs=inputs, evidence_set_sha256=digest(inputs), evidence_refs=refs,
            artifact_refs=deepcopy(refs), artifact_set_sha256=digest(refs), manual_observation_budget=budget,
            allowed_controls=["review", *(["observe"] if number == 1 else []), "cancel"])
        packet["packet_sha256"] = digest(packet)
        packet_ref = save("records/packet-" + str(number) + ".json", packet)
        outcome = {"schema": "task_plan_manual_observation_result.v1", "run_id": "run-one",
            "execution_request_id": "execution-one", "observation_request_id": request["observation_request_id"],
            "status": "captured", "reason": "task_plan_manual_observation_requires_review", "read_only": True,
            "authorizes_action": False, "automatic_retry_allowed": False, "packet_sha256": packet["packet_sha256"],
            "frame": observed, "record_ref": record_ref, "manual_observation_budget": budget}
        entries["requests"][request["observation_request_id"]] = {"request": request, "request_sha256": digest(request),
            "status": "captured", "result": outcome, "record_ref": record_ref, "capture_budget": budget}
        entries["revisions"].append({"record_ref": record_ref, "packet_ref": packet_ref, "previous_packet_ref": previous_ref})
        previous = packet
        outcomes.append(outcome)
    state = {key: deepcopy(base[key]) for key in
        ("run_id", "plan_id", "plan_sha256", "owner_id", "session_directory", "target_identity")}
    state.update(review_packet=previous, manual_observation=outcomes[-1],
        verification_results={"original": {"execution_request_id": "execution-one", "review_packet": base}},
        manual_observations={"execution-one": entries})
    return state, outcomes


PROBE = """
import json, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
attempts = []
roots = {'pywinauto', 'comtypes', 'pythoncom', 'win32com', 'uiautomation'}
class Guard:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in roots:
            attempts.append(fullname)
            raise ImportError('unexpected_native_import: ' + fullname)
sys.meta_path.insert(0, Guard())
from app.execution.task_plan_observation_delivery import manual_observation_image
root = Path(sys.argv[1])
state = json.loads((root / 'state.json').read_text(encoding='utf-8'))
def read():
    try:
        data, frame = manual_observation_image(root, state)
        from hashlib import sha256
        return {'sha256': sha256(data).hexdigest(), 'capture_id': frame['capture_id']}
    except (OSError, ValueError) as error:
        return {'error': str(error)}
with ThreadPoolExecutor(max_workers=1) as pool:
    result = pool.submit(read).result()
print(json.dumps({'result': result, 'attempts': attempts,
    'native_loaded': [name for name in sys.modules if name.split('.')[0] in roots]}))
"""


@pytest.mark.parametrize("case", ["current", "ancestor", "record_hash", "outside", "binding", "image_hash"])
def test_real_v3_evidence_delivery_never_imports_native_modules(tmp_path, case):
    root = (tmp_path / "session").resolve()
    state, outcomes = evidence_scene(root)
    expected = outcomes[-1]
    if case == "ancestor":
        state["manual_observation"] = expected = outcomes[0]
    elif case == "record_hash":
        (root / "records" / "packet-1.json").write_bytes(b"changed")
    elif case == "outside":
        state["manual_observations"]["execution-one"]["revisions"][0]["packet_ref"]["path"] = "../outside.json"
        (tmp_path / "outside.json").write_text("{}", encoding="utf-8")
    elif case == "binding":
        state["manual_observation"] = {**outcomes[-1], "packet_sha256": "c" * 64}
    elif case == "image_hash":
        Path(outcomes[-1]["frame"]["image_path"]).write_bytes(b"changed")
    (root / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    child = subprocess.run([sys.executable, "-B", "-X", "utf8", "-c", PROBE, str(root)],
        cwd=Path(__file__).resolve().parents[1], env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert child.returncode == 0, child.stderr
    assert child.stderr == ""
    result = json.loads(child.stdout)
    assert result["attempts"] == [], result
    assert result["native_loaded"] == []
    if case in {"current", "ancestor"}:
        assert result["result"] == {"sha256": expected["frame"]["sha256"], "capture_id": expected["frame"]["capture_id"]}
    else:
        assert result["result"] == {"error": {
            "record_hash": "task_plan_manual_artifact_changed",
            "outside": "task_plan_observation_evidence_outside_session",
            "binding": "task_plan_observation_delivery_binding_invalid",
            "image_hash": "task_plan_manual_revision_binding_invalid",
        }[case]}
