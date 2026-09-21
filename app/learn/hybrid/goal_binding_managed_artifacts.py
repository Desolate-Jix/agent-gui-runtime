"""Read-only incumbent identities, separate from disposable download manifests."""
from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from app.learn.hybrid import model_test_storage as storage

VERSION = "goal_binding_managed_incumbent_artifact_manifest_v1"
PROVIDER = "qwen3_vl_8b_q4_k_m"
REPOSITORY = "Qwen/Qwen3-VL-8B-Instruct-GGUF"
REVISION = "f982a07559d4a2f6c8744d840bf6fccab30eea96"
READONLY_ROOT = Path(r"D:\agent-gui-runtime")
REPO_ROOT = Path(__file__).resolve().parents[3]
EXPECTED_WEIGHTS = {
    "model": {"sha256": "67d1659bfe71b89d50b45a4ad1a9e5b997e5bb16ce5da66a6a6167abd569e9e2", "bytes": 5027784800},
    "mmproj": {"sha256": "c6ba85508d82f42590e6eb77d5340369ab6fecf107a7561d809523d8aa5f3bfd", "bytes": 752289728},
}
CODE_PATHS = (
    "app/core/model_server.py",
    "app/learn/hybrid/goal_binding_managed_artifacts.py",
    "app/learn/hybrid/goal_binding_model_callers.py",
    "scripts/model_servers/goal_binding_transformers_worker.py",
    "scripts/model_servers/goal_binding_provider_runtimes.py",
    "scripts/model_servers/start_llama_vision_server.ps1",
    "scripts/model_servers/stop_local_vision_server.ps1",
    "configs/model_profiles/qwen3_vl_8b_q4_k_m.json",
)


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _read_json(path):
    from app.learn.hybrid.goal_binding_model_callers import _closed_object
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_closed_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("managed identity document unavailable") from exc


def _file_identity(path):
    try:
        resolved = path.resolve(strict=True)
        return {"path": str(resolved), "bytes": resolved.stat().st_size, "sha256": storage._sha256(resolved)}
    except OSError as exc:
        raise ValueError("managed artifact identity unavailable") from exc


def _selected_profile():
    from app.core.model_server import profile_for_stage
    return profile_for_stage("understanding", PROVIDER)


def _asset_paths(selected):
    root = READONLY_ROOT.resolve(strict=True)
    result = {}
    for role, key in (("model", "model_path"), ("mmproj", "mmproj_path"), ("runtime", "server_path")):
        path = (REPO_ROOT / selected[key]).resolve(strict=True)
        if not path.is_relative_to(root):
            raise ValueError("managed read-only source origin escaped its bound root")
        result[role] = path
    return result


def _dll_identities(runtime):
    identities = []
    for path in sorted(runtime.parent.glob("*.dll")):
        identity = _file_identity(path)
        if Path(identity["path"]).parent != runtime.parent:
            raise ValueError("managed runtime DLL source origin escaped its directory")
        identities.append(identity)
    return identities


def _environment():
    dependencies = []
    for dist in importlib.metadata.distributions():
        records = [dist.locate_file(item) for item in (dist.files or ()) if str(item).endswith(".dist-info/RECORD")]
        dependencies.append({"name": dist.metadata["Name"], "version": dist.version,
                             "record": _file_identity(Path(records[0])) if len(records) == 1 else None,
                             "record_status": "verified" if len(records) == 1 else "unavailable"})
    return {"python": _file_identity(Path(sys.executable)), "version": sys.version,
            "dependencies": sorted(dependencies, key=lambda item: (item["name"].lower(), item["version"]))}


def _code_identity():
    return [{"relative_path": name, **_file_identity(REPO_ROOT / name)} for name in CODE_PATHS]


def _require_incumbent(profile):
    if profile.get("provider_id") != PROVIDER or profile.get("native_output", {}).get("kind") != "qwen_goal_binding_array_v1":
        raise ValueError("managed manifest is only for the exact Qwen incumbent")


def build_incumbent_documents(template, artifact_root: Path, *, directory: str):
    """Read assets and construct documents without writing or launching anything."""
    from app.learn.hybrid.goal_binding_model_callers import _validate_profile, _relative
    _require_incumbent(template)
    profile = _validate_profile(template)
    directory = _relative(directory, "managed report directory")
    if Path(directory).parts[0] != "reports":
        raise ValueError("managed identity files must be under reports")
    selected = _selected_profile()
    paths = _asset_paths(selected)
    files = []
    for role, path in paths.items():
        identity = _file_identity(path)
        if role in EXPECTED_WEIGHTS and any(identity[key] != value for key, value in EXPECTED_WEIGHTS[role].items()):
            raise ValueError("managed weight identity differs from pinned upstream")
        files.append({"role": role, "relative_path": path.relative_to(READONLY_ROOT.resolve()).as_posix(), "origin": "readonly", **identity})
    dlls = _dll_identities(paths["runtime"])
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, encoding="utf-8").strip()
    dirty = subprocess.check_output(["git", "diff", "HEAD", "--name-only", "--", *CODE_PATHS], cwd=REPO_ROOT, text=True, encoding="utf-8").splitlines()
    source = {"contract_version": "goal_binding_managed_source_v1", "repo_root": str(REPO_ROOT.resolve()),
              "revision": revision, "modified_tracked_code": dirty, "code": _code_identity(), "environment": _environment()}
    preprocessing = {"contract_version": "goal_binding_managed_preprocessing_v1", "source_sha256": sha256(_json_bytes(source)).hexdigest(),
                     "identity": "sealed_incumbent_qwen_projection_v1", "managed_profile": selected}
    documents = {}
    for role, value in (("source", source), ("preprocessing", preprocessing)):
        relative = f"{directory}/{role}.json"
        raw = _json_bytes(value)
        documents[relative] = raw
        files.append({"role": role, "relative_path": relative, "origin": "reports", "path": str((artifact_root / relative).resolve()), "bytes": len(raw), "sha256": sha256(raw).hexdigest()})
    manifest = {"contract_version": VERSION, "provider_id": PROVIDER, "repo_id": REPOSITORY, "revision": REVISION,
                "readonly_root": str(READONLY_ROOT.resolve()), "managed_profile": selected, "files": files,
                "dll_files": dlls, "artifact_is_authorization": False}
    relative = f"{directory}/manifest.json"
    documents[relative] = _json_bytes(manifest)
    profile.update(repository_id=REPOSITORY, upstream_revision=REVISION,
                   artifacts=[{key: item[key] for key in ("role", "relative_path", "bytes", "sha256")} for item in files],
                   artifact_manifest={"status": "verified", "relative_path": relative, "sha256": sha256(documents[relative]).hexdigest()})
    profile["runtime"].update(isolated_runtime_path=files[2]["relative_path"], sha256=files[2]["sha256"])
    profile["preprocessing"].update(source_revision="local-repo@" + revision, sha256=files[4]["sha256"])
    documents[f"{directory}/profile.json"] = _json_bytes(_validate_profile(profile))
    return documents


def materialize_incumbent_profile(template, artifact_root: Path) -> Path:
    """Explicitly publish small reports only; never write the read-only asset tree."""
    from scripts.fetch_goal_binding_model import _quota_reservation
    root = storage._require_model_test_root(artifact_root)
    directory = "reports/managed-incumbent-" + uuid4().hex
    documents = build_incumbent_documents(template, root, directory=directory)
    with _quota_reservation(root):
        storage.assert_download_fits(root=root, remote_bytes=sum(map(len, documents.values())))
        destination = storage._guarded_directory(root, *Path(directory).parts)
        for relative, raw in documents.items():
            storage._guard(root, destination)
            path = root / relative
            with path.open("xb") as stream:
                stream.write(raw)
            storage._guard(root, path)
        if not storage.inventory_storage(root)["within_cap"]:
            raise ValueError("managed reports exceed the 30 GiB storage cap")
        profile_path = destination / "profile.json"
        verify_managed_artifacts(_read_json(profile_path), root)
    return profile_path


def verify_managed_artifacts(profile, artifact_root: Path) -> dict[str, Path]:
    """Compare current files with sealed expected identities in parent and worker."""
    from app.learn.hybrid.goal_binding_model_callers import _validate_profile, _safe_under
    _require_incumbent(profile)
    profile = _validate_profile(profile)
    ref = profile["artifact_manifest"]
    manifest_path = _safe_under(artifact_root, ref["relative_path"])
    storage._guard(artifact_root, manifest_path)
    manifest = _read_json(manifest_path)
    if ref["status"] != "verified" or storage._sha256(manifest_path) != ref["sha256"]:
        raise ValueError("managed manifest identity changed")
    fields = {"contract_version", "provider_id", "repo_id", "revision", "readonly_root", "managed_profile", "files", "dll_files", "artifact_is_authorization"}
    if not isinstance(manifest, Mapping) or set(manifest) != fields or manifest["contract_version"] != VERSION or manifest["provider_id"] != PROVIDER or manifest["repo_id"] != REPOSITORY or manifest["revision"] != REVISION or manifest["artifact_is_authorization"] is not False:
        raise ValueError("managed manifest identity invalid")
    selected = _selected_profile()
    if manifest["readonly_root"] != str(READONLY_ROOT.resolve()) or manifest["managed_profile"] != selected or profile["repository_id"] != REPOSITORY or profile["upstream_revision"] != REVISION:
        raise ValueError("managed read-only root or selected profile identity changed")
    try:
        assets = _asset_paths(selected)
    except OSError as exc:
        raise ValueError("managed artifact identity unavailable") from exc
    rows = manifest["files"]
    if not isinstance(rows, list) or len(rows) != 5 or {row.get("role") for row in rows if isinstance(row, Mapping)} != {"model", "mmproj", "runtime", "source", "preprocessing"}:
        raise ValueError("managed artifact roles invalid")
    expected_profile = {item["role"]: item for item in profile["artifacts"]}
    if set(expected_profile) != {row["role"] for row in rows}:
        raise ValueError("managed profile artifact roles changed")
    result = {}
    for row in rows:
        if set(row) != {"role", "relative_path", "origin", "path", "bytes", "sha256"}:
            raise ValueError("managed artifact record invalid")
        role = row["role"]
        if row["origin"] != ("readonly" if role in assets else "reports"):
            raise ValueError("managed artifact source origin invalid")
        if role in assets:
            path = assets[role]
            if row["relative_path"] != path.relative_to(READONLY_ROOT.resolve()).as_posix():
                raise ValueError("managed read-only relative identity changed")
        else:
            path = _safe_under(artifact_root, row["relative_path"])
            storage._guard(artifact_root, path)
            if not path.is_relative_to((artifact_root / "reports").resolve()):
                raise ValueError("managed source origin is not reports")
        identity = _file_identity(path)
        if identity != {key: row[key] for key in identity} or expected_profile[role] != {key: row[key] for key in ("role", "relative_path", "bytes", "sha256")}:
            raise ValueError("managed artifact identity changed")
        if role in EXPECTED_WEIGHTS and any(identity[key] != value for key, value in EXPECTED_WEIGHTS[role].items()):
            raise ValueError("managed weight identity differs from pinned upstream")
        result[role] = path
    dlls = _dll_identities(assets["runtime"])
    if dlls != manifest["dll_files"]:
        raise ValueError("managed runtime DLL identities changed")
    source = _read_json(result["source"])
    if not isinstance(source, Mapping) or set(source) != {"contract_version", "repo_root", "revision", "modified_tracked_code", "code", "environment"} or source.get("contract_version") != "goal_binding_managed_source_v1" or source.get("repo_root") != str(REPO_ROOT.resolve()) or source.get("code") != _code_identity():
        raise ValueError("managed source code identity changed")
    if source.get("environment") != _environment():
        raise ValueError("managed interpreter or dependency identity changed")
    preprocessing = _read_json(result["preprocessing"])
    if preprocessing != {"contract_version": "goal_binding_managed_preprocessing_v1", "source_sha256": storage._sha256(result["source"]), "identity": "sealed_incumbent_qwen_projection_v1", "managed_profile": selected}:
        raise ValueError("managed preprocessing identity changed")
    if profile["runtime"]["sha256"] != expected_profile["runtime"]["sha256"] or profile["runtime"]["isolated_runtime_path"] != expected_profile["runtime"]["relative_path"] or profile["preprocessing"]["sha256"] != expected_profile["preprocessing"]["sha256"] or profile["preprocessing"]["source_revision"] != "local-repo@" + source["revision"]:
        raise ValueError("managed runtime or preprocessing profile identity changed")
    return result
