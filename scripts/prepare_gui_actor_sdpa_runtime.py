"""Materialize a sealed GUI-Actor Windows SDPA runtime."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.learn.hybrid import goal_binding_gui_actor_deployed_artifacts as deployed
from app.learn.hybrid import model_test_storage as storage


OFFICIAL_SOURCE_GIT_REVISION = "d98d1bbd01862f9112114b83b032f492c365a173"


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _git(source: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(source), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise ValueError("pinned GUI-Actor source checkout is unavailable")
    return result.stdout.strip()


def _verified_official_source(source: Path) -> dict[str, bytes]:
    if _git(source, "status", "--porcelain"):
        raise ValueError("pinned GUI-Actor source checkout is dirty")
    if _git(source, "rev-parse", "HEAD") != OFFICIAL_SOURCE_GIT_REVISION:
        raise ValueError("pinned GUI-Actor source revision is invalid")
    result: dict[str, bytes] = {}
    for relative, repository_relative in sorted(deployed.OFFICIAL_SOURCE_FILES.items()):
        completed = subprocess.run(
            ["git", "-C", str(source), "show", f"{OFFICIAL_SOURCE_GIT_REVISION}:{repository_relative}"],
            check=False,
            capture_output=True,
        )
        if completed.returncode != 0:
            raise ValueError("pinned GUI-Actor source import closure is incomplete")
        result[relative] = completed.stdout
    return result


def _smoke_script() -> str:
    return '''import importlib\nimport importlib.metadata\nimport json\nfrom pathlib import Path\nimport platform\nimport sys\nruntime = Path(sys.argv[1]).resolve()\nsys.path.insert(0, str(runtime / "official"))\nsys.path.insert(0, str(runtime / "Lib" / "site-packages"))\nitems = [("torch", "torch"), ("torchvision", "torchvision"), ("transformers", "transformers"), ("accelerate", "accelerate"), ("qwen-vl-utils", "qwen_vl_utils"), ("Pillow", "PIL"), ("psutil", "psutil")]\npackages = []\nfor distribution, module_name in items:\n    module = importlib.import_module(module_name)\n    origin = Path(module.__file__).resolve()\n    try:\n        relative = origin.relative_to(runtime).as_posix()\n    except ValueError:\n        raise RuntimeError("module origin escapes staging runtime")\n    packages.append({"distribution": distribution, "version": importlib.metadata.version(distribution), "module_origin": relative})\nfrom gui_actor.modeling_qwen25vl import Qwen2_5_VLForConditionalGenerationWithPointer\nfrom gui_actor.inference import inference\nfrom gui_actor.constants import grounding_system_message\nif not isinstance(Qwen2_5_VLForConditionalGenerationWithPointer, type) or not callable(inference) or not isinstance(grounding_system_message, str) or not grounding_system_message:\n    raise RuntimeError("GUI-Actor official import identity is invalid")\nprint(json.dumps({"python": {"implementation": platform.python_implementation(), "version": platform.python_version()}, "packages": packages}, sort_keys=True))\n'''


def _validated_smoke_output(value: object, runtime: Path) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {"python", "packages"}:
        raise ValueError("GUI-Actor runtime smoke emitted invalid identity")
    python, packages = value.get("python"), value.get("packages")
    if (
        not isinstance(python, dict)
        or set(python) != {"implementation", "version"}
        or python.get("implementation") != "CPython"
        or not isinstance(python.get("version"), str)
        or not isinstance(packages, list)
        or len(packages) != len(deployed.RUNTIME_PACKAGE_VERSIONS)
    ):
        raise ValueError("GUI-Actor runtime smoke identity is invalid")
    observed: set[str] = set()
    for item in packages:
        if not isinstance(item, dict) or set(item) != {
            "distribution",
            "version",
            "module_origin",
        }:
            raise ValueError("GUI-Actor runtime smoke package is invalid")
        distribution, origin = item.get("distribution"), item.get("module_origin")
        if (
            not isinstance(distribution, str)
            or distribution in observed
            or item.get("version") != deployed.RUNTIME_PACKAGE_VERSIONS.get(distribution)
        ):
            raise ValueError("GUI-Actor runtime smoke package version is invalid")
        if (
            not isinstance(origin, str)
            or not origin
            or Path(origin).is_absolute()
            or ".." in Path(origin).parts
        ):
            raise ValueError("GUI-Actor runtime smoke module origin is invalid")
        (runtime / origin).resolve().relative_to(runtime.resolve())
        observed.add(distribution)
    if observed != set(deployed.RUNTIME_PACKAGE_VERSIONS):
        raise ValueError("GUI-Actor runtime smoke package set is incomplete")
    return value


def _run_smoke(runtime: Path) -> dict[str, object]:
    executable = runtime / "Scripts" / "python.exe"
    script = runtime / "runtime-smoke.py"
    if not executable.is_file() or not script.is_file() or script.read_text(encoding="utf-8") != _smoke_script():
        raise ValueError("prepared GUI-Actor runtime smoke inputs are invalid")
    environment = dict(os.environ)
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    environment.update(
        {
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
    )
    result = subprocess.run(
        [str(executable), "-I", "-B", str(script), str(runtime)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
    )
    if result.returncode != 0:
        raise ValueError("prepared GUI-Actor runtime smoke failed")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("prepared GUI-Actor runtime smoke emitted invalid JSON") from exc
    return _validated_smoke_output(value, runtime)


def _expected_tree(root: Path) -> tuple[dict[str, int], dict[str, str]]:
    files = {path.relative_to(root).as_posix(): path for path in root.rglob("*") if path.is_file()}
    if not files:
        raise ValueError("prepared GUI-Actor runtime is empty")
    return (
        {name: path.stat().st_size for name, path in files.items()},
        {name: _sha256(path) for name, path in files.items()},
    )


def _reference(path: Path, root: Path) -> dict[str, str]:
    return {"relative_path": path.relative_to(root).as_posix(), "sha256": _sha256(path)}


def _pin_runtime_python_home(root: Path, staging: Path) -> None:
    config = staging / "pyvenv.cfg"
    if not config.is_file() or not (staging / "base" / "python.exe").is_file():
        raise ValueError("prepared GUI-Actor runtime has no relocatable Python base")
    destination = root / "artifacts" / deployed.WINDOWS_SDPA_RUNTIME_PROVIDER / deployed.WINDOWS_SDPA_RUNTIME_REVISION
    values: list[str] = []
    home_seen = False
    executable_seen = False
    for line in config.read_text(encoding="utf-8").splitlines():
        key = line.partition("=")[0].strip().casefold()
        if key == "home":
            values.append(f"home = {destination / 'base'}")
            home_seen = True
        elif key == "executable":
            values.append(f"executable = {destination / 'base' / 'python.exe'}")
            executable_seen = True
        else:
            values.append(line)
    if not home_seen:
        raise ValueError("prepared GUI-Actor runtime has no Python home")
    if not executable_seen:
        values.append(f"executable = {destination / 'base' / 'python.exe'}")
    config.write_text("\n".join(values) + "\n", encoding="utf-8", newline="\n")


def prepare_gui_actor_sdpa_runtime(
    *, root: Path, checkpoint_manifest: Path, runtime_staging: Path,
    source_checkout: Path, profile_template: Path,
) -> dict[str, Path]:
    root = storage._require_model_test_root(Path(root))
    if not storage.inventory_storage(root)["within_cap"]:
        raise ValueError("model-test storage exceeds the cap")
    expected_staging = root / "staging" / deployed.WINDOWS_SDPA_RUNTIME_PROVIDER / deployed.WINDOWS_SDPA_RUNTIME_REVISION
    runtime_staging = Path(runtime_staging)
    if runtime_staging.resolve() != expected_staging.resolve():
        raise ValueError("prepared runtime staging path is invalid")
    _, _, checkpoint_path = storage._load_manifest(root, Path(checkpoint_manifest))
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if (
        checkpoint.get("provider_id") != deployed.GUI_ACTOR_PROVIDER
        or checkpoint.get("repo_id") != deployed.GUI_ACTOR_REPOSITORY
        or checkpoint.get("revision") != deployed.GUI_ACTOR_CHECKPOINT_REVISION
    ):
        raise ValueError("checkpoint parent identity is invalid")
    source_files = _verified_official_source(Path(source_checkout))
    for relative, content in source_files.items():
        installed = runtime_staging / "Lib" / "site-packages" / relative
        if not installed.is_file():
            raise ValueError("prepared runtime installed source is incomplete")
        installed.write_bytes(content)
        target = runtime_staging / "official" / relative
        if target.exists():
            raise ValueError("prepared runtime already contains official source")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    source_path = runtime_staging / "official-source.json"
    _write_json(source_path, {
        "contract_version": "goal_binding_gui_actor_source_identity_v1",
        "official_source_revision": deployed.OFFICIAL_SOURCE_REVISION,
        "official_source_files": {name: sha256(content).hexdigest() for name, content in source_files.items()},
        "project_revision": deployed.WINDOWS_SDPA_RUNTIME_REVISION,
        "code_files": deployed._current_code_hashes(),
    })
    preprocessing_path = runtime_staging / "preprocessing.json"
    _write_json(preprocessing_path, {
        "contract_version": "goal_binding_gui_actor_preprocessing_v1",
        "source_document_sha256": _sha256(source_path),
        "official_attention_implementation": "flash_attention_2",
        "tested_attention_implementation": "sdpa",
        "dtype": "bfloat16", "native_output_kind": "gui_actor_topk_points_v1",
        "coordinate_space": "normalized_0_1", "topk": 3,
        "local_files_only": True, "device_map": "cuda:0",
    })
    smoke_script = runtime_staging / "runtime-smoke.py"
    smoke_script.write_text(_smoke_script(), encoding="utf-8", newline="\n")
    smoke = _run_smoke(runtime_staging)
    namespace = Path("artifacts") / deployed.WINDOWS_SDPA_RUNTIME_PROVIDER / deployed.WINDOWS_SDPA_RUNTIME_REVISION
    smoke["packages"] = [
        {**item, "module_origin": (namespace / item["module_origin"]).as_posix()}
        for item in smoke["packages"]
    ]
    smoke_path = runtime_staging / "runtime-smoke.json"
    _write_json(smoke_path, {
        "contract_version": "goal_binding_gui_actor_sdpa_runtime_smoke_v1",
        **smoke,
        "python_executable_sha256": _sha256(runtime_staging / "Scripts" / "python.exe"),
        "smoke_script_sha256": _sha256(smoke_script), "exit_code": 0,
    })
    _pin_runtime_python_home(root, runtime_staging)
    sizes, hashes = _expected_tree(runtime_staging)
    runtime_manifest = storage.materialize_downloaded_artifact(
        root=root, provider_id=deployed.WINDOWS_SDPA_RUNTIME_PROVIDER,
        repo_id=deployed.WINDOWS_SDPA_RUNTIME_REPOSITORY,
        revision=deployed.WINDOWS_SDPA_RUNTIME_REVISION,
        staging_path=runtime_staging, expected_files=sizes, expected_sha256=hashes,
        post_move_validate=_run_smoke,
    )
    checkpoint_files = checkpoint.get("files")
    model_entries = sorted(
        (
            item
            for item in checkpoint_files or []
            if isinstance(item, dict)
            and str(item.get("relative_path", "")).endswith(".safetensors")
        ),
        key=lambda item: str(item["relative_path"]),
    )
    if not model_entries:
        raise ValueError("checkpoint parent has no model weights")
    runtime_root = root / namespace
    roles = {
        "model": root / model_entries[0]["relative_path"],
        "runtime": runtime_root / "Scripts" / "python.exe",
        "source": runtime_root / "official-source.json",
        "preprocessing": runtime_root / "preprocessing.json",
    }
    report = root / "reports" / "gui-actor-sdpa-deployments" / uuid.uuid4().hex
    report.mkdir(parents=True, exist_ok=False)
    deployment_path = report / "deployment.json"
    deployment = {
        "contract_version": deployed.CONTRACT_VERSION,
        "provider_id": deployed.GUI_ACTOR_PROVIDER, "repo_id": deployed.GUI_ACTOR_REPOSITORY,
        "revision": deployed.GUI_ACTOR_CHECKPOINT_REVISION,
        "checkpoint_parent": _reference(checkpoint_path, root),
        "runtime_parent": _reference(runtime_manifest, root),
        "artifacts": [
            {"role": role, "parent": "checkpoint" if role == "model" else "runtime",
             "relative_path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": _sha256(path)}
            for role, path in roles.items()
        ], "artifact_is_authorization": False,
    }
    _write_json(deployment_path, deployment)
    profile = json.loads(Path(profile_template).read_text(encoding="utf-8"))
    profile["upstream_revision"] = deployed.GUI_ACTOR_CHECKPOINT_REVISION
    profile["artifact_manifest"] = {"status": "verified", **_reference(deployment_path, root)}
    profile["artifacts"] = [
        {"role": role, "relative_path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": _sha256(path)}
        for role, path in roles.items()
    ]
    profile["runtime"]["isolated_runtime_path"] = roles["runtime"].relative_to(root).as_posix()
    profile["runtime"]["sha256"] = _sha256(roles["runtime"])
    profile["preprocessing"]["sha256"] = _sha256(roles["preprocessing"])
    profile["preprocessing"]["source_revision"] = deployed.OFFICIAL_SOURCE_REVISION
    profile_path = report / "profile.json"
    _write_json(profile_path, profile)
    deployed.verify_gui_actor_deployment(profile, root)
    return {"runtime_manifest": runtime_manifest, "deployment_manifest": deployment_path, "profile": profile_path}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--checkpoint-manifest", required=True, type=Path)
    parser.add_argument("--runtime-staging", required=True, type=Path)
    parser.add_argument("--source-checkout", required=True, type=Path)
    parser.add_argument("--profile-template", required=True, type=Path)
    args = parser.parse_args()
    result = prepare_gui_actor_sdpa_runtime(
        root=args.root, checkpoint_manifest=args.checkpoint_manifest,
        runtime_staging=args.runtime_staging, source_checkout=args.source_checkout,
        profile_template=args.profile_template,
    )
    print(json.dumps({name: str(path) for name, path in result.items()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
