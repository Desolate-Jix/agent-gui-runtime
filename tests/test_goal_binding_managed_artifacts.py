from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def managed_fixture(tmp_path, monkeypatch):
    from app.learn.hybrid import goal_binding_managed_artifacts as managed
    from app.learn.hybrid import model_test_storage as storage
    readonly = tmp_path / "readonly"
    report_root = tmp_path / "reports-store"
    selected = {"model_path": "models/model.gguf", "mmproj_path": "models/mmproj.gguf", "server_path": "tools/llama-server.exe", "port": 13240}
    paths = {}
    for role, relative in (("model", selected["model_path"]), ("mmproj", selected["mmproj_path"]), ("runtime", selected["server_path"]), ("dll", "tools/runtime.dll")):
        path = readonly / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(role.encode())
        paths[role] = path
    expected = {role: {"sha256": sha256(paths[role].read_bytes()).hexdigest(), "bytes": paths[role].stat().st_size} for role in ("model", "mmproj")}
    monkeypatch.setattr(managed, "READONLY_ROOT", readonly)
    monkeypatch.setattr(managed, "EXPECTED_WEIGHTS", expected)
    monkeypatch.setattr(managed, "_selected_profile", lambda: {key: str(readonly / value) if key.endswith("_path") else value for key, value in selected.items()})
    monkeypatch.setattr(storage, "MODEL_TEST_ROOT", report_root)
    template = json.loads((ROOT / "configs/model_profiles/goal_binding_qwen_incumbent.json").read_text(encoding="utf-8"))
    return managed, storage, template, paths, report_root


def test_build_materialize_verify_readonly_incumbent_without_copy(managed_fixture):
    managed, _, template, paths, root = managed_fixture
    before = {role: path.read_bytes() for role, path in paths.items()}
    profile_path = managed.materialize_incumbent_profile(template, root)
    from app.learn.hybrid.goal_binding_model_callers import load_goal_binding_profile, _verified
    profile = load_goal_binding_profile(profile_path)
    assert _verified(profile, root) == profile
    verified = managed.verify_managed_artifacts(profile, root)
    assert verified["model"] == paths["model"].resolve()
    assert verified["runtime"] == paths["runtime"].resolve()
    assert profile["contract_version"] == "goal_binding_model_profile_v1"
    assert all(path.is_relative_to(root / "reports") or path.name == ".goal-binding-quota.lock" for path in root.rglob("*") if path.is_file())
    assert not list(root.rglob("*.gguf")) and not list(root.rglob("*.dll"))
    assert before == {role: path.read_bytes() for role, path in paths.items()}
    assert template["artifact_manifest"]["status"] == "not_acquired"


@pytest.mark.parametrize("role", ["model", "mmproj", "runtime", "dll"])
def test_changed_or_missing_readonly_artifact_is_rejected(managed_fixture, role):
    managed, _, template, paths, root = managed_fixture
    profile_path = managed.materialize_incumbent_profile(template, root)
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    paths[role].write_bytes(b"changed")
    with pytest.raises(ValueError, match="identity|changed"):
        managed.verify_managed_artifacts(profile, root)
    paths[role].unlink()
    with pytest.raises(ValueError, match="unavailable|identity|changed"):
        managed.verify_managed_artifacts(profile, root)


def test_changed_source_code_is_not_resealed_at_startup(managed_fixture, monkeypatch):
    managed, _, template, _, root = managed_fixture
    profile_path = managed.materialize_incumbent_profile(template, root)
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    original = managed._file_identity
    def changed(path):
        result = original(path)
        if path.name == "goal_binding_transformers_worker.py":
            result["sha256"] = "0" * 64
        return result
    monkeypatch.setattr(managed, "_file_identity", changed)
    with pytest.raises(ValueError, match="source.*changed"):
        managed.verify_managed_artifacts(profile, root)


def test_resealed_origin_substitution_is_rejected(managed_fixture):
    managed, _, template, _, root = managed_fixture
    profile_path = managed.materialize_incumbent_profile(template, root)
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    manifest_path = root / profile["artifact_manifest"]["relative_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["origin"] = "reports"
    raw = managed._json_bytes(manifest)
    manifest_path.write_bytes(raw)
    profile["artifact_manifest"]["sha256"] = sha256(raw).hexdigest()
    with pytest.raises(ValueError, match="origin"):
        managed.verify_managed_artifacts(profile, root)


def test_builder_rejects_other_provider_and_storage_over_cap(managed_fixture, monkeypatch):
    managed, storage, template, _, root = managed_fixture
    other = deepcopy(template)
    other["provider_id"] = "gui_actor_3b_bf16"
    with pytest.raises(ValueError, match="incumbent"):
        managed.materialize_incumbent_profile(other, root)
    monkeypatch.setattr(storage, "MODEL_TEST_MAX_BYTES", 1)
    with pytest.raises(ValueError, match="30 GiB"):
        managed.materialize_incumbent_profile(template, root)
    assert not list(root.rglob("*.json"))


def test_materialized_incumbent_factory_worker_runner_finalizes(managed_fixture, monkeypatch, tmp_path):
    from app.learn.hybrid import goal_binding_model_callers as callers
    from app.learn.hybrid.windows_process_scope import windows_process_scope_available
    from app.core import model_server
    from test_goal_binding_ab import _run
    from app.learn.hybrid.goal_binding_ab_score import _verified_cleanup_receipt
    if not windows_process_scope_available():
        pytest.skip("real Windows Job primitives unavailable")
    managed, _, template, _, root = managed_fixture
    generated = managed.materialize_incumbent_profile(template, root)
    profile = callers.load_goal_binding_profile(generated)
    selected = managed._selected_profile()
    boot = tmp_path / "bootstrap"
    boot.mkdir()
    (boot / "sitecustomize.py").write_text(
        "from pathlib import Path\n"
        "from app.learn.hybrid import goal_binding_managed_artifacts as managed\n"
        "from scripts.model_servers import goal_binding_provider_runtimes as runtimes\n"
        f"managed.READONLY_ROOT=Path({str(managed.READONLY_ROOT)!r})\n"
        f"managed.EXPECTED_WEIGHTS={managed.EXPECTED_WEIGHTS!r}\n"
        f"managed._selected_profile=lambda: {selected!r}\n"
        "class FakeManaged:\n"
        "    def __init__(self, profile, artifact_root, session_root, scope_name):\n"
        "        runtimes.verified_artifact_paths(profile, artifact_root)\n"
        "        self.events=session_root/'events.txt'\n"
        "        self.events.write_text('verified-load\\n', encoding='utf-8')\n"
        "    def __call__(self, **kwargs):\n"
        "        with self.events.open('a', encoding='utf-8') as f: f.write('call\\n')\n"
        "        return '[{\"goal_index\":0,\"candidate_index\":0,\"status\":\"BOUND\",\"confidence\":0.9}]'\n"
        "    def close(self):\n"
        "        with self.events.open('a', encoding='utf-8') as f: f.write('close\\n')\n"
        "        return {'status':'released','managed_release':{'lease':{}}}\n"
        "runtimes._ManagedIncumbentSession=FakeManaged\n", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(boot) + ";" + str(ROOT))
    monkeypatch.setattr(callers, "_gpu_ownership_snapshot", lambda: {"status": "verified", "owners": [], "raw": ""})
    monkeypatch.setattr(callers, "_resource_preflight", lambda profile: {"model_launch_allowed": True, "status": "ready"})
    monkeypatch.setattr(model_server, "_validate_exact_qwen_cleanup_evidence", lambda *args: None)
    arm = callers.make_goal_binding_arm(profile=profile, artifact_dir=root, run_root=tmp_path / "run")
    try:
        artifact = _run(tmp_path / "diagnostic", arm=arm)
    finally:
        arm.cleanup()
    document = json.loads(artifact.path.read_text(encoding="utf-8"))
    assert _verified_cleanup_receipt(document["cleanup_receipt"], provider_id=managed.PROVIDER)
    events = list((tmp_path / "run").rglob("events.txt"))
    assert len(events) == 1
    assert events[0].read_text(encoding="utf-8").splitlines() == ["verified-load"] + ["call"] * 25 + ["close"]
    assert artifact.metrics["binder"]["schema_valid"] == 25


def test_added_dll_and_readonly_root_drift_rejected(managed_fixture, monkeypatch, tmp_path):
    managed, _, template, paths, root = managed_fixture
    generated = managed.materialize_incumbent_profile(template, root)
    profile = json.loads(generated.read_text(encoding="utf-8"))
    extra = paths["runtime"].with_name("new.dll")
    extra.write_bytes(b"new")
    with pytest.raises(ValueError, match="DLL identities changed"):
        managed.verify_managed_artifacts(profile, root)
    extra.unlink()
    monkeypatch.setattr(managed, "READONLY_ROOT", tmp_path)
    with pytest.raises(ValueError, match="root.*changed"):
        managed.verify_managed_artifacts(profile, root)


def test_environment_change_and_managed_selected_path_substitution_rejected(managed_fixture, monkeypatch):
    from scripts.model_servers import goal_binding_provider_runtimes as runtimes
    managed, _, template, paths, root = managed_fixture
    generated = managed.materialize_incumbent_profile(template, root)
    profile = json.loads(generated.read_text(encoding="utf-8"))
    selected = managed._selected_profile()
    identities = runtimes._managed_artifact_identity(profile, selected, root)
    assert identities["model"] == sha256(paths["model"].read_bytes()).hexdigest()
    with pytest.raises(runtimes.ProviderIntegrityError, match="selected paths changed"):
        runtimes._managed_artifact_identity(profile, selected | {"model_path": str(paths["mmproj"])}, root)
    original = managed._environment()
    monkeypatch.setattr(managed, "_environment", lambda: original | {"version": "changed"})
    with pytest.raises(ValueError, match="interpreter or dependency"):
        managed.verify_managed_artifacts(profile, root)


def test_production_builder_rejects_nonproduction_write_root_before_creating_it(managed_fixture, tmp_path):
    managed, _, template, _, _ = managed_fixture
    elsewhere = tmp_path / "not-production"
    with pytest.raises(ValueError, match="pinned"):
        managed.materialize_incumbent_profile(template, elsewhere)
    assert not elsewhere.exists()


def test_existing_acquisition_quota_lock_prevents_report_writes(managed_fixture):
    from scripts.fetch_goal_binding_model import _quota_reservation
    managed, _, template, _, root = managed_fixture
    with _quota_reservation(root):
        with pytest.raises(RuntimeError, match="quota reservation"):
            managed.materialize_incumbent_profile(template, root)
        assert not list(root.rglob("*.json"))


def test_exact_managed_launch_callback_reuses_sealed_manifest_root(monkeypatch, tmp_path):
    from app.core import model_server
    from scripts.model_servers import goal_binding_provider_runtimes as runtimes
    seen = []
    selected = {"port": 13240}
    def verify(profile, selected, artifact_root=None):
        seen.append(artifact_root)
        if artifact_root != tmp_path:
            raise ValueError("sealed manifest root missing from launch callback")
        return {}
    def acquire(**kwargs):
        kwargs["profile_validator"](selected)
        return {"server_process_identity": {"pid": 42, "create_time_ns": 99}}
    monkeypatch.setattr(runtimes, "_managed_artifact_identity", verify)
    monkeypatch.setattr(model_server, "profile_for_stage", lambda *args: selected)
    monkeypatch.setattr(model_server, "ensure_and_acquire_scoped_qwen_model_lease", acquire)
    runtimes._ManagedIncumbentSession({"timeout_seconds": 5}, tmp_path, tmp_path, "unused")
    assert seen == [tmp_path, tmp_path]
