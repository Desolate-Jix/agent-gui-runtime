"""模板接线的离线资格、旧摘要和原输入认证回归。"""
from copy import deepcopy
from hashlib import sha256
import json
import sqlite3

import pytest

from app.judgment.condition_templates import make_record_id_template, resolve_condition_binding
from app.judgment.evidence import prepare_request
from app.judgment.profile import DecisionProfile
from app.judgment.service import DecisionService, decision_profile_sha256
from test_decision_service import frame


def concrete(record_id="RID-17", **template_changes):
    template = make_record_id_template(allowed_states=["Record details page"], **template_changes)
    return resolve_condition_binding({"schema": "condition_binding.v1", "template": template,
        "typed_parameters": {"record_id": {"source": "input", "name": "record_id"}}}, {"record_id": record_id})


def identity(snapshot):
    return {key: snapshot[key] for key in ("condition_template_id", "revision", "template_sha256")}


def context(snapshot):
    return {"goal": "Open record", "step_goal": "Open details", "remaining_plan": [],
            "allowed_states": deepcopy(snapshot["allowed_states"]), "review_policy": snapshot["review_policy"],
            "source_id": "plan-1", "source_sha256": "b" * 64}


def arguments(root, snapshot=None, **changes):
    snapshot = concrete() if snapshot is None else snapshot
    return {"request_id": "judge-1", "execution_request_id": "execute-1", "condition": snapshot["condition"],
            "frames": [frame(root)], "review_context": context(snapshot), "condition_snapshot": snapshot, **changes}


class FakeProvider:
    ready = True

    def __init__(self, on_judge=None):
        self.calls = []
        self.on_judge = on_judge

    def judge(self, payload):
        self.calls.append(deepcopy(payload))
        if self.on_judge:
            self.on_judge()
        names = payload.get("enabled_predicates", ["condition_met", "visible_error"])
        return {"request_sha256": payload["request_sha256"],
                "predicates": {name: {"type": "predicate", "probability": 0.98 if name == "condition_met" else 0.01}
                               for name in names},
                "usage": {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15},
                "http_elapsed_ms": 0, "server_processing_ms": None, "provider_request_id": "fake-template-1"}


def service(root, snapshot=None, *, approved=True, mode="auto", provider=None, **profile_changes):
    snapshot = concrete() if snapshot is None else snapshot
    profile = DecisionProfile.model_validate({"contract_version": "decision_profile.v2", "mode": mode,
        "auto_condition_templates": [identity(snapshot)] if approved else [], **profile_changes})
    provider = FakeProvider() if provider is None else provider
    return DecisionService(root, profile=profile, provider=provider), provider


@pytest.mark.parametrize("version,profile_hash,request_hash", [
    ("decision_profile.v1", "06c24c243cd24854df590806b1d72f521520e9d28ff411737708fe114a360c8e",
     "8d2c0a1ff4ac4bd567dfe04ff59dc5949d3aaa3498d4797bbe2c82a9a5144227"),
    ("decision_profile.v2", "ed879ce17daaf1141ec4b12502bd6866373b0d2a318879a6dff985f97ee9312d",
     "63096b69bd160d7f124d971210370cdb359d2c50b86cf2f819ee952a031d39bc"),
])
def test_no_template_profile_and_request_keep_fixed_legacy_hashes(monkeypatch, version, profile_hash, request_hash):
    profile = DecisionProfile.model_validate({"contract_version": version, "mode": "auto",
        "api_key_env": "TEMPLATE_SERVICE_TEST_KEY", "auto_conditions": ["Record details are visible."]})
    expected_profile = {"contract_version": version, "mode": "auto", "api_key_env": "TEMPLATE_SERVICE_TEST_KEY",
        "timeout_seconds": 8.0, "pass_threshold": 0.9, "fail_threshold": 0.1, "request_cap": 20,
        "auto_conditions": ["Record details are visible."]}
    bound = {"request_id": "judge-fixed", "execution_request_id": "execute-fixed", "condition": "Record details are visible.",
        "frames": [{"capture_id": "capture-fixed", "sha256": "a" * 64, "image_path": "C:/fixed/capture.png",
                    "window_identity": {"handle": 123, "process_id": 456, "process_create_time": 1000.25}, "role": "after"}],
        "mode": "execution", "phase": "after_action", "run_id": None, "step_id": None, "action": None}
    if version == "decision_profile.v2":
        expected_profile.update(proactive_review=True, review_policy="adaptive")
        bound["review_context"] = {"goal": "Open record", "step_goal": "Open details", "remaining_plan": [],
                                   "allowed_states": ["Record details page"]}
    assert profile.model_dump(mode="json") == expected_profile
    assert decision_profile_sha256(profile) == profile_hash
    monkeypatch.setattr("app.judgment.service.prepare_request", lambda *args, **kwargs: (deepcopy(bound), []))
    runtime = DecisionService(".", profile=profile)
    assert runtime._prepare({})[2] == request_hash
    assert runtime._prepare({"condition_snapshot": None})[2] == request_hash


def test_explicit_empty_v2_allowlist_preserves_legacy_profile_serialization():
    profile = DecisionProfile.model_validate({"contract_version": "decision_profile.v2", "auto_condition_templates": []})
    legacy = DecisionProfile.model_validate({"contract_version": "decision_profile.v2"})
    assert profile.auto_condition_templates == ()
    assert profile.model_dump_json() == legacy.model_dump_json()
    assert "auto_condition_templates" not in profile.model_dump()
    assert decision_profile_sha256(profile) == decision_profile_sha256(legacy)


@pytest.mark.parametrize("templates", [[], [identity(concrete())]])
def test_v1_rejects_explicit_template_allowlist_even_when_empty(templates):
    with pytest.raises(ValueError):
        DecisionProfile.model_validate({"contract_version": "decision_profile.v1", "auto_condition_templates": templates})


@pytest.mark.parametrize("change", [
    {"revision": True}, {"revision": 0}, {"revision": "1"},
    {"condition_template_id": "bad/id"}, {"condition_template_id": 1},
    {"template_sha256": "A" * 64}, {"template_sha256": "f" * 63}, {"extra": True},
])
def test_profile_template_identity_is_strict(change):
    value = {**identity(concrete()), **change}
    with pytest.raises(ValueError):
        DecisionProfile.model_validate({"contract_version": "decision_profile.v2", "auto_condition_templates": [value]})


@pytest.mark.parametrize("templates", [None, {}, "template", [identity(concrete())] * 101,
    [identity(concrete())] * 2,
    [identity(concrete()), {**identity(concrete()), "template_sha256": "f" * 64}]])
def test_profile_rejects_bad_allowlist_shape_and_revision_collisions(templates):
    with pytest.raises(ValueError):
        DecisionProfile.model_validate({"contract_version": "decision_profile.v2", "auto_condition_templates": templates})


def test_profile_keeps_different_explicit_revisions_and_freezes_identity():
    first, second = concrete(), concrete(revision=2)
    profile = DecisionProfile.model_validate({"contract_version": "decision_profile.v2",
        "auto_condition_templates": [identity(first), identity(second)]})
    assert type(profile.auto_condition_templates) is tuple
    assert [item.revision for item in profile.auto_condition_templates] == [1, 2]
    with pytest.raises(ValueError):
        profile.auto_condition_templates[0].revision = 3


@pytest.mark.parametrize("version", ["decision_profile.v1", "decision_profile.v2"])
def test_none_snapshot_is_absent_from_real_evidence_binding_and_digest(tmp_path, version):
    args = arguments(tmp_path)
    del args["condition_snapshot"]
    runtime = DecisionService(tmp_path, profile=DecisionProfile.model_validate({"contract_version": version}))
    plain = runtime._prepare(args)
    explicit = runtime._prepare({**args, "condition_snapshot": None})
    assert plain == explicit
    assert "condition_snapshot" not in plain[0]


def test_prepare_request_freezes_full_snapshot_without_changing_provider_frames(tmp_path):
    args = arguments(tmp_path)
    original = deepcopy(args)
    bound, uploads = prepare_request(tmp_path, **args)
    assert bound["condition_snapshot"] == original["condition_snapshot"]
    args["condition_snapshot"]["binding"]["template"]["allowed_states"].append("Changed")
    assert bound["condition_snapshot"] == original["condition_snapshot"]
    assert len(uploads) == 1 and "condition_snapshot" not in uploads[0]


@pytest.mark.parametrize("violation", ["condition", "states", "missing_context", "weaker_policy", "tampered_snapshot"])
def test_invalid_snapshot_or_context_is_rejected_before_any_call(tmp_path, violation):
    snapshot = concrete(review_policy="always_main" if violation == "weaker_policy" else "adaptive")
    runtime, provider = service(tmp_path, snapshot)
    args = arguments(tmp_path, snapshot)
    if violation == "condition":
        args["condition"] = "An unrelated result passes."
    elif violation == "states":
        args["review_context"]["allowed_states"] = ["Any page"]
    elif violation == "missing_context":
        args["review_context"] = None
    elif violation == "weaker_policy":
        args["review_context"]["review_policy"] = "adaptive"
    else:
        args["condition_snapshot"]["condition"] = "An unrelated result passes."
    result = runtime.evaluate(**args)
    assert result["status"] == "rejected" and not result["adopted"]
    assert provider.calls == []
    with pytest.raises(ValueError):
        prepare_request(tmp_path, **args)


def test_v1_rejects_template_request_without_dispatch(tmp_path):
    provider = FakeProvider()
    runtime = DecisionService(tmp_path, profile=DecisionProfile(mode="auto"), provider=provider)
    result = runtime.evaluate(**arguments(tmp_path))
    assert result["status"] == "rejected" and provider.calls == []


@pytest.mark.parametrize("policy_source", ["template", "context", "profile"])
def test_always_main_from_any_authorized_source_is_authenticated_zero_call(tmp_path, policy_source):
    snapshot = concrete(review_policy="always_main" if policy_source == "template" else "adaptive")
    runtime, provider = service(tmp_path, snapshot, review_policy="always_main" if policy_source == "profile" else "adaptive")
    args = arguments(tmp_path, snapshot)
    if policy_source == "context":
        args["review_context"]["review_policy"] = "always_main"
    result = runtime.evaluate(**args)
    assert result["status"] == "skipped" and result["reason"] == "decision_always_main"
    assert runtime.validate_result(result, **args) and runtime.status()["used"] == 0
    assert provider.calls == []


@pytest.mark.parametrize("allowlisted_text", [False, True])
def test_unknown_auto_template_is_durable_zero_call_without_text_fallback(tmp_path, allowlisted_text):
    snapshot = concrete()
    runtime, provider = service(tmp_path, snapshot, approved=False,
        auto_conditions=[snapshot["condition"]] if allowlisted_text else [])
    args = arguments(tmp_path, snapshot)
    result = runtime.evaluate(**args)
    assert result["status"] == "skipped" and result["reason"] == "decision_condition_template_not_allowlisted"
    assert result["review_scope"] == "effect" and not result["adopted"]
    assert runtime.validate_result(result, **args) and runtime.status()["used"] == 0
    with sqlite3.connect(tmp_path / "judgments" / "decisions.sqlite3") as db:
        assert db.execute("SELECT dispatched FROM dispatches").fetchone() == (0,)
    reopened, other_provider = service(tmp_path, snapshot, approved=False,
        auto_conditions=[snapshot["condition"]] if allowlisted_text else [])
    assert reopened.evaluate(**args) == result
    assert provider.calls == other_provider.calls == []


@pytest.mark.parametrize("field,value", [("condition_template_id", "other_template"), ("revision", 2), ("template_sha256", "f" * 64)])
def test_auto_allowlist_matches_all_identity_fields(tmp_path, field, value):
    snapshot = concrete()
    runtime, provider = service(tmp_path, snapshot,
        auto_condition_templates=[{**identity(snapshot), field: value}])
    assert not runtime.auto_condition_allowed(snapshot["condition"], condition_snapshot=snapshot)
    assert runtime.evaluate(**arguments(tmp_path, snapshot))["status"] == "skipped"
    assert provider.calls == []


def test_approved_auto_template_adopts_and_preserves_provider_protocol(tmp_path):
    snapshot = concrete()
    runtime, provider = service(tmp_path, snapshot)
    args = arguments(tmp_path, snapshot)
    result = runtime.evaluate(**args)
    assert result["status"] == "completed" and result["verdict"] == "success"
    assert result["adopted"] and result["disposition"] == "continue"
    assert runtime.auto_condition_allowed(snapshot["condition"], condition_snapshot=snapshot)
    assert runtime.validate_result(result, **args)
    assert result["condition_snapshot"] == snapshot and not result["authorizes_action"]
    assert len(provider.calls) == 1
    assert set(provider.calls[0]) == {"condition", "phase", "frames", "action", "request_sha256",
                                     "schema_version", "enabled_predicates", "review_context"}
    assert provider.calls[0]["condition"] == snapshot["condition"]
    assert provider.calls[0]["request_sha256"] == result["request_sha256"]


@pytest.mark.parametrize("approved", [True, False])
def test_shadow_template_never_adopts_even_with_low_review_score(tmp_path, approved):
    runtime, provider = service(tmp_path, approved=approved, mode="shadow")
    args = arguments(tmp_path)
    result = runtime.evaluate(**args)
    assert result["verdict"] == "success" and result["suggested_disposition"] == "continue"
    assert result["disposition"] == "review_required" and not result["adopted"]
    assert runtime.validate_result(result, **args) and len(provider.calls) == 1


def test_template_authentication_requires_explicit_expected_original_snapshot(tmp_path):
    runtime, _ = service(tmp_path)
    args = arguments(tmp_path)
    result = runtime.evaluate(**args)
    assert runtime.validate_result(result, **args)
    assert runtime.validate_result(result) is False
    without = {key: value for key, value in args.items() if key != "condition_snapshot"}
    assert runtime.validate_result(result, **without) is False
    assert runtime.validate_result(result, **{**args, "condition_snapshot": None}) is False


def test_changed_run_input_cannot_authenticate_or_reuse_original_dispatch(tmp_path):
    runtime, provider = service(tmp_path)
    original = arguments(tmp_path)
    result = runtime.evaluate(**original)
    replacement = concrete("RID-18")
    changed = {**original, "condition": replacement["condition"], "condition_snapshot": replacement}
    assert not runtime.validate_result(result, **changed)
    assert runtime.evaluate(**changed)["status"] == "conflict"
    forged = {**result, "condition": replacement["condition"], "condition_snapshot": replacement}
    assert not runtime.validate_result(forged, **original)
    assert len(provider.calls) == 1


def test_original_snapshot_is_frozen_through_provider_mutation_and_reopen(tmp_path):
    args = arguments(tmp_path)
    before = deepcopy(args)
    provider = FakeProvider(on_judge=lambda: args["condition_snapshot"]["typed_parameters"].update(record_id="changed"))
    runtime, _ = service(tmp_path, provider=provider)
    result = runtime.evaluate(**args)
    assert result["condition_snapshot"] == before["condition_snapshot"]
    assert runtime.validate_result(result, **before)
    assert not runtime.validate_result(result, **args)
    reopened, new_provider = service(tmp_path)
    assert reopened.evaluate(**before) == result
    assert reopened.validate_result(result, **before) and new_provider.calls == []


def test_changed_profile_identity_cannot_authenticate_previous_adoption(tmp_path):
    runtime, _ = service(tmp_path)
    args = arguments(tmp_path)
    result = runtime.evaluate(**args)
    changed, provider = service(tmp_path, approved=False)
    assert not changed.validate_result(result, **args)
    assert changed.evaluate(**args)["status"] == "conflict" and provider.calls == []


def test_explicit_none_snapshot_keeps_legacy_result_authentication(tmp_path):
    provider = FakeProvider()
    runtime = DecisionService(tmp_path, profile=DecisionProfile.model_validate({"contract_version": "decision_profile.v2",
        "mode": "auto", "auto_conditions": ["Record details are visible."]}), provider=provider)
    args = arguments(tmp_path, condition="Record details are visible.")
    del args["condition_snapshot"]
    result = runtime.evaluate(**args, condition_snapshot=None)
    assert result["adopted"] and "condition_snapshot" not in result
    assert runtime.validate_result(result) and runtime.validate_result(result, **args, condition_snapshot=None)
    assert runtime.evaluate(**args) == result and len(provider.calls) == 1
