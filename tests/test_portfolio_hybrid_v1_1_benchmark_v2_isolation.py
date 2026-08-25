from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import msvcrt
from typing import Any

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "portfolio_hybrid_v1_1"
PARENT_PATH = FIXTURE_ROOT / "corpus-manifest.v1.json"
TEMPLATE_PATH = FIXTURE_ROOT / "benchmark-v2-manifest.template.json"
PROJECTOR = PROJECT_ROOT / "scripts" / "project_portfolio_hybrid_v1_1_provider_corpus_v2.py"
PARENT_SHA256 = "8503010496a426893456e903b9d768f2a281ef0509f11230d312b073c0760757"
RELEASE_ID = "portfolio_hybrid_v1_1_benchmark_v2_release_1"
PROVIDER_CODE_REFS = (
    ("bootstrap", "app/learn/hybrid/benchmark_v2_provider_sandbox.py"),
    ("contracts", "app/learn/hybrid/benchmark_v2_contracts.py"),
    ("corpus_loader", "app/learn/hybrid/benchmark_v2_provider_corpus.py"),
)
PROFILE_PATH = PROJECT_ROOT / "configs" / "benchmarks" / "portfolio_hybrid_v1_1_estimand.v2.json"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8") + b"\n"


def _content_sha(value: dict[str, Any]) -> str:
    unhashed = {key: item for key, item in value.items() if key != "content_sha256"}
    compact = json.dumps(
        unhashed,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(compact).hexdigest()


def _write_child(path: Path, value: dict[str, Any]) -> str:
    value["content_sha256"] = _content_sha(value)
    raw = _canonical_bytes(value)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _provider_manifest_value(child: dict[str, Any], file_sha: str) -> dict[str, Any]:
    return {
        "contract_version": "portfolio_hybrid_v1_1_provider_manifest_v2",
        "benchmark_release_id": RELEASE_ID,
        "provider_corpus_ref": {
            "contract_version": child["contract_version"],
            "relative_path": "provider-corpus.v2.json",
            "file_sha256": file_sha,
            "content_sha256": child["content_sha256"],
            "source_parent_ref": deepcopy(child["source_parent_ref"]),
        },
        "sealed_runtime": {
            "code_refs": [
                {
                    "role": role,
                    "relative_path": relative,
                    "file_sha256": _file_sha(PROJECT_ROOT / relative),
                }
                for role, relative in PROVIDER_CODE_REFS
            ],
            "profile_refs": [
                {
                    "role": "estimand",
                    "relative_path": PROFILE_PATH.relative_to(PROJECT_ROOT).as_posix(),
                    "file_sha256": _file_sha(PROFILE_PATH),
                }
            ],
        },
        "arm_order": ["qwen_only", "omni_only_discovery", "omni_to_qwen", "omni_to_qwen_vista"],
        "safety": deepcopy(child["safety"]),
    }


@pytest.fixture
def provider_bootstrap_files(
    tmp_path: Path,
    projected_child: tuple[Path, dict[str, Any], str],
) -> dict[str, Any]:
    source_path, child, file_sha = projected_child
    child_path = tmp_path / "provider-corpus.v2.json"
    child_path.write_bytes(source_path.read_bytes())
    manifest_path = tmp_path / "benchmark-v2-provider-manifest.json"
    manifest = _provider_manifest_value(child, file_sha)
    manifest_path.write_bytes(_canonical_bytes(manifest))
    roots = {name: tmp_path / name for name in ("operation", "output", "ledger")}
    for root in roots.values():
        root.mkdir()
    return {
        "manifest_path": manifest_path,
        "manifest_sha": _file_sha(manifest_path),
        "child_path": child_path,
        "child_sha": file_sha,
        **roots,
    }


def _run_process(argv: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> tuple[int, str, str, int]:
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    pid = process.pid
    try:
        stdout, stderr = process.communicate(timeout=30)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        for pipe in (process.stdout, process.stderr):
            if pipe is not None:
                pipe.close()
    return process.returncode, stdout, stderr, pid


@pytest.fixture(scope="module")
def projected_child(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any], str]:
    directory = tmp_path_factory.mktemp("provider-child")
    output = directory / "provider-corpus.v2.json"
    code, stdout, stderr, pid = _run_process(
        [
            sys.executable,
            str(PROJECTOR),
            "--parent-manifest",
            str(PARENT_PATH),
            "--output",
            str(output),
        ],
        cwd=PROJECT_ROOT,
    )
    assert code == 0, stderr
    receipt = json.loads(stdout)
    assert receipt["process_id"] != os.getpid()
    assert pid != os.getpid()
    assert receipt["output_path"] == str(output.resolve())
    raw = output.read_bytes()
    assert receipt["file_sha256"] == hashlib.sha256(raw).hexdigest()
    value = json.loads(raw.decode("utf-8"))
    return output, value, receipt["file_sha256"]


def test_projector_process_emits_closed_opaque_provider_child(
    projected_child: tuple[Path, dict[str, Any], str],
) -> None:
    from app.learn.hybrid.benchmark_v2_provider_corpus import load_provider_corpus

    path, raw_value, file_sha = projected_child
    value = load_provider_corpus(child_path=path, expected_sha256=file_sha)
    assert value == raw_value
    assert value["contract_version"] == "portfolio_hybrid_v1_1_provider_corpus_v2"
    assert value["benchmark_release_id"] == RELEASE_ID
    assert value["source_parent_ref"] == {
        "contract_version": "portfolio_hybrid_v1_1_corpus_parent_ref_v1",
        "artifact_id": "portfolio-hybrid-v1-1-corpus-parent",
        "file_sha256": PARENT_SHA256,
        "content_sha256": "bc06e007b4518bb716fdaff81ae7dd147227d09a10044d90a6b4577088ecba93",
    }
    assert value["safety"] == {
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "display_only": True,
    }
    cases = value["cases"]
    assert len(cases) == 120
    assert len({case["case_id"] for case in cases}) == 120
    groups = {case["screen_group"] for case in cases}
    assert len(groups) == 24
    assert {sum(case["screen_group"] == group for case in cases) for group in groups} == {5}
    by_partition = {
        partition: {case["screen_group"] for case in cases if case["partition"] == partition}
        for partition in ("regression", "holdout")
    }
    assert {partition: len(groups) for partition, groups in by_partition.items()} == {
        "regression": 12,
        "holdout": 12,
    }
    assert all(case["image"]["width"] == 1280 for case in cases)
    assert all(case["image"]["height"] == 720 for case in cases)
    assert len({case["image"]["sha256"] for case in cases}) == 24
    assert len({case["image"]["path"] for case in cases}) == 24
    assert all((PROJECT_ROOT / case["image"]["path"]).is_file() for case in cases)
    assert all(case["goal"].strip() for case in cases)


def test_provider_child_recursively_excludes_private_gold_and_action_authority(
    projected_child: tuple[Path, dict[str, Any], str],
) -> None:
    _, value, _ = projected_child
    allowed_safety = {"artifact_is_authorization", "execute_binding_enabled", "display_only"}
    forbidden_key_parts = (
        "gold",
        "private",
        "target_id",
        "screen_id",
        "acceptable",
        "bbox",
        "reviewer",
        "annotator",
        "scorer",
        "coordinate",
        "click",
        "point",
        "action",
    )
    forbidden_paths = (
        "corpus-manifest.v1.json",
        "gold.v1.json",
        "benchmark_scorer",
    )

    def walk(item: object) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                lowered = key.casefold()
                if key not in allowed_safety:
                    assert not any(token in lowered for token in forbidden_key_parts), key
                walk(nested)
        elif isinstance(item, list):
            for nested in item:
                walk(nested)
        elif isinstance(item, str):
            lowered = item.casefold().replace("\\", "/")
            assert not any(token in lowered for token in forbidden_paths), item

    walk(value)
    assert "purpose" not in json.dumps(value, ensure_ascii=False).casefold()


def test_projector_is_byte_deterministic_across_distinct_processes(
    tmp_path: Path,
    projected_child: tuple[Path, dict[str, Any], str],
) -> None:
    first_path, _, first_sha = projected_child
    second_path = tmp_path / "provider-corpus.v2.json"
    code, stdout, stderr, _ = _run_process(
        [
            sys.executable,
            str(PROJECTOR),
            "--parent-manifest",
            str(PARENT_PATH),
            "--output",
            str(second_path),
        ],
        cwd=PROJECT_ROOT,
    )
    assert code == 0, stderr
    receipt = json.loads(stdout)
    assert receipt["process_id"] != os.getpid()
    assert receipt["file_sha256"] == first_sha
    assert second_path.read_bytes() == first_path.read_bytes()


def test_provider_loader_rejects_wrong_raw_file_sha(
    projected_child: tuple[Path, dict[str, Any], str],
) -> None:
    from app.learn.hybrid.benchmark_v2_provider_corpus import load_provider_corpus

    path, _, _ = projected_child
    with pytest.raises(ValueError, match="file SHA mismatch"):
        load_provider_corpus(child_path=path, expected_sha256="0" * 64)


def test_parent_ref_can_only_be_built_from_the_verified_parent_content_sha() -> None:
    from app.learn.hybrid.benchmark_v2_privileged_projector import (
        _parent_ref_from_verified_content_sha,
    )

    with pytest.raises(ValueError, match="frozen parent content SHA"):
        _parent_ref_from_verified_content_sha("0" * 64)
    ref = _parent_ref_from_verified_content_sha(
        "bc06e007b4518bb716fdaff81ae7dd147227d09a10044d90a6b4577088ecba93"
    )
    assert ref["content_sha256"] == (
        "bc06e007b4518bb716fdaff81ae7dd147227d09a10044d90a6b4577088ecba93"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "nested_private_key",
        "nested_parent_path",
        "case_count",
        "screen_count",
        "partition_group_count",
        "same_parent_sha_wrong_lineage",
    ],
)
def test_provider_loader_fails_closed_on_mutated_child(
    tmp_path: Path,
    projected_child: tuple[Path, dict[str, Any], str],
    mutation: str,
) -> None:
    from app.learn.hybrid.benchmark_v2_provider_corpus import load_provider_corpus

    _, source, _ = projected_child
    value = deepcopy(source)
    if mutation == "nested_private_key":
        value["cases"][0]["layout"]["metadata"] = {"gold_answer": "hidden"}
    elif mutation == "nested_parent_path":
        value["cases"][0]["layout"]["metadata"] = {
            "note": "tests/fixtures/portfolio_hybrid_v1_1/corpus-manifest.v1.json"
        }
    elif mutation == "case_count":
        value["cases"].pop()
    elif mutation == "screen_count":
        replacement = value["cases"][0]["screen_group"]
        old = value["cases"][-1]["screen_group"]
        for case in value["cases"]:
            if case["screen_group"] == old:
                case["screen_group"] = replacement
    elif mutation == "partition_group_count":
        group = next(
            case["screen_group"] for case in value["cases"] if case["partition"] == "holdout"
        )
        for case in value["cases"]:
            if case["screen_group"] == group:
                case["partition"] = "regression"
    else:
        value["source_parent_ref"]["artifact_id"] = "same-sha-wrong-parent"
    path = tmp_path / f"{mutation}.json"
    file_sha = _write_child(path, value)
    with pytest.raises(ValueError):
        load_provider_corpus(child_path=path, expected_sha256=file_sha)


def test_provider_manifest_is_closed_and_parent_bound(
    projected_child: tuple[Path, dict[str, Any], str],
) -> None:
    from app.learn.hybrid.benchmark_v2_provider_corpus import validate_provider_manifest

    _, child, file_sha = projected_child
    value = _provider_manifest_value(child, file_sha)
    assert validate_provider_manifest(value) == value
    for mutation in (
        lambda item: item["provider_corpus_ref"]["source_parent_ref"].update(
            {"artifact_id": "wrong-lineage"}
        ),
        lambda item: item["provider_corpus_ref"].update({"gold_path": str(PARENT_PATH)}),
        lambda item: item["provider_corpus_ref"].update(
            {"relative_path": "tests/fixtures/portfolio_hybrid_v1_1/corpus-manifest.v1.json"}
        ),
        lambda item: item["sealed_runtime"]["code_refs"][0].update(
            {"relative_path": "app/learn/hybrid/benchmark_scorer_v1.py"}
        ),
        lambda item: item.update({"purpose": "provider"}),
    ):
        changed = deepcopy(value)
        mutation(changed)
        with pytest.raises(ValueError):
            validate_provider_manifest(changed)


def test_provider_import_graph_excludes_privileged_and_private_scorer() -> None:
    provider_paths = (
        PROJECT_ROOT / "app" / "learn" / "hybrid" / "benchmark_v2_contracts.py",
        PROJECT_ROOT / "app" / "learn" / "hybrid" / "benchmark_v2_provider_corpus.py",
        PROJECT_ROOT / "app" / "learn" / "hybrid" / "benchmark_v2_provider_sandbox.py",
    )
    forbidden = {
        "app.learn.hybrid.benchmark_v2_privileged_projector",
        "app.learn.hybrid.benchmark_scorer_v1",
        "scripts.seal_portfolio_hybrid_v1_1_corpus",
    }
    for path in provider_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        assert not any(
            imported == blocked or imported.startswith(blocked + ".")
            for imported in imports
            for blocked in forbidden
        ), (path, imports & forbidden)


def test_process_projection_is_closed_and_rejects_all_path_aliases(
    tmp_path: Path,
    provider_bootstrap_files: dict[str, Any],
) -> None:
    from app.learn.hybrid.benchmark_v2_provider_sandbox import (
        build_provider_bootstrap_command,
        minimal_provider_environment,
        validate_provider_process_projection,
    )

    files = provider_bootstrap_files
    argv = build_provider_bootstrap_command(
        provider_manifest_path=files["manifest_path"],
        expected_manifest_sha256=files["manifest_sha"],
        provider_child_path=files["child_path"],
        expected_child_sha256=files["child_sha"],
        operation_root=files["operation"],
        output_root=files["output"],
        ledger_root=files["ledger"],
    )
    safe = {
        "argv": argv,
        "env": minimal_provider_environment(),
        "cwd": files["operation"],
        "stdin": b"",
        "forbidden_roots": (FIXTURE_ROOT, PARENT_PATH),
    }
    validate_provider_process_projection(**safe)
    manifest_index = argv.index("--provider-manifest") + 1
    mutations = []
    relative_argv = list(argv)
    relative_argv[manifest_index] = os.path.relpath(files["manifest_path"], files["operation"])
    mutations.append({"argv": tuple(relative_argv)})
    case_argv = list(argv)
    case_argv[manifest_index] = str(files["manifest_path"]).upper()
    mutations.append({"argv": tuple(case_argv)})
    mutations.extend(
        (
            {"argv": (*argv, "--unknown", "value")},
            {"env": {**safe["env"], "PROVIDER_ALIAS": str(PARENT_PATH)}},
            {"cwd": tmp_path},
            {"stdin": b"private-input"},
        )
    )
    for mutation in mutations:
        value = dict(safe)
        value.update(mutation)
        with pytest.raises(ValueError):
            validate_provider_process_projection(**value)


def _create_directory_junction(alias: Path, target: Path) -> None:
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(alias), str(target)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        close_fds=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)


def test_production_bootstrap_owns_load_tighten_and_open_audit(
    provider_bootstrap_files: dict[str, Any],
) -> None:
    from app.learn.hybrid.benchmark_v2_provider_sandbox import spawn_provider_bootstrap

    files = provider_bootstrap_files
    alias = files["operation"] / "provider-boundary-parent-alias"
    _create_directory_junction(alias, FIXTURE_ROOT)
    private_stream = PARENT_PATH.open("rb")
    private_handle = msvcrt.get_osfhandle(private_stream.fileno())
    os.set_handle_inheritable(private_handle, True)
    try:
        receipt = spawn_provider_bootstrap(
            provider_manifest_path=files["manifest_path"],
            expected_manifest_sha256=files["manifest_sha"],
            provider_child_path=files["child_path"],
            expected_child_sha256=files["child_sha"],
            operation_root=files["operation"],
            output_root=files["output"],
            ledger_root=files["ledger"],
        )
    finally:
        os.set_handle_inheritable(private_handle, False)
        private_stream.close()
        if alias.exists():
            os.rmdir(alias)
    assert receipt["contract_version"] == "portfolio_hybrid_v1_1_provider_bootstrap_receipt_v1"
    assert receipt["boot_policy_installed"] is True
    assert receipt["tight_policy_installed"] is True
    assert receipt["child_case_count"] == 120
    assert receipt["screen_count"] == 24
    assert receipt["sealed_code_count"] == 3
    assert receipt["sealed_profile_count"] == 1
    assert receipt["unexpected_inherited_fds"] == []
    assert set(receipt["denied_open_probes"]) == {
        "builtin_parent",
        "pathlib_gold",
        "os_open_parent",
        "relative_parent",
        "case_alias",
        "reparse_alias",
        "integer_fd",
        "dir_fd",
    }
    assert receipt["allowed_read_count"] == 30
    assert receipt["allowed_write_roots"] == ["operation", "output", "ledger"]
    for root in (files["operation"], files["output"], files["ledger"]):
        assert (root / "provider-bootstrap-write-probe.json").read_text(encoding="utf-8") == "{}"


def test_parent_spawner_rejects_reparse_alias_before_launch(
    tmp_path: Path,
    provider_bootstrap_files: dict[str, Any],
) -> None:
    from app.learn.hybrid.benchmark_v2_provider_sandbox import spawn_provider_bootstrap

    files = provider_bootstrap_files
    alias_root = tmp_path / "provider-child-alias"
    _create_directory_junction(alias_root, files["child_path"].parent)
    try:
        with pytest.raises(ValueError, match="reparse|canonical"):
            spawn_provider_bootstrap(
                provider_manifest_path=files["manifest_path"],
                expected_manifest_sha256=files["manifest_sha"],
                provider_child_path=alias_root / files["child_path"].name,
                expected_child_sha256=files["child_sha"],
                operation_root=files["operation"],
                output_root=files["output"],
                ledger_root=files["ledger"],
            )
    finally:
        if alias_root.exists():
            os.rmdir(alias_root)


def test_bootstrap_failure_closes_process_and_allows_clean_retry(
    provider_bootstrap_files: dict[str, Any],
) -> None:
    from app.learn.hybrid.benchmark_v2_provider_sandbox import spawn_provider_bootstrap

    files = provider_bootstrap_files
    original = files["manifest_path"].read_bytes()
    mutated = json.loads(original.decode("utf-8"))
    mutated["sealed_runtime"]["code_refs"][0]["file_sha256"] = "0" * 64
    files["manifest_path"].write_bytes(_canonical_bytes(mutated))
    with pytest.raises(ValueError, match="failed closed"):
        spawn_provider_bootstrap(
            provider_manifest_path=files["manifest_path"],
            expected_manifest_sha256=_file_sha(files["manifest_path"]),
            provider_child_path=files["child_path"],
            expected_child_sha256=files["child_sha"],
            operation_root=files["operation"],
            output_root=files["output"],
            ledger_root=files["ledger"],
        )
    files["manifest_path"].write_bytes(original)
    receipt = spawn_provider_bootstrap(
        provider_manifest_path=files["manifest_path"],
        expected_manifest_sha256=_file_sha(files["manifest_path"]),
        provider_child_path=files["child_path"],
        expected_child_sha256=files["child_sha"],
        operation_root=files["operation"],
        output_root=files["output"],
        ledger_root=files["ledger"],
    )
    assert receipt["tight_policy_installed"] is True


def test_provider_file_policy_rejects_private_fixture_even_if_declared(tmp_path: Path) -> None:
    from app.learn.hybrid.benchmark_v2_provider_sandbox import install_provider_file_policy

    write_root = tmp_path / "output"
    write_root.mkdir()
    for private_path in (PARENT_PATH, FIXTURE_ROOT / "gold.v1.json", TEMPLATE_PATH):
        with pytest.raises(ValueError, match="private fixture"):
            install_provider_file_policy(
                read_files=(private_path,),
                read_roots=(),
                write_roots=(write_root,),
            )
    with pytest.raises(ValueError, match="exact files"):
        install_provider_file_policy(
            read_files=(PROJECT_ROOT / "app" / "learn" / "hybrid" / "benchmark_v2_provider_corpus.py",),
            read_roots=(PROJECT_ROOT,),
            write_roots=(write_root,),
        )
    with pytest.raises(ValueError, match="private fixture or scorer"):
        install_provider_file_policy(
            read_files=(PROJECT_ROOT / "app" / "learn" / "hybrid" / "benchmark_scorer_v1.py",),
            read_roots=(),
            write_roots=(write_root,),
        )


def test_privileged_template_is_fixed_non_authorizing_and_not_a_provider_input() -> None:
    value = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    assert value == {
        "contract_version": "portfolio_hybrid_v1_1_benchmark_v2_manifest_template_v1",
        "benchmark_release_id": RELEASE_ID,
        "corpus_parent": {
            "contract_version": "portfolio_hybrid_v1_1_corpus_manifest_v1",
            "relative_path": "tests/fixtures/portfolio_hybrid_v1_1/corpus-manifest.v1.json",
            "file_sha256": PARENT_SHA256,
        },
        "provider_corpus_output": "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/provider-corpus.candidate.json",
        "safety": {
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "display_only": True,
        },
    }
