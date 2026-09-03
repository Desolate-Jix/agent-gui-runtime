"""冻结五屏 GoalBinding 实验的薄 CLI；默认只读，不取得执行授权。"""
from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

INCUMBENT = "goal_binding_qwen_incumbent"
STAGE1 = ("goal_binding_ui_venus_1_5_2b_f16", "goal_binding_gui_actor_3b_bf16", "goal_binding_phi_ground_any_bf16")
STAGE2 = ("goal_binding_ui_venus_2_9b_q6_k", "goal_binding_groundnext_7b_q6_k")
FALLBACK = "goal_binding_ui_venus_1_5_8b_q6_k"
ARMS = (INCUMBENT, *STAGE1, *STAGE2, FALLBACK)
CAP = 32_212_254_720
DEFAULT_CONFIG = ROOT / "configs/benchmarks/goal_binding_provider_ab_v1.json"


def _arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--mode", choices=("preflight", "snapshot", "arm", "matrix", "score", "cleanup"), default="preflight")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--artifact-root", type=Path, default=ROOT / ".artifacts/goal-binding-ab")
    parser.add_argument("--storage-root", type=Path, default=Path("E:/\u6a21\u578b\u6d4b\u8bd5"))
    parser.add_argument("--arm-id", choices=ARMS)
    parser.add_argument("--operator-approved-model-start", action="store_true")
    return parser.parse_args(argv)


def _path(path):
    from app.learn.hybrid.omni_snapshot import _safe_ancestors
    absolute = Path(path).absolute()
    if any("holdout" in part.casefold() for part in absolute.parts):
        raise ValueError("holdout paths are forbidden")
    _safe_ancestors(absolute, label="experiment path")
    resolved = absolute.resolve()
    if any("holdout" in part.casefold() for part in resolved.parts):
        raise ValueError("resolved holdout paths are forbidden")
    return resolved


def _read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    def constant(value):
        raise ValueError("non-finite JSON")
    return json.loads(_path(path).read_text(encoding="utf-8"), object_pairs_hook=pairs, parse_constant=constant)


def _config(path):
    from scripts.run_simple_native_provider_smoke import _config as original_config
    baseline = original_config(ROOT / "configs/benchmarks/simple_native_provider_smoke_v1.json")
    value = _read(path)
    expected_matrix = {"incumbent": INCUMBENT, "stage1": list(STAGE1), "stage2": list(STAGE2), "stage2_fallback": FALLBACK, "stage2_condition": "no_stage1_hard_gate_passer", "fallback_condition": "ui_venus_2_runtime_incompatible"}
    if not isinstance(value, dict) or set(value) != set(baseline) | {"matrix", "omni_identity", "storage_max_bytes"}:
        raise ValueError("experiment configuration is not closed")
    if value["contract_version"] != "goal_binding_provider_ab_v1" or value["matrix"] != expected_matrix or value["storage_max_bytes"] != CAP:
        raise ValueError("frozen experiment stage order or quota differs")
    for key in baseline.keys() - {"contract_version"}:
        if value[key] != baseline[key]:
            raise ValueError(f"frozen experiment {key} differs")
    expected_identity = {"provider_id": "local.runtime/omniparser", "profile_id": baseline["provider"]["profile_ids"]["omni"], "model_revision": "v2.0.1", "preprocessing_revision": "omni_native_v1"}
    if value["omni_identity"] != expected_identity:
        raise ValueError("frozen Omni identity differs")
    for screen in value["screens"]:
        _path(ROOT / screen["path"])
    _path(ROOT / value["provider"]["provider_corpus_path"])
    return value


def _storage(root):
    from app.learn.hybrid.model_test_storage import _require_model_test_root, inventory_storage
    _require_model_test_root(root)
    result = inventory_storage(root)
    if result["max_bytes"] != CAP or result["logical_bytes"] > CAP or result["within_cap"] is not True:
        raise ValueError("storage exceeds the exact 30 GiB cap")
    return result


def _profile(arm_id):
    from app.learn.hybrid.goal_binding_model_callers import load_goal_binding_profile
    if arm_id not in ARMS:
        raise ValueError("unknown frozen arm")
    result = load_goal_binding_profile(_path(ROOT / "configs/model_profiles" / f"{arm_id}.json"))
    if result["arm_id"] != arm_id:
        raise ValueError("profile arm identity differs")
    return result


def _available(profile, storage_root):
    from app.learn.hybrid.goal_binding_model_callers import _verified
    return _verified(profile, storage_root)


def _preflight(config, storage_root):
    from scripts.run_simple_native_provider_smoke import preflight, _cases
    preflight(config)
    cases = _cases(config)
    inventory = _storage(storage_root)
    profiles = []
    for arm_id in ARMS:
        profile = _profile(arm_id)
        status, reason = "verified", None
        if profile["artifact_manifest"]["status"] != "verified":
            status, reason = "not_acquired", "acquisition/profile projection required"
        else:
            try:
                _available(profile, storage_root)
            except (OSError, ValueError, RuntimeError) as error:
                status, reason = "blocked", str(error)
        profiles.append({"arm_id": arm_id, "status": status, "reason": reason})
    return {"mode": "preflight", "screen_count": len(cases), "target_count": sum(len(case.goals) for case in cases), "model_callers_constructed": False, "profiles_ready": all(p["status"] == "verified" for p in profiles[:4]), "preflight_scope": "config_storage_profile_only", "runtime_resource_check": "performed_by_session_before_start", "profiles": profiles, "storage": inventory, "holdout_accessed": False, "artifact_is_authorization": False}


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _write(path, value, *, replace=False):
    path = _path(path)
    data = _bytes(value)
    if path.exists() and not replace:
        if path.read_bytes() != data:
            raise ValueError(f"immutable experiment evidence already exists: {path.name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".writing")
    with temporary.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _ref(path, root):
    path = _path(path)
    if not path.is_relative_to(root):
        raise ValueError("evidence escaped the run root")
    return {"path": path.relative_to(root).as_posix(), "sha256": sha256(path.read_bytes()).hexdigest()}


def _evidence(ref, root):
    if not isinstance(ref, dict) or set(ref) != {"path", "sha256"} or Path(ref["path"]).is_absolute():
        raise ValueError("invalid run evidence reference")
    path = _path(root / ref["path"])
    if not path.is_relative_to(root) or _ref(path, root) != ref:
        raise ValueError("run evidence hash or path changed")
    return path


def _journal(root, config, storage_root, *, create):
    path = root / "stage-journal.json"
    expected = {"contract_version": "goal_binding_stage_journal_v1", "config_sha256": sha256(_bytes(config)).hexdigest(), "storage_root": str(storage_root), "holdout_accessed": False, "artifact_is_authorization": False}
    if path.exists():
        value = _read(path)
        if not isinstance(value, dict) or set(value) != set(expected) | {"snapshot", "arms", "events"} or any(value.get(k) != v for k, v in expected.items()):
            raise ValueError("stage journal experiment identity differs")
        return value
    if not create:
        raise ValueError("stage journal is missing")
    if root.exists() and any(root.iterdir()):
        raise ValueError("run root is not empty and has no stage journal")
    value = expected | {"snapshot": None, "arms": {}, "events": []}
    _write(path, value)
    return value


def _event(root, journal, phase, state, **evidence):
    journal["events"].append({"sequence": len(journal["events"]) + 1, "phase": phase, "state": state, **evidence})
    _write(root / "stage-journal.json", journal, replace=True)


def _clean(receipt):
    from app.learn.hybrid.goal_binding_model_callers import cleanup_receipt_is_clean
    if not cleanup_receipt_is_clean(receipt):
        raise RuntimeError("provider cleanup is unverified; next phase blocked")


def _slots(factory, config, directory):
    if factory is None:
        from app.learn.hybrid.simple_native_callers import make_actual_simple_native_slots
        factory = make_actual_simple_native_slots
    return factory(config={"provider": deepcopy(config["provider"]), "limits": deepcopy(config["limits"])}, artifact_dir=directory)


def _release(slots, providers):
    errors = []
    for provider in providers:
        try:
            receipt = slots.release_provider(provider)
            if receipt.get("provider") != provider:
                raise RuntimeError("slot cleanup provider identity differs")
            _clean(receipt)
        except (OSError, RuntimeError, ValueError, TypeError) as error:
            errors.append(str(error))
    result = slots.cleanup()
    if errors or not isinstance(result, dict) or result.get("contract_version") != "simple_native_actual_session_cleanup_v1" or result.get("verified") is not True:
        raise RuntimeError("managed slots cleanup is unverified: " + "; ".join(errors))
    receipts = result.get("provider_receipts")
    if not isinstance(receipts, list) or [r.get("provider") for r in receipts] != ["omni", "qwen", "vista"]:
        raise RuntimeError("managed slot cleanup evidence is incomplete")
    for receipt in receipts:
        _clean(receipt)
    return result


def _snapshot(root, config, cases, journal, storage_root, slots_factory):
    from app.learn.hybrid.omni_snapshot import create_omni_snapshot
    if journal["snapshot"] is not None or (root / "omni-snapshot-v1").exists():
        raise ValueError("snapshot already exists; use its frozen identity instead of rerunning Omni")
    _storage(storage_root)
    _event(root, journal, "snapshot", "started")
    slots = _slots(slots_factory, config, root / "snapshot-lifecycle")
    try:
        try:
            manifest = create_omni_snapshot(cases=cases, omni=slots.omni, output_dir=root / "omni-snapshot-v1", provider_identity=config["omni_identity"])
        finally:
            receipt = _release(slots, ("omni", "qwen", "vista"))
            _write(root / "snapshot-cleanup.json", receipt)
        from app.learn.hybrid.omni_snapshot import load_verified_omni_snapshot
        verified = load_verified_omni_snapshot(manifest, expected_cases=cases, expected_provider_identity=config["omni_identity"])
        journal["snapshot"] = {"manifest": _ref(manifest, root), "cleanup": _ref(root / "snapshot-cleanup.json", root), "sha256": verified["snapshot_sha256"]}
        _event(root, journal, "snapshot", "finalized", snapshot_sha256=verified["snapshot_sha256"])
    except BaseException as error:
        _event(root, journal, "snapshot", "blocked", error=str(error))
        raise


def _verified_snapshot(root, config, cases, journal):
    from app.learn.hybrid.omni_snapshot import load_verified_omni_snapshot
    item = journal["snapshot"]
    if not isinstance(item, dict):
        raise ValueError("one finalized Omni snapshot is required")
    manifest = _evidence(item["manifest"], root)
    cleanup = _read(_evidence(item["cleanup"], root))
    if cleanup.get("verified") is not True:
        raise ValueError("snapshot cleanup is not verified")
    for receipt in cleanup["provider_receipts"]:
        _clean(receipt)
    snapshot = load_verified_omni_snapshot(manifest, expected_cases=cases, expected_provider_identity=config["omni_identity"])
    if snapshot["snapshot_sha256"] != item["sha256"]:
        raise ValueError("frozen snapshot SHA changed")
    return manifest


def _score_report(artifact, config):
    from app.learn.hybrid.goal_binding_ab_score import score_goal_binding_arm
    return score_goal_binding_arm(provider_artifact=artifact, gold_path=_path(ROOT / config["scorer_gold_path"]))


def _arm_evidence(arm_id, root, journal):
    item = journal["arms"].get(arm_id)
    if not isinstance(item, dict) or item.get("status") != "finalized":
        raise ValueError(f"arm has no finalized report: {arm_id}")
    artifact = _evidence(item["artifact"], root)
    pipeline = _read(_evidence(item["pipeline_cleanup"], root))
    if pipeline.get("verified") is not True:
        raise RuntimeError("VISTA cleanup is unverified")
    for receipt in pipeline["provider_receipts"]:
        _clean(receipt)
    from app.learn.hybrid.goal_binding_ab_score import _load_artifact
    raw, _ = _load_artifact(artifact)
    _clean(raw["cleanup_receipt"])
    if raw["arm_id"] != arm_id or raw["omni_snapshot_ref"]["sha256"] != journal["snapshot"]["sha256"]:
        raise ValueError("arm evidence does not consume the frozen snapshot")
    return artifact


def _arm_report(arm_id, root, config, journal):
    artifact = _arm_evidence(arm_id, root, journal)
    report = _score_report(artifact, config)
    if report["arm_id"] != arm_id or report["omni_snapshot_ref"]["sha256"] != journal["snapshot"]["sha256"]:
        raise ValueError("arm report does not consume the frozen snapshot")
    _clean(report["cleanup_receipt"])
    _write(root / "arms" / arm_id / "binder-report.json", report)
    return report


def _passer(reports):
    from app.learn.hybrid.goal_binding_ab_score import evaluate_binding_hard_gate
    return any(evaluate_binding_hard_gate(binder_report=r, cleanup_receipt=r["cleanup_receipt"])["passed"] for r in reports)


def _order(arm_id, root, config, journal):
    predecessors = [INCUMBENT, *STAGE1, *STAGE2, FALLBACK]
    for previous in predecessors[:predecessors.index(arm_id)]:
        _arm_report(previous, root, config, journal)
    if arm_id in (*STAGE2, FALLBACK) and _passer([_arm_report(a, root, config, journal) for a in STAGE1]):
        raise ValueError("Stage 2 is forbidden after a Stage 1 hard-gate passer")
    if arm_id == FALLBACK and not _runtime_incompatible(root, journal):
        raise ValueError("Venus 1.5-8B requires exact Venus 2 runtime incompatibility evidence")


def _runtime_incompatible(root, journal):
    item = journal["arms"].get(STAGE2[0], {})
    if "probe" not in item:
        return False
    probe = _read(_evidence(item["probe"], root))
    _clean(probe["cleanup"])
    raw = probe["raw_native_output"]
    return isinstance(raw, dict) and raw.get("contract_version") == "goal_binding_native_trace_v2" and raw.get("outcome") == "provider_failure" and isinstance(raw.get("failure"), dict) and raw["failure"].get("kind") == "provider_platform_incompatible"


def _probe(profile, image, root, storage_root, arm_factory):
    from app.learn.hybrid.goal_binding_ab import _native_envelope
    from app.learn.hybrid.goal_binding_model_callers import native_adapter_for_profile, _adapter_profile
    directory = root / "probes" / profile["arm_id"]
    arm = arm_factory(profile=profile, artifact_dir=storage_root, run_root=directory)
    try:
        raw = arm.call(image, {"goal": "button: Open"})
    finally:
        cleanup = arm.cleanup()
    _clean(cleanup)
    envelope = _native_envelope(raw)
    failure = envelope.get("failure") if envelope else None
    incompatible = isinstance(failure, dict) and failure["kind"] == "provider_platform_incompatible"
    raw_text = envelope["raw_native_output"] if envelope else raw
    proposal = native_adapter_for_profile(profile)(raw_text, goal_index=0, profile=_adapter_profile(profile)) if failure is None else None
    smoke_ok = proposal is not None and proposal.status == "OK"
    result = {"contract_version": "goal_binding_profile_probe_v1", "provider_id": profile["provider_id"], "raw_native_output": raw, "cleanup": cleanup, "schema_smoke_passed": smoke_ok, "runtime_incompatible": incompatible, "contains_holdout": False, "holdout_accessed": False, "candidate_mapping": None, "artifact_is_authorization": False}
    _write(directory / "probe.json", result)
    if not smoke_ok and not incompatible:
        raise RuntimeError("Stage 2 no-Gold schema smoke failed; see persisted probe, not an incompatibility claim")
    return _ref(directory / "probe.json", root)


def _run_arm(arm_id, root, config, cases, journal, storage_root, slots_factory, arm_factory):
    from app.learn.hybrid.goal_binding_ab import run_goal_binding_arm
    manifest = _verified_snapshot(root, config, cases, journal)
    _order(arm_id, root, config, journal)
    if arm_id in journal["arms"] or (root / "arms" / arm_id).exists():
        raise ValueError("arm already attempted; do not overwrite or reload it")
    _storage(storage_root)
    try:
        profile = _available(_profile(arm_id), storage_root)
    except (OSError, ValueError, RuntimeError) as error:
        _event(root, journal, arm_id, "profile_unavailable", error=str(error), inference_attempted=False)
        raise
    if arm_factory is None:
        from app.learn.hybrid.goal_binding_model_callers import make_goal_binding_arm
        arm_factory = make_goal_binding_arm
    journal["arms"][arm_id] = {"status": "started"}
    _event(root, journal, arm_id, "started", snapshot_sha256=journal["snapshot"]["sha256"])
    try:
        probe_ref = None
        if arm_id in (*STAGE2, FALLBACK):
            _event(root, journal, arm_id + "/probe", "started")
            probe_ref = _probe(profile, cases[0].image_path, root, storage_root, arm_factory)
            _event(root, journal, arm_id + "/probe", "finalized", probe=probe_ref)
            _storage(storage_root)
        slots = _slots(slots_factory, config, root / "arms" / arm_id / "vista-lifecycle")
        remaining = ["omni", "qwen", "vista"]
        try:
            for unused in ("omni", "qwen"):
                receipt = slots.release_provider(unused)
                remaining.pop(0)
                _clean(receipt)
            arm = arm_factory(profile=profile, artifact_dir=storage_root, run_root=root)
            if arm.arm_id != arm_id or arm.provider_id != profile["provider_id"]:
                raise ValueError("constructed arm identity differs")
            artifact = run_goal_binding_arm(cases=cases, snapshot_path=manifest, arm=arm, vista=slots.vista, artifact_dir=root / "arms" / arm_id, expected_omni_provider_identity=config["omni_identity"])
        finally:
            receipt = _release(slots, remaining)
            _write(root / "arms" / arm_id / "pipeline-cleanup.json", receipt)
        raw = _read(artifact.path)
        _clean(raw["cleanup_receipt"])
        journal["arms"][arm_id] = {"status": "finalized", "artifact": _ref(artifact.path, root), "pipeline_cleanup": _ref(root / "arms" / arm_id / "pipeline-cleanup.json", root)}
        if probe_ref is not None:
            journal["arms"][arm_id]["probe"] = probe_ref
        _arm_report(arm_id, root, config, journal)
        _event(root, journal, arm_id, "finalized", **journal["arms"][arm_id])
    except BaseException as error:
        journal["arms"][arm_id]["status"] = "blocked"
        _event(root, journal, arm_id, "blocked", error=str(error))
        raise


def _score(root, config, cases, journal):
    from app.learn.hybrid.goal_binding_ab_score import build_goal_binding_matrix
    _verified_snapshot(root, config, cases, journal)
    if any(item.get("status") != "finalized" for item in journal["arms"].values()):
        raise ValueError("unfinished or unverified arm prevents scoring")
    reports = [_arm_report(a, root, config, journal) for a in ARMS if a in journal["arms"]]
    result = build_goal_binding_matrix(arm_reports=reports)
    _write(root / "matrix-report.json", result, replace=True)
    return result


def main(argv=None, *, slots_factory=None, arm_factory=None):
    args = _arguments(argv)
    try:
        if args.mode in {"snapshot", "arm", "matrix"} and not args.operator_approved_model_start:
            raise ValueError(f"{args.mode} requires --operator-approved-model-start")
        if args.mode == "arm" and args.arm_id is None:
            raise ValueError("arm requires --arm-id")
        config = _config(args.config)
        root, storage_root = _path(args.artifact_root), _path(args.storage_root)
        if args.mode == "preflight":
            report = _preflight(config, storage_root)
            print(json.dumps(report, ensure_ascii=False))
            return 0
        from scripts.run_simple_native_provider_smoke import _cases, preflight
        from app.learn.hybrid.model_test_storage import _require_model_test_root
        _require_model_test_root(storage_root)
        preflight(config)
        if args.mode in {"snapshot", "arm", "matrix"}:
            _storage(storage_root)
        cases = _cases(config)
        journal = _journal(root, config, storage_root, create=args.mode in {"snapshot", "matrix"})
        if args.mode == "snapshot":
            _snapshot(root, config, cases, journal, storage_root, slots_factory)
        elif args.mode == "arm":
            _run_arm(args.arm_id, root, config, cases, journal, storage_root, slots_factory, arm_factory)
        elif args.mode == "matrix":
            if journal["snapshot"] is None:
                _snapshot(root, config, cases, journal, storage_root, slots_factory)
            for arm_id in (INCUMBENT, *STAGE1):
                if arm_id not in journal["arms"]:
                    _run_arm(arm_id, root, config, cases, journal, storage_root, slots_factory, arm_factory)
                else:
                    _arm_report(arm_id, root, config, journal)
            if not _passer([_arm_report(a, root, config, journal) for a in STAGE1]):
                for arm_id in STAGE2:
                    if arm_id not in journal["arms"]:
                        _run_arm(arm_id, root, config, cases, journal, storage_root, slots_factory, arm_factory)
                    else:
                        _arm_report(arm_id, root, config, journal)
                if _runtime_incompatible(root, journal) and FALLBACK not in journal["arms"]:
                    _run_arm(FALLBACK, root, config, cases, journal, storage_root, slots_factory, arm_factory)
            _score(root, config, cases, journal)
        elif args.mode == "score":
            _score(root, config, cases, journal)
        else:
            _verified_snapshot(root, config, cases, journal)
            for arm_id in journal["arms"]:
                _arm_evidence(arm_id, root, journal)
            _write(root / "cleanup-receipt.json", {"contract_version": "goal_binding_experiment_cleanup_v1", "verified": True, "operation": "recorded_cleanup_evidence_audit", "live_cleanup_performed": False, "holdout_accessed": False, "snapshot_cleanup": journal["snapshot"]["cleanup"], "arm_evidence": deepcopy(journal["arms"]), "artifact_is_authorization": False}, replace=True)
        print(json.dumps({"mode": args.mode, "artifact_root": str(root), "holdout_accessed": False, "artifact_is_authorization": False}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
