from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
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
GATE_PATH = PROJECT_ROOT / "configs" / "benchmarks" / "portfolio_hybrid_v1_1_gate.v2.json"
RELEASE_CODE_REFS = (
    ("benchmark_runtime", "app/learn/hybrid/benchmark_v2_runtime.py"),
    ("benchmark_runner", "scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py"),
)


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
        "contract_version": "portfolio_hybrid_v1_1_provider_manifest_v2_1",
        "benchmark_release_id": RELEASE_ID,
        "provider_corpus_ref": {
            "contract_version": child["contract_version"],
            "relative_path": "provider-corpus.v2.json",
            "file_sha256": file_sha,
            "content_sha256": child["content_sha256"],
            "source_parent_ref": deepcopy(child["source_parent_ref"]),
        },
        "holdout_partition": "holdout",
        "evaluation_projection": {
            "provider_policy": {
                "provider_revisions": {
                    "omni": "PINNED_OMNI_REVISION",
                    "qwen": "PINNED_QWEN_REVISION",
                    "vista": "PINNED_VISTA_REVISION",
                },
                "provider_revisions_sha256": "25ff2b06d0f5c3fa24809b9e3b046994f3a1d3a472fecffd252238aaa0a0e1c4",
                "shared_budget": {
                    "max_provider_calls_per_case": 3,
                    "max_output_tokens_per_case": 2048,
                    "max_wall_time_ms_per_case": 120000,
                },
                "shared_budget_sha256": "ee15ff899063c6e6ce6de50d635886699b2bc4c3962ca441f3ea2cbf23028932",
                "shared_context_policy": {
                    "policy_version": "portfolio-hybrid-shared-uia-ocr-v1",
                    "uia": "same_capture_optional",
                    "ocr": "same_capture_optional",
                },
                "shared_context_policy_sha256": "a02c7efbb9c639d1c45c8e621be5f24a474a85aa34205e46a5b654d84eb1d31e",
            },
            "estimand": {
                "file_sha256": _file_sha(PROFILE_PATH),
                "contract_version": "portfolio_hybrid_v1_1_estimand_v2_1",
                "arms": {
                    "arm_ids": [
                        "qwen_only",
                        "omni_only_discovery",
                        "omni_to_qwen",
                        "omni_to_qwen_vista",
                    ],
                    "release_arm": "omni_to_qwen_vista",
                    "statistical_arm_count": 4,
                },
                "execution_units": {
                    "hybrid_arms": [
                        "omni_only_discovery",
                        "omni_to_qwen",
                        "omni_to_qwen_vista",
                    ],
                    "hybrid_invocation_unit": "screen_group",
                    "hybrid_invocations_per_screen_group": 1,
                    "incumbent_arm": "qwen_only",
                    "incumbent_invocation_unit": "target",
                    "targets_per_screen_group": 5,
                    "call_count_reports": [
                        "unique_invocation_count",
                        "amortized_per_target_count",
                    ],
                },
                "point_metric": {
                    "denominator": "submitted_count",
                    "gain_numerator": "sum(refined_hit-baseline_hit)",
                    "gain": "gain_numerator/submitted_count",
                    "comparison_arithmetic": "exact_rational_no_rounding",
                    "min_vista_submitted_count": 1,
                    "required_gain_numerator": ">0",
                },
            },
            "gate": {
                "file_sha256": _file_sha(GATE_PATH),
                "contract_version": "portfolio_hybrid_v1_1_automatic_gate_v2",
                "automatic_split": "pre_review",
                "holdout_role": "automatic_gate",
                "regression_role": "precondition_only",
                "thresholds": {
                    "min_coverage": "1/5",
                    "min_important_target_correct_coverage_delta": "1/20",
                    "min_semantic_precision_delta": "0/1",
                    "min_vista_submitted_count": 1,
                    "required_vista_gain_numerator": ">0",
                    "wrong_target_count": 0,
                },
            },
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
            "release_code_refs": [
                {
                    "role": role,
                    "relative_path": relative,
                    "file_sha256": _file_sha(PROJECT_ROOT / relative),
                }
                for role, relative in RELEASE_CODE_REFS
            ],
            "profile_refs": [
                {
                    "role": "estimand",
                    "relative_path": PROFILE_PATH.relative_to(PROJECT_ROOT).as_posix(),
                    "file_sha256": _file_sha(PROFILE_PATH),
                }
            ],
        },
        "workload": {
            "contract_version": "provider_sandbox_workload_request_v1",
            "command": "validate_provider_corpus",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
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


def test_opaque_identity_helpers_are_shared_and_do_not_expose_private_markers() -> None:
    from app.learn.hybrid.benchmark_v2_privileged_projector import (
        _opaque_case_id,
        _opaque_screen_group,
        _project_cases,
    )

    screen_id = "synthetic-screen-001"
    target_id = "private-target-001"
    assert _opaque_case_id(screen_id, target_id) == (
        "8d2b4bd05850428863a7bce72d2474157bb9c49c64425db046e4b1a2cdf00c28"
    )
    assert _opaque_screen_group(screen_id) == (
        "b7f2871304bb3d35d494c52cc911dceecee48758d3943a61d64ca853452d0177"
    )

    screens = {
        screen_id: {
            "partition": "holdout",
            "path": "synthetic/provider-safe.png",
            "sha256": "1" * 64,
            "width": 1280,
            "height": 720,
            "layout_id": "synthetic-layout",
            "title": "Synthetic",
            "surface": "native",
            "density": "normal",
            "precision_case": False,
            "source_kind": "privacy_safe_synthetic",
            "source_provenance": "test-only",
        }
    }
    private_markers = [f"private-target-{index:03d}" for index in range(1, 6)]
    parent = {
        "gold_records": [
            {
                "target_id": marker,
                "screen_id": screen_id,
                "partition": "holdout",
                "role": "button",
                "label": f"private-label-{index:03d}",
                "goal": f"Open synthetic item {index}",
                "bbox": [index, index, index + 2, index + 2],
                "acceptable_candidate_ids": [f"candidate-{index}"],
                "acceptable_regions": [[index, index, index + 2, index + 2]],
                "annotator_identity_hash": "2" * 64,
                "reviewer_identity_hash": "3" * 64,
                "acceptable_region_disagreement": False,
                "review_status": "approved",
                "important_target": True,
            }
            for index, marker in enumerate(private_markers, start=1)
        ]
    }
    provider_cases = _project_cases(parent, screens)
    serialized = json.dumps(provider_cases, sort_keys=True)

    assert [case["case_id"] for case in provider_cases] == [
        _opaque_case_id(screen_id, marker) for marker in private_markers
    ]
    assert {case["screen_group"] for case in provider_cases} == {
        _opaque_screen_group(screen_id)
    }
    assert "target_id" not in serialized
    assert all(marker not in serialized for marker in private_markers)
    assert all(f"private-label-{index:03d}" not in serialized for index in range(1, 6))


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
        lambda item: item.update(
            {"contract_version": "portfolio_hybrid_v1_1_provider_manifest_v2"}
        ),
        lambda item: item.pop("holdout_partition"),
        lambda item: item.update({"holdout_partition": "regression"}),
        lambda item: item["evaluation_projection"]["estimand"]["execution_units"].update(
            {"hybrid_invocations_per_screen_group": 5}
        ),
        lambda item: item["evaluation_projection"]["gate"]["thresholds"].update(
            {"min_coverage": "1/4"}
        ),
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
        lambda item: item["workload"].update({"command": "arbitrary_callback"}),
        lambda item: item["workload"].update({"artifact_is_authorization": True}),
        lambda item: item.update({"purpose": "provider"}),
    ):
        changed = deepcopy(value)
        mutation(changed)
        with pytest.raises(ValueError):
            validate_provider_manifest(changed)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda policy: policy.pop("shared_budget"),
        lambda policy: policy.update({"extra": False}),
        lambda policy: policy["provider_revisions"].update({"qwen": "CALLER_CHOSEN"}),
        lambda policy: policy.update({"provider_revisions_sha256": "0" * 64}),
        lambda policy: policy["shared_budget"].update({"max_provider_calls_per_case": 4}),
        lambda policy: policy.update({"shared_budget_sha256": "1" * 64}),
        lambda policy: policy["shared_context_policy"].update({"ocr": "disabled"}),
        lambda policy: policy.update({"shared_context_policy_sha256": "2" * 64}),
    ),
)
def test_provider_manifest_provider_policy_is_closed_and_parent_frozen(
    projected_child: tuple[Path, dict[str, Any], str], mutation: Any
) -> None:
    from app.learn.hybrid.benchmark_v2_provider_corpus import validate_provider_manifest

    _, child, file_sha = projected_child
    changed = _provider_manifest_value(child, file_sha)
    mutation(changed["evaluation_projection"]["provider_policy"])
    with pytest.raises(ValueError):
        validate_provider_manifest(changed)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda projection: projection["provider_policy"]["shared_budget"].update(
            {"max_provider_calls_per_case": 3.0}
        ),
        lambda projection: projection["estimand"]["arms"].update(
            {"statistical_arm_count": 4.0}
        ),
        lambda projection: projection["estimand"]["execution_units"].update(
            {"hybrid_invocations_per_screen_group": True}
        ),
        lambda projection: projection["estimand"]["point_metric"].update(
            {"min_vista_submitted_count": True}
        ),
        lambda projection: projection["gate"]["thresholds"].update(
            {"min_vista_submitted_count": True}
        ),
        lambda projection: projection["gate"]["thresholds"].update(
            {"wrong_target_count": False}
        ),
        lambda projection: projection["estimand"]["execution_units"].update(
            {"hybrid_arms": tuple(projection["estimand"]["execution_units"]["hybrid_arms"])}
        ),
    ),
)
def test_provider_manifest_evaluation_projection_requires_exact_json_types(
    projected_child: tuple[Path, dict[str, Any], str], mutation: Any
) -> None:
    from app.learn.hybrid.benchmark_v2_provider_corpus import validate_provider_manifest

    _, child, file_sha = projected_child
    changed = _provider_manifest_value(child, file_sha)
    mutation(changed["evaluation_projection"])
    with pytest.raises(ValueError):
        validate_provider_manifest(changed)


@pytest.mark.parametrize(
    "leak",
    (
        r"C:\\provider\\manifest.json",
        r"\\\\server\\share\\manifest.json",
        "/var/tmp/manifest.json",
        "file:///tmp/manifest.json",
        "%LOCALAPPDATA%/manifest.json",
        "$HOME/manifest.json",
        "~/manifest.json",
        "private/manifest.json",
        "Gold/manifest.json",
        "app/learn/hybrid/benchmark_scorer_v2.py",
        "host/path/manifest.json",
    ),
)
def test_provider_manifest_evaluation_projection_rejects_path_or_private_leaks(
    projected_child: tuple[Path, dict[str, Any], str], leak: str
) -> None:
    from app.learn.hybrid.benchmark_v2_provider_corpus import validate_provider_manifest

    _, child, file_sha = projected_child
    changed = _provider_manifest_value(child, file_sha)
    changed["evaluation_projection"]["provider_policy"]["provider_revisions"]["qwen"] = leak
    with pytest.raises(ValueError):
        validate_provider_manifest(changed)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda refs, runtime: refs.pop(),
        lambda refs, runtime: refs[1].update({"role": refs[0]["role"]}),
        lambda refs, runtime: refs[1].update({"relative_path": refs[0]["relative_path"]}),
        lambda refs, runtime: refs[0].update({"role": "not-a-role"}),
        lambda refs, runtime: refs[0].update({"file_sha256": "A" * 64}),
        lambda refs, runtime: refs[0].update({"extra": False}),
        lambda refs, runtime: refs[0].update({"relative_path": "../scripts/run.py"}),
        lambda refs, runtime: refs[0].update({"relative_path": r"scripts\\run.py"}),
        lambda refs, runtime: refs[0].update({"relative_path": "C:/scripts/run.py"}),
        lambda refs, runtime: refs[0].update({"relative_path": "//server/share/run.py"}),
        lambda refs, runtime: refs[0].update({"relative_path": "%ROOT%/scripts/run.py"}),
        lambda refs, runtime: refs[0].update({"relative_path": "~/scripts/run.py"}),
        lambda refs, runtime: refs[0].update({"relative_path": "file:///scripts/run.py"}),
        lambda refs, runtime: refs[0].update({"relative_path": "app/private/run.py"}),
        lambda refs, runtime: refs[0].update({"relative_path": "app/Gold/run.py"}),
        lambda refs, runtime: refs[0].update(
            {"relative_path": "app/learn/hybrid/benchmark_scorer_v2.py"}
        ),
        lambda refs, runtime: refs[0].update(
            {"relative_path": runtime["code_refs"][0]["relative_path"]}
        ),
    ),
)
def test_provider_manifest_release_code_refs_fail_closed(
    projected_child: tuple[Path, dict[str, Any], str], mutation: Any
) -> None:
    from app.learn.hybrid.benchmark_v2_provider_corpus import validate_provider_manifest

    _, child, file_sha = projected_child
    changed = _provider_manifest_value(child, file_sha)
    runtime = changed["sealed_runtime"]
    mutation(runtime["release_code_refs"], runtime)
    with pytest.raises(ValueError):
        validate_provider_manifest(changed)


@pytest.mark.parametrize("duplicate", ("role", "relative_path"))
def test_provider_manifest_profile_roles_and_paths_are_unique(
    projected_child: tuple[Path, dict[str, Any], str], duplicate: str
) -> None:
    from app.learn.hybrid.benchmark_v2_provider_corpus import validate_provider_manifest

    _, child, file_sha = projected_child
    changed = _provider_manifest_value(child, file_sha)
    first = changed["sealed_runtime"]["profile_refs"][0]
    second = {
        "role": "gate",
        "relative_path": GATE_PATH.relative_to(PROJECT_ROOT).as_posix(),
        "file_sha256": _file_sha(GATE_PATH),
    }
    second[duplicate] = first[duplicate]
    changed["sealed_runtime"]["profile_refs"].append(second)
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
    assert receipt["contract_version"] == "provider_sandbox_workload_receipt_v1"
    assert receipt["provider_pid"] == receipt["process_id"] == receipt["launcher_process_id"]
    assert receipt["launcher_identity"]["pid"] == receipt["launcher_process_id"]
    assert receipt["launcher_identity"]["create_time_100ns"] > 0
    assert re.fullmatch(
        r"[0-9a-f]{64}", receipt["launcher_identity"]["job_identity_sha256"]
    )
    assert receipt["phase_trace"] == ["boot", "tight", "workload", "complete"]
    assert receipt["filesystem_read_policy_after_tight"] == "deny_all"
    assert receipt["workload_request"] == {
        "contract_version": "provider_sandbox_workload_request_v1",
        "command": "validate_provider_corpus",
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    assert receipt["workload_result"] == {
        "contract_version": "provider_corpus_validation_result_v1",
        "case_count": 120,
        "screen_count": 24,
        "regression_screen_count": 12,
        "holdout_screen_count": 12,
        "child_content_sha256": receipt["child_ref"]["content_sha256"],
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    assert receipt["preflight"] == {
        "contract_version": "provider_sandbox_preflight_receipt_v1",
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    assert receipt["tight_read_file_count"] == 0
    assert len(receipt["preloaded_bytes_sha256_by_role"]) == 30
    child_value = json.loads(files["child_path"].read_text(encoding="utf-8"))
    expected_preloaded = {
        "manifest": {
            "path": str(files["manifest_path"]),
            "sha256": _file_sha(files["manifest_path"]),
            "byte_length": len(files["manifest_path"].read_bytes()),
        },
        "child": {
            "path": str(files["child_path"]),
            "sha256": _file_sha(files["child_path"]),
            "byte_length": len(files["child_path"].read_bytes()),
        },
        **{
            f"code:{role}": {
                "path": relative,
                "sha256": _file_sha(PROJECT_ROOT / relative),
                "byte_length": len((PROJECT_ROOT / relative).read_bytes()),
            }
            for role, relative in PROVIDER_CODE_REFS
        },
        "profile:estimand": {
            "path": PROFILE_PATH.relative_to(PROJECT_ROOT).as_posix(),
            "sha256": _file_sha(PROFILE_PATH),
            "byte_length": len(PROFILE_PATH.read_bytes()),
        },
        **{
            f"screenshot:{case['image']['path']}": {
                "path": case["image"]["path"],
                "sha256": _file_sha(PROJECT_ROOT / case["image"]["path"]),
                "byte_length": len((PROJECT_ROOT / case["image"]["path"]).read_bytes()),
            }
            for case in child_value["cases"]
        },
    }
    assert receipt["preloaded_bytes_sha256_by_role"] == expected_preloaded
    expected_projection = {
        "manifest": deepcopy(expected_preloaded["manifest"]),
        "child": {
            **deepcopy(expected_preloaded["child"]),
            "content_sha256": child_value["content_sha256"],
            "source_parent_ref": deepcopy(child_value["source_parent_ref"]),
        },
        "runtime": {
            "code_refs": [
                {"role": role, **deepcopy(expected_preloaded[f"code:{role}"])}
                for role, _ in PROVIDER_CODE_REFS
            ],
            "profile_refs": [
                {"role": "estimand", **deepcopy(expected_preloaded["profile:estimand"])}
            ],
        },
        "screenshot_refs": [
            deepcopy(expected_preloaded[role])
            for role in sorted(expected_preloaded)
            if role.startswith("screenshot:")
        ],
    }
    assert receipt["sealed_input_projection"] == expected_projection
    expected_projection_sha = hashlib.sha256(
        json.dumps(expected_projection, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert receipt["parent_expected_projection_sha256"] == expected_projection_sha
    assert receipt["job_active_processes_after"] == 0
    assert receipt["job_stable_zero"] is True
    assert receipt["unexpected_inherited_fds"] == []
    assert receipt["denied_controls"] == {
        "builtin_parent": "filesystem_read_denied",
        "pathlib_gold": "filesystem_read_denied",
        "os_open_parent": "filesystem_read_denied",
        "relative_parent": "relative_path_denied",
        "case_alias": "path_alias_denied",
        "reparse_alias": "path_alias_denied",
        "integer_fd": "integer_fd_denied",
        "relative_dir_fd_branch": "relative_path_denied",
        "subprocess_popen": "process_creation_denied",
        "os_system": "process_creation_denied",
        "winapi_create_process": "native_process_surface_denied",
        "os_chdir": "cwd_mutation_denied",
        "dynamic_import": "dynamic_import_denied",
        "ctypes_createfile_import": "dynamic_import_denied",
    }
    assert receipt["artifact_is_authorization"] is False
    assert receipt["execute_binding_enabled"] is False
    canonical_receipt = dict(receipt)
    declared_sha = canonical_receipt.pop("receipt_sha256")
    assert hashlib.sha256(
        json.dumps(
            canonical_receipt,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest() == declared_sha
    from app.learn.hybrid.benchmark_v2_provider_sandbox import (
        _bind_provider_receipt_to_launcher,
    )

    child_claim = deepcopy(receipt)
    for field in (
        "process_id",
        "launcher_process_id",
        "launcher_identity",
        "parent_expected_projection_sha256",
        "job_active_processes_after",
        "job_stable_zero",
        "receipt_sha256",
    ):
        child_claim.pop(field)
    child_claim["provider_pid"] = receipt["launcher_process_id"] + 1
    with pytest.raises(ValueError, match="differs from the observed launcher"):
        _bind_provider_receipt_to_launcher(
            child_claim,
            observed_process_id=receipt["launcher_process_id"],
            launcher_identity=receipt["launcher_identity"],
            job_active_processes_after=0,
            expected_sealed_input_projection=expected_projection,
            expected_projection_sha256=expected_projection_sha,
        )
    for mutation in (
        {"phase_trace": ["boot", "tight", "complete"]},
        {"artifact_is_authorization": True},
        {"job_active_processes_after": 1},
        {
            "provider_pid": receipt["provider_pid"] + 1,
            "process_id": receipt["provider_pid"] + 1,
        },
        {
            "provider_pid": receipt["provider_pid"] + 1,
            "process_id": receipt["provider_pid"] + 1,
            "launcher_process_id": receipt["provider_pid"] + 1,
            "launcher_identity": {
                **receipt["launcher_identity"],
                "pid": receipt["provider_pid"] + 1,
            },
        },
        {
            "launcher_identity": {
                **receipt["launcher_identity"],
                "create_time_100ns": receipt["launcher_identity"]["create_time_100ns"] + 1,
            }
        },
    ):
        from app.learn.hybrid.benchmark_v2_provider_sandbox import (
            validate_provider_workload_receipt,
        )

        changed = deepcopy(receipt)
        changed.update(mutation)
        changed.pop("receipt_sha256")
        changed["receipt_sha256"] = hashlib.sha256(
            json.dumps(changed, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        with pytest.raises(ValueError):
            validate_provider_workload_receipt(
                changed,
                expected_launcher_identity=receipt["launcher_identity"],
                expected_sealed_input_projection=expected_projection,
                expected_projection_sha256=expected_projection_sha,
            )
    for role_mutation in (
        "fake_role",
        "code_sha",
        "profile_sha",
        "screenshot_sha",
        "byte_length",
    ):
        from app.learn.hybrid.benchmark_v2_provider_sandbox import (
            validate_provider_workload_receipt,
        )

        changed = deepcopy(receipt)
        preloaded = changed["preloaded_bytes_sha256_by_role"]
        if role_mutation == "fake_role":
            removed = preloaded.pop("code:contracts")
            preloaded["code:fake"] = removed
        elif role_mutation == "code_sha":
            preloaded["code:contracts"]["sha256"] = "0" * 64
        elif role_mutation == "profile_sha":
            preloaded["profile:estimand"]["sha256"] = "0" * 64
        elif role_mutation == "screenshot_sha":
            role = next(key for key in preloaded if key.startswith("screenshot:"))
            preloaded[role]["sha256"] = "0" * 64
        else:
            preloaded["code:bootstrap"]["byte_length"] += 1
        changed.pop("receipt_sha256")
        changed["receipt_sha256"] = hashlib.sha256(
            json.dumps(changed, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        with pytest.raises(ValueError):
            validate_provider_workload_receipt(
                changed,
                expected_launcher_identity=receipt["launcher_identity"],
                expected_sealed_input_projection=expected_projection,
                expected_projection_sha256=expected_projection_sha,
            )
    for synchronized_mutation in (
        "code",
        "profile",
        "screenshot_sha_length",
        "screenshot_path",
    ):
        from app.learn.hybrid.benchmark_v2_provider_sandbox import (
            validate_provider_workload_receipt,
        )

        changed = deepcopy(receipt)
        projection = changed["sealed_input_projection"]
        preload = changed["preloaded_bytes_sha256_by_role"]
        if synchronized_mutation == "code":
            projection["runtime"]["code_refs"][1]["sha256"] = "1" * 64
            preload["code:contracts"]["sha256"] = "1" * 64
        elif synchronized_mutation == "profile":
            projection["runtime"]["profile_refs"][0]["sha256"] = "2" * 64
            preload["profile:estimand"]["sha256"] = "2" * 64
        elif synchronized_mutation == "screenshot_sha_length":
            screen = projection["screenshot_refs"][0]
            role = f"screenshot:{screen['path']}"
            screen["sha256"] = "3" * 64
            screen["byte_length"] += 1
            preload[role]["sha256"] = "3" * 64
            preload[role]["byte_length"] += 1
        else:
            screen = projection["screenshot_refs"][0]
            old_role = f"screenshot:{screen['path']}"
            replacement_path = screen["path"].rsplit("/", 1)[0] + "/case-999.png"
            screen["path"] = replacement_path
            replacement = preload.pop(old_role)
            replacement["path"] = replacement_path
            preload[f"screenshot:{replacement_path}"] = replacement
        changed.pop("receipt_sha256")
        changed["receipt_sha256"] = hashlib.sha256(
            json.dumps(changed, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        with pytest.raises(ValueError):
            validate_provider_workload_receipt(
                changed,
                expected_launcher_identity=receipt["launcher_identity"],
                expected_sealed_input_projection=expected_projection,
                expected_projection_sha256=expected_projection_sha,
            )
    assert not (files["operation"] / "provider-process-escape.txt").exists()
    assert not (files["operation"] / "provider-system-escape.txt").exists()


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
    with pytest.raises(ValueError, match="failed closed|parent expected"):
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
    assert receipt["contract_version"] == "provider_sandbox_workload_receipt_v1"
    assert receipt["phase_trace"] == ["boot", "tight", "workload", "complete"]


def test_valid_nonstandard_fd_is_denied_by_policy_reason(tmp_path: Path) -> None:
    from app.learn.hybrid.benchmark_v2_provider_sandbox import (
        ProviderSandboxDenied,
        _AuditState,
    )

    source = tmp_path / "readable.bin"
    source.write_bytes(b"sealed")
    descriptor = os.open(source, os.O_RDONLY)
    try:
        os.fstat(descriptor)
        state = _AuditState(boot_reads=(source.resolve(),))
        with pytest.raises(ProviderSandboxDenied) as denied:
            state.audit("open", (descriptor, None, os.O_RDONLY))
        assert denied.value.code == "integer_fd_denied"
    finally:
        os.close(descriptor)


def test_denial_probe_rejects_non_policy_exceptions() -> None:
    from app.learn.hybrid.benchmark_v2_provider_sandbox import _expect_denied

    observed: dict[str, str] = {}
    with pytest.raises(OSError, match="not policy"):
        _expect_denied(
            "generic_error",
            lambda: (_ for _ in ()).throw(OSError("not policy")),
            observed,
        )
    assert observed == {}


def test_preloaded_child_bytes_ignore_same_size_replace_and_restore(
    projected_child: tuple[Path, dict[str, Any], str],
) -> None:
    from app.learn.hybrid.benchmark_v2_provider_corpus import validate_preloaded_provider_corpus

    path, expected, file_sha = projected_child
    preloaded = path.read_bytes()
    mutated = bytearray(preloaded)
    position = preloaded.index(b"portfolio_hybrid_v1_1_provider_corpus_v2")
    mutated[position] = ord("x")
    assert len(mutated) == len(preloaded)
    path.write_bytes(mutated)
    try:
        validated = validate_preloaded_provider_corpus(
            raw=preloaded,
            expected_sha256=file_sha,
        )
        assert validated == expected
    finally:
        path.write_bytes(preloaded)
    assert _file_sha(path) == file_sha


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
