from __future__ import annotations

from hashlib import sha1, sha256
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from app.learn.hybrid import model_test_storage as storage
from scripts import fetch_goal_binding_model as fetch


PROFILES = Path(__file__).parents[1] / "configs" / "model_profiles"
STAGE_ONE = [
    "goal_binding_ui_venus_1_5_2b_f16",
    "goal_binding_gui_actor_3b_bf16",
    "goal_binding_phi_ground_any_bf16",
]


def _canonical(name: str = STAGE_ONE[0]) -> dict:
    return json.loads((PROFILES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def isolated_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetch, "MODEL_TEST_ROOT", tmp_path)
    monkeypatch.setattr(storage, "MODEL_TEST_ROOT", tmp_path)


def _hub(monkeypatch: pytest.MonkeyPatch, siblings: list, payloads: dict[str, bytes], revision: str):
    calls = []

    class Api:
        def __init__(self, **kwargs):
            calls.append(("api", kwargs))

        def model_info(self, repo_id, **kwargs):
            calls.append(("info", repo_id, kwargs))
            return SimpleNamespace(sha=revision, siblings=siblings)

    def download(**kwargs):
        calls.append(("download", kwargs))
        target = kwargs["local_dir"] / kwargs["filename"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payloads[kwargs["filename"]])
        return str(target)

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(HfApi=Api, hf_hub_download=download))
    return calls


def _small(name: str, payload: bytes, *, blob: bool = True):
    return SimpleNamespace(
        rfilename=name, size=len(payload), lfs=None,
        blob_id=sha1(b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload).hexdigest() if blob else None,
    )


@pytest.mark.parametrize("name", STAGE_ONE)
def test_canonical_profile_and_selectors_project_same_pinned_checkpoint_without_network(name, monkeypatch, tmp_path):
    profile = _canonical(name)
    monkeypatch.setitem(sys.modules, "huggingface_hub", None)
    expected = {
        "provider_id": profile["provider_id"], "repo_id": profile["repository_id"],
        "revision": profile["upstream_revision"], "artifact_files": [], "full_checkpoint": True,
    }
    assert fetch.project_profile(profile=profile) == expected
    assert fetch.project_profile(provider_id=profile["provider_id"], repo_id=profile["repository_id"], full_checkpoint=True) == expected
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("change", [
    {"repository_id": "wrong/repo"}, {"repo_id": "wrong/repo"},
    {"upstream_revision": "b" * 40}, {"revision": "main"},
    {"provider_id": "unknown-provider"}, {"upstream_revision": None},
])
def test_canonical_projection_rejects_identity_or_revision_drift(change):
    profile = _canonical()
    profile.update(change)
    with pytest.raises(ValueError, match="checked-in|immutable"):
        fetch.project_profile(profile=profile)


def test_selectors_require_unique_checked_in_match(monkeypatch, tmp_path):
    profile = _canonical()
    with pytest.raises(ValueError, match="checked-in"):
        fetch.project_profile(provider_id=profile["provider_id"], repo_id="wrong/repo", full_checkpoint=True)
    directory = tmp_path / "profiles"
    directory.mkdir()
    for name in ("one.json", "two.json"):
        (directory / name).write_text(json.dumps(profile), encoding="utf-8")
    monkeypatch.setattr(fetch, "_PROFILE_DIRECTORY", directory)
    with pytest.raises(ValueError, match="unique"):
        fetch.project_profile(provider_id=profile["provider_id"], full_checkpoint=True)


def test_unpinned_canonical_is_not_resolved_through_main():
    with pytest.raises(ValueError, match="immutable"):
        fetch.project_profile(profile=_canonical("goal_binding_groundnext_7b_q6_k"))


def test_gguf_projection_excludes_local_runtime_and_source_artifacts():
    profile = _canonical("goal_binding_ui_venus_1_5_8b_q6_k")
    projected = fetch.project_profile(profile=profile)
    assert projected["artifact_files"] == ["UI-Venus-1.5-8B-Q6_K.gguf", "mmproj-Q8_0.gguf"]
    assert projected["full_checkpoint"] is False


def test_cli_selectors_are_projected_before_explicit_fetch(monkeypatch, capsys):
    profile = _canonical()
    seen = []
    monkeypatch.setattr(fetch, "fetch_profile", lambda **kwargs: seen.append(kwargs) or Path("manifest.json"))
    assert fetch.main(["--provider-id", profile["provider_id"], "--repo-id", profile["repository_id"], "--full-checkpoint"]) == 0
    assert seen[0]["profile"] == fetch.project_profile(profile=profile)
    assert json.loads(capsys.readouterr().out)["artifact_is_authorization"] is False


def test_cli_profile_and_conflicting_selector_reject_before_fetch(monkeypatch):
    monkeypatch.setattr(fetch, "fetch_profile", lambda **kwargs: pytest.fail("must not fetch"))
    with pytest.raises(SystemExit):
        fetch.main(["--profile", str(PROFILES / f"{STAGE_ONE[0]}.json"), "--repo-id", "wrong/repo"])


@pytest.mark.parametrize("lfs_object", [False, True])
def test_full_checkpoint_seals_every_sibling_with_lfs_and_non_lfs_hashes(tmp_path, monkeypatch, lfs_object):
    profile = _canonical()
    payloads = {"model-00001.safetensors": b"weights", "config.json": b"{}", "nested/tokenizer.json": b"tokenizer", "README.md": b"card"}
    lfs = {"sha256": sha256(b"weights").hexdigest(), "size": 7}
    if lfs_object:
        lfs = SimpleNamespace(**lfs)
    siblings = [SimpleNamespace(rfilename="model-00001.safetensors", size=None, lfs=lfs)]
    siblings.extend(_small(name, data, blob=name != "README.md") for name, data in payloads.items() if name != "model-00001.safetensors")
    calls = _hub(monkeypatch, siblings, payloads, profile["upstream_revision"])
    original = fetch.materialize_downloaded_artifact
    sealed = []

    def materialize(**kwargs):
        sealed.append(dict(kwargs["expected_sha256"]))
        return original(**kwargs)

    monkeypatch.setattr(fetch, "materialize_downloaded_artifact", materialize)
    manifest = fetch.fetch_profile(profile=profile, root=tmp_path)
    assert sealed == [{name: sha256(data).hexdigest() for name, data in payloads.items()}]
    document = json.loads(manifest.read_text(encoding="utf-8"))
    assert len(document["files"]) == len(payloads)
    assert calls[1][2] == {"revision": profile["upstream_revision"], "files_metadata": True}
    assert [call[1]["filename"] for call in calls if call[0] == "download"] == list(payloads)
    for call in calls:
        if call[0] == "download":
            assert call[1]["revision"] == profile["upstream_revision"]


@pytest.mark.parametrize("names", [
    ["config.json", "config.json"], ["config.json", "CONFIG.json"],
    ["../escape"], ["/absolute"], ["C:/absolute"], ["nested\\escape"],
    ["a/./b"], ["a//b"], ["a/../b"], ["file:stream"], ["NUL"],
    ["trailing."], [".cache/huggingface/meta"], [".goal-binding-transaction.json"],
    ["config", "config/nested.json"],
])
def test_full_checkpoint_rejects_unsafe_or_duplicate_metadata_before_staging(tmp_path, monkeypatch, names):
    profile = _canonical()
    siblings = [_small(name, b"x") for name in names]
    calls = _hub(monkeypatch, siblings, {}, profile["upstream_revision"])
    with pytest.raises(ValueError, match="unsafe|duplicate|collision"):
        fetch.fetch_profile(profile=profile, root=tmp_path)
    assert not (tmp_path / "staging").exists()
    assert not any(call[0] == "download" for call in calls)


@pytest.mark.parametrize("size", [None, True, -1, "1"])
def test_full_checkpoint_rejects_unavailable_size_before_staging(tmp_path, monkeypatch, size):
    profile = _canonical()
    _hub(monkeypatch, [SimpleNamespace(rfilename="config.json", size=size, lfs=None)], {}, profile["upstream_revision"])
    with pytest.raises(ValueError, match="size is unavailable"):
        fetch.fetch_profile(profile=profile, root=tmp_path)
    assert not (tmp_path / "staging").exists()


def test_canonical_metadata_revision_mismatch_rejected_before_staging(tmp_path, monkeypatch):
    profile = _canonical()
    _hub(monkeypatch, [_small("config.json", b"{}")], {}, "a" * 40)
    with pytest.raises(ValueError, match="revision"):
        fetch.fetch_profile(profile=profile, root=tmp_path)
    assert not (tmp_path / "staging").exists()


@pytest.mark.parametrize("kind", ["blob_mismatch", "malformed_blob", "wrong_size", "missing_lfs_sha", "wrong_lfs_sha"])
def test_checkpoint_verification_failure_never_materializes(tmp_path, monkeypatch, kind):
    profile = _canonical()
    sibling = _small("config.json", b"{}")
    if kind == "blob_mismatch":
        sibling.blob_id = "a" * 40
    elif kind == "malformed_blob":
        sibling.blob_id = "bad"
    elif kind == "wrong_size":
        sibling.size = 3
    else:
        sibling.lfs = {} if kind == "missing_lfs_sha" else {"sha256": "a" * 64}
    _hub(monkeypatch, [sibling], {"config.json": b"{}"}, profile["upstream_revision"])
    with pytest.raises(ValueError, match="verification|blob|SHA-256"):
        fetch.fetch_profile(profile=profile, root=tmp_path)
    assert not (tmp_path / "artifacts").exists()
    assert not (tmp_path / "staging" / profile["provider_id"] / profile["upstream_revision"]).exists()


def test_non_lfs_mutation_is_caught_by_unchanged_materialize_rehash(tmp_path, monkeypatch):
    profile = _canonical()
    _hub(monkeypatch, [_small("config.json", b"{}")], {"config.json": b"{}"}, profile["upstream_revision"])

    def mutate(**kwargs):
        (kwargs["staging_path"] / "config.json").write_bytes(b"[]")

    monkeypatch.setattr(fetch, "remove_huggingface_local_metadata", mutate)
    with pytest.raises(ValueError, match="changed"):
        fetch.fetch_profile(profile=profile, root=tmp_path)
    assert not (tmp_path / "artifacts").exists()


def test_full_checkpoint_requires_nonempty_metadata(tmp_path, monkeypatch):
    profile = _canonical()
    _hub(monkeypatch, [], {}, profile["upstream_revision"])
    with pytest.raises(ValueError, match="empty"):
        fetch.fetch_profile(profile=profile, root=tmp_path)
    assert not (tmp_path / "staging").exists()
