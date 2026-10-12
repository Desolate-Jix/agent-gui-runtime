"""从固定程序和原启动来源重建模板，不信任可变运行快照自证。"""
from hashlib import sha256
from pathlib import Path

from app.core.json_snapshot import read_json_snapshot
from app.desktop_review.external_mapping import canonical_json_bytes
from app.judgment.condition_templates import resolve_condition_binding


def step_condition_snapshot(step, inputs=None):
    binding = step.get("verification", {}).get("condition_binding")
    return None if binding is None else resolve_condition_binding(binding, {} if inputs is None else inputs)


def program_condition_snapshots(program, inputs):
    return {step["step_id"]: step_condition_snapshot(step, inputs)
        for step in program["definition"]["steps"] if "condition_binding" in step.get("verification", {})}


def validate_template_revisions(definition, baseline=None):
    identities = {}
    for source in ([baseline] if baseline is not None else []) + [definition]:
        for step in source["steps"]:
            binding = step.get("verification", {}).get("condition_binding")
            if binding is None:
                continue
            template = binding["template"]
            key = (template["condition_template_id"], template["revision"])
            if key in identities and identities[key] != template["template_sha256"]:
                raise ValueError("workflow_condition_template_revision_conflict")
            identities[key] = template["template_sha256"]


def validate_frozen_conditions(state, program, session, *, read=None):
    expected = program_condition_snapshots(program, state["inputs"])
    if not expected and "condition_snapshots" not in state:
        return
    if not expected or state.get("condition_snapshots") != expected:
        raise ValueError("workflow_condition_snapshots_mismatch")
    session = Path(session).resolve()
    read = read or read_json_snapshot
    marker = state.get("recovery_import")
    if marker is not None:
        from .workflow_recovery_import import _claim_path
        claim = read(_claim_path(session, marker["claim_id"]))
        original = claim.get("prepared", {}).get("trial_state", {})
        if (claim.get("new_run_id") != state["run_id"] or claim.get("recovery_import") != marker
                or claim.get("trial_state_sha256") != sha256(canonical_json_bytes(original)).hexdigest()
                or any(state.get(key) != original.get(key) for key in
                    ("workflow_id", "program_id", "start_step_id", "inputs", "condition_snapshots"))):
            raise ValueError("workflow_condition_recovery_binding_changed")
        return
    values = [state["workflow_id"], state["program_id"], state["start_step_id"], state["inputs"]]
    strategy = state.get("execution_strategy", "learned")
    if strategy != "learned":
        values.append(strategy)
    request_hash = sha256(canonical_json_bytes(values)).hexdigest()
    index = read(session / "workflow-trials" / "requests.json")
    matches = [(key, item) for key, item in index.items() if item.get("run_id") == state["run_id"]]
    if (len(matches) != 1 or matches[0][1].get("request_sha256") != request_hash
            or state["run_id"] != "trial-" + sha256(canonical_json_bytes(
                [str(session), matches[0][0], request_hash])).hexdigest()):
        raise ValueError("workflow_condition_original_inputs_changed")


__all__ = ["step_condition_snapshot", "program_condition_snapshots", "validate_template_revisions",
           "validate_frozen_conditions"]
