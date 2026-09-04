"""Materialize a sealed UI-Venus SDPA runtime from a prepared isolated staging tree."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import uuid

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.learn.hybrid import goal_binding_deployed_artifacts as deployed
from app.learn.hybrid import model_test_storage as storage
from scripts.model_servers.goal_binding_provider_runtimes import UI_VENUS_CENTER_POINT_PROMPT

OFFICIAL_SOURCE_GIT_REVISION = "192a9247ad1129279ba1d6c263d4c9e7ecef3644"


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")


def _git(source_checkout: Path, *arguments: str) -> str:
    result = subprocess.run(["git", "-C", str(source_checkout), *arguments], check=False, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise ValueError("pinned UI-Venus source checkout is unavailable")
    return result.stdout.strip()


def _verified_official_source(source_checkout: Path) -> dict[str, bytes]:
    if _git(source_checkout, "status", "--porcelain"):
        raise ValueError("pinned UI-Venus source checkout is dirty")
    if _git(source_checkout, "rev-parse", "HEAD") != OFFICIAL_SOURCE_GIT_REVISION:
        raise ValueError("pinned UI-Venus source revision is invalid")
    result: dict[str, bytes] = {}
    for relative, digest in deployed.OFFICIAL_SOURCE_FILES.items():
        command = ["git", "-C", str(source_checkout), "show", f"{OFFICIAL_SOURCE_GIT_REVISION}:{relative}"]
        completed = subprocess.run(command, check=False, capture_output=True)
        if completed.returncode != 0 or sha256(completed.stdout).hexdigest() != digest:
            raise ValueError("pinned UI-Venus official source file hash is invalid")
        result[relative] = completed.stdout
    return result


def _smoke_script() -> str:
    return '''import importlib\nimport importlib.metadata\nimport json\nfrom pathlib import Path\nimport platform\nimport sys\nruntime = Path(sys.argv[1]).resolve()\nsite_packages = runtime / "site-packages"\nsys.path.insert(0, str(site_packages))\nitems = [("torch", "torch"), ("torchvision", "torchvision"), ("transformers", "transformers"), ("accelerate", "accelerate"), ("qwen-vl-utils", "qwen_vl_utils"), ("Pillow", "PIL"), ("psutil", "psutil")]\npackages = []\nfor distribution, module_name in items:\n    module = importlib.import_module(module_name)\n    origin = Path(module.__file__).resolve()\n    try:\n        relative = origin.relative_to(runtime).as_posix()\n    except ValueError:\n        raise RuntimeError("module origin escapes staging runtime")\n    packages.append({"distribution": distribution, "version": importlib.metadata.version(distribution), "module_origin": relative})\nprint(json.dumps({"python": {"implementation": platform.python_implementation(), "version": platform.python_version()}, "packages": packages}, sort_keys=True))\n'''


def _run_smoke(runtime_staging: Path) -> dict[str, object]:
    executable = runtime_staging / "Scripts" / "python.exe"
    if not executable.is_file():
        raise ValueError("prepared isolated runtime has no python.exe")
    script = runtime_staging / "runtime-smoke.py"
    script.write_text(_smoke_script(), encoding="utf-8", newline="\n")
    result = subprocess.run([str(executable), "-I", str(script), str(runtime_staging)], check=False, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise ValueError("prepared isolated runtime smoke failed")
    try:
        observed = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("prepared isolated runtime smoke emitted invalid JSON") from exc
    if not isinstance(observed, dict) or set(observed) != {"python", "packages"}:
        raise ValueError("prepared isolated runtime smoke emitted invalid identity")
    packages = observed.get("packages")
    if not isinstance(packages, list) or len(packages) != len(deployed.RUNTIME_PACKAGE_VERSIONS):
        raise ValueError("prepared isolated runtime smoke package set is invalid")
    names = set()
    for package in packages:
        if not isinstance(package, dict) or set(package) != {"distribution", "version", "module_origin"}:
            raise ValueError("prepared isolated runtime smoke package is invalid")
        distribution = package["distribution"]
        origin = package["module_origin"]
        if distribution in names or package["version"] != deployed.RUNTIME_PACKAGE_VERSIONS.get(distribution) or not isinstance(origin, str):
            raise ValueError("prepared isolated runtime smoke package version is invalid")
        try:
            (runtime_staging / origin).resolve().relative_to(runtime_staging.resolve())
        except ValueError as exc:
            raise ValueError("prepared isolated runtime smoke module origin escapes staging") from exc
        names.add(distribution)
    if names != set(deployed.RUNTIME_PACKAGE_VERSIONS):
        raise ValueError("prepared isolated runtime smoke package set is incomplete")
    return observed


def _expected_tree(root: Path) -> tuple[dict[str, int], dict[str, str]]:
    files = {path.relative_to(root).as_posix(): path for path in root.rglob("*") if path.is_file()}
    if not files:
        raise ValueError("prepared isolated runtime is empty")
    return ({name: path.stat().st_size for name, path in files.items()}, {name: _sha256(path) for name, path in files.items()})


def _reference(path: Path, root: Path) -> dict[str, str]:
    return {"relative_path": path.relative_to(root).as_posix(), "sha256": _sha256(path)}


def prepare_ui_venus_sdpa_runtime(*, root: Path, checkpoint_manifest: Path, runtime_staging: Path, source_checkout: Path, profile_template: Path) -> dict[str, Path]:
    root = storage._require_model_test_root(Path(root))
    if not storage.inventory_storage(root)["within_cap"]:
        raise ValueError("model-test storage exceeds the cap")
    runtime_staging = Path(runtime_staging)
    expected_staging = root / "staging" / deployed.WINDOWS_SDPA_RUNTIME_PROVIDER / deployed.WINDOWS_SDPA_RUNTIME_REVISION
    if runtime_staging.resolve() != expected_staging.resolve():
        raise ValueError("prepared runtime staging path is not the sealed UI-Venus SDPA namespace")
    _, _, checkpoint_resolved = storage._load_manifest(root, Path(checkpoint_manifest))
    checkpoint_payload = json.loads(checkpoint_resolved.read_text(encoding="utf-8"))
    if checkpoint_payload.get("provider_id") != deployed.UI_VENUS_PROVIDER or checkpoint_payload.get("repo_id") != deployed.UI_VENUS_REPOSITORY or checkpoint_payload.get("revision") != deployed.UI_VENUS_CHECKPOINT_REVISION:
        raise ValueError("checkpoint parent identity is invalid")
    checkpoint_files = {Path(item["relative_path"]).name for item in checkpoint_payload.get("files", []) if isinstance(item, dict)}
    if checkpoint_files != deployed.UI_VENUS_CHECKPOINT_FILES:
        raise ValueError("checkpoint parent is not the exact expected nine-file snapshot")
    official_source = _verified_official_source(Path(source_checkout))
    smoke = _run_smoke(runtime_staging)
    namespace = Path("artifacts") / deployed.WINDOWS_SDPA_RUNTIME_PROVIDER / deployed.WINDOWS_SDPA_RUNTIME_REVISION
    smoke = {
        **smoke,
        "packages": [
            {**item, "module_origin": (namespace / str(item["module_origin"])).as_posix()}
            for item in smoke["packages"]
        ],
    }
    for relative, payload in official_source.items():
        target = runtime_staging / "official" / relative
        if target.exists():
            raise ValueError("prepared runtime already contains official source")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    source_path = runtime_staging / "official-source.json"
    source_document = {
        "contract_version": "goal_binding_ui_venus_source_identity_v1",
        "official_source_revision": deployed.OFFICIAL_SOURCE_REVISION,
        "official_source_files": dict(deployed.OFFICIAL_SOURCE_FILES),
        "project_revision": deployed.WINDOWS_SDPA_RUNTIME_REVISION,
        "code_files": deployed._current_code_hashes(),
    }
    _write_json(source_path, source_document)
    preprocessing_path = runtime_staging / "preprocessing.json"
    _write_json(preprocessing_path, {
        "contract_version": "goal_binding_ui_venus_preprocessing_v1",
        "source_document_sha256": _sha256(source_path),
        "official_attention_implementation": "flash_attention_2",
        "tested_attention_implementation": "sdpa",
        "prompt": {"sha256": sha256(UI_VENUS_CENTER_POINT_PROMPT.encode("utf-8")).hexdigest(), "utf8": UI_VENUS_CENTER_POINT_PROMPT},
        "dtype": "bfloat16", "max_new_tokens": 128, "native_output_kind": "ui_venus_point_v1", "coordinate_space": "normalized_0_1000",
    })
    smoke_path = runtime_staging / "runtime-smoke.json"
    _write_json(smoke_path, {"contract_version": "goal_binding_ui_venus_sdpa_runtime_smoke_v1", **smoke, "python_executable_sha256": _sha256(runtime_staging / "Scripts" / "python.exe"), "smoke_script_sha256": _sha256(runtime_staging / "runtime-smoke.py"), "exit_code": 0})
    expected_files, expected_sha256 = _expected_tree(runtime_staging)
    runtime_manifest = storage.materialize_downloaded_artifact(root=root, provider_id=deployed.WINDOWS_SDPA_RUNTIME_PROVIDER, repo_id=deployed.WINDOWS_SDPA_RUNTIME_REPOSITORY, revision=deployed.WINDOWS_SDPA_RUNTIME_REVISION, staging_path=runtime_staging, expected_files=expected_files, expected_sha256=expected_sha256)
    profile = json.loads(Path(profile_template).read_text(encoding="utf-8"))
    roles = {
        "model": root / next(item["relative_path"] for item in checkpoint_payload["files"] if item["relative_path"].endswith("model.safetensors")),
        "runtime": root / "artifacts" / deployed.WINDOWS_SDPA_RUNTIME_PROVIDER / deployed.WINDOWS_SDPA_RUNTIME_REVISION / "Scripts" / "python.exe",
        "source": root / "artifacts" / deployed.WINDOWS_SDPA_RUNTIME_PROVIDER / deployed.WINDOWS_SDPA_RUNTIME_REVISION / "official-source.json",
        "preprocessing": root / "artifacts" / deployed.WINDOWS_SDPA_RUNTIME_PROVIDER / deployed.WINDOWS_SDPA_RUNTIME_REVISION / "preprocessing.json",
    }
    report = root / "reports" / "ui-venus-sdpa-deployments" / uuid.uuid4().hex
    report.mkdir(parents=True, exist_ok=False)
    deployment_path = report / "deployment.json"
    deployment = {"contract_version": deployed.CONTRACT_VERSION, "provider_id": deployed.UI_VENUS_PROVIDER, "repo_id": deployed.UI_VENUS_REPOSITORY, "revision": deployed.UI_VENUS_CHECKPOINT_REVISION, "checkpoint_parent": _reference(checkpoint_resolved, root), "runtime_parent": _reference(runtime_manifest, root), "artifacts": [{"role": role, "parent": "checkpoint" if role == "model" else "runtime", "relative_path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": _sha256(path)} for role, path in roles.items()], "artifact_is_authorization": False}
    _write_json(deployment_path, deployment)
    profile["upstream_revision"] = deployed.UI_VENUS_CHECKPOINT_REVISION
    profile["artifact_manifest"] = {"status": "verified", **_reference(deployment_path, root)}
    profile["artifacts"] = [{"role": role, "relative_path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": _sha256(path)} for role, path in roles.items()]
    profile["runtime"]["isolated_runtime_path"] = roles["runtime"].relative_to(root).as_posix()
    profile["runtime"]["sha256"] = _sha256(roles["runtime"])
    profile["preprocessing"]["sha256"] = _sha256(roles["preprocessing"])
    profile["preprocessing"]["source_revision"] = deployed.OFFICIAL_SOURCE_REVISION
    profile_path = report / "profile.json"
    _write_json(profile_path, profile)
    deployed.verify_ui_venus_deployment(profile, root)
    return {"runtime_manifest": runtime_manifest, "deployment_manifest": deployment_path, "profile": profile_path}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--checkpoint-manifest", required=True, type=Path)
    parser.add_argument("--runtime-staging", required=True, type=Path)
    parser.add_argument("--source-checkout", required=True, type=Path)
    parser.add_argument("--profile-template", required=True, type=Path)
    args = parser.parse_args()
    result = prepare_ui_venus_sdpa_runtime(root=args.root, checkpoint_manifest=args.checkpoint_manifest, runtime_staging=args.runtime_staging, source_checkout=args.source_checkout, profile_template=args.profile_template)
    print(json.dumps({name: str(path) for name, path in result.items()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
