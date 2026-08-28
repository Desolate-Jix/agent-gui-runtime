from __future__ import annotations

import ast
from copy import deepcopy
import importlib
import inspect
import json
import os
from pathlib import Path

import pytest


MODULE_NAME = "scripts.assemble_portfolio_hybrid_v1_1_benchmark_v2_report"


def _module():
    return importlib.import_module(MODULE_NAME)


def _synthetic_snapshot(module, tmp_path: Path):
    production_paths = ("production/a.py", "production/b.py")
    test_paths = ("tests/test_a.py",)
    for relative_path, payload in (
        (production_paths[0], b"alpha\n"),
        (production_paths[1], b"beta\n"),
        (test_paths[0], b"test\n"),
    ):
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    snapshot = module.capture_source_snapshot(
        root=tmp_path,
        production_paths=production_paths,
        test_paths=test_paths,
    )
    return production_paths, test_paths, snapshot


def _synthetic_evidence(module, snapshot):
    result_receipts = {}
    result_refs = {}
    review_receipts = {}
    review_refs = {}
    for suite_id in module.DEPENDENCY_ORDER:
        result = module.build_dependency_result_receipt(
            suite_id=suite_id,
            pytest_argv=module.FROZEN_PYTEST_ARGV_BY_SUITE_ID[suite_id],
            pre_source_snapshot=snapshot,
            post_source_snapshot=snapshot,
            exit_code=0,
            collected_count=3,
            failed_count=0,
        )
        result_ref = module.artifact_ref(result)
        review = module.build_dependency_review_receipt(
            suite_id=suite_id,
            result_receipt=result,
            result_receipt_ref=result_ref,
            review_name=module.REVIEW_NAME_BY_SUITE_ID[suite_id],
            review_file_sha256="a" * 64,
            reviewer_identity_sha256="b" * 64,
            reviewer_independent=True,
            unresolved_findings={"critical": 0, "important": 0},
        )
        result_receipts[suite_id] = result
        result_refs[suite_id] = result_ref
        review_receipts[suite_id] = review
        review_refs[suite_id] = module.artifact_ref(review)
    return result_receipts, result_refs, review_receipts, review_refs


def _configured_plugin(module, tmp_path: Path, *, suite_id: str, addopts=()):
    output = tmp_path / "receipt.json"

    class Invocation:
        args = (
            "-p",
            module.PYTEST_PLUGIN_NAME,
            module.PYTEST_SUITE_OPTION,
            suite_id,
            module.PYTEST_RECEIPT_OPTION,
            str(output),
            *module.FROZEN_PYTEST_ARGV_BY_SUITE_ID[suite_id][1:],
        )

    class PluginManager:
        @staticmethod
        def list_plugin_distinfo():
            return []

        @staticmethod
        def get_plugins():
            return set()

    class Config:
        invocation_params = Invocation()
        pluginmanager = PluginManager()

        @staticmethod
        def getoption(name):
            return {
                module.PYTEST_SUITE_OPTION: suite_id,
                module.PYTEST_RECEIPT_OPTION: str(output),
            }.get(name)

        @staticmethod
        def getini(name):
            return list(addopts) if name == "addopts" else []

    config = Config()
    module.pytest_configure(config)
    return config, output


@pytest.mark.parametrize("mutation", ["missing", "extra", "malformed"])
def test_source_snapshot_validation_rejects_missing_extra_or_malformed_maps(
    tmp_path: Path, mutation: str
) -> None:
    module = _module()
    production_paths, test_paths, snapshot = _synthetic_snapshot(module, tmp_path)
    changed = deepcopy(snapshot)
    if mutation == "missing":
        changed["production_source_sha256_by_path"].pop(production_paths[0])
    elif mutation == "extra":
        changed["test_source_sha256_by_path"]["tests/extra.py"] = "0" * 64
    else:
        changed["production_source_sha256_by_path"][production_paths[0]] = "BAD"

    with pytest.raises(ValueError, match="source snapshot"):
        module.validate_source_snapshot(
            changed,
            production_paths=production_paths,
            test_paths=test_paths,
        )


def test_dependency_result_receipt_fails_on_pre_post_source_drift(
    tmp_path: Path,
) -> None:
    module = _module()
    production_paths, test_paths, pre_snapshot = _synthetic_snapshot(module, tmp_path)
    (tmp_path / production_paths[0]).write_bytes(b"changed\n")
    post_snapshot = module.capture_source_snapshot(
        root=tmp_path,
        production_paths=production_paths,
        test_paths=test_paths,
    )

    receipt = module.build_dependency_result_receipt(
        suite_id="task05_worker_binding_v1",
        pytest_argv=module.FROZEN_PYTEST_ARGV_BY_SUITE_ID[
            "task05_worker_binding_v1"
        ],
        pre_source_snapshot=pre_snapshot,
        post_source_snapshot=post_snapshot,
        exit_code=0,
        collected_count=1,
        failed_count=0,
    )

    assert receipt["source_snapshot_sha256"] == module.source_snapshot_sha256(
        pre_snapshot,
        production_paths=production_paths,
        test_paths=test_paths,
    )
    assert receipt["status"] == "FAIL"


@pytest.mark.parametrize("mutation", ["missing", "extra", "malformed"])
def test_dependency_result_receipt_rejects_source_snapshot_digest_field_drift(
    tmp_path: Path, mutation: str
) -> None:
    module = _module()
    _, _, snapshot = _synthetic_snapshot(module, tmp_path)
    receipt = module.build_dependency_result_receipt(
        suite_id="task05_worker_binding_v1",
        pytest_argv=module.FROZEN_PYTEST_ARGV_BY_SUITE_ID[
            "task05_worker_binding_v1"
        ],
        pre_source_snapshot=snapshot,
        post_source_snapshot=snapshot,
        exit_code=0,
        collected_count=1,
        failed_count=0,
    )
    changed = deepcopy(receipt)
    if mutation == "missing":
        changed.pop("source_snapshot_sha256")
    elif mutation == "extra":
        changed["post_source_snapshot_sha256"] = receipt["source_snapshot_sha256"]
    else:
        changed["source_snapshot_sha256"] = "BAD"

    with pytest.raises(ValueError, match="dependency result receipt"):
        module.validate_dependency_result_receipt(changed)


def test_manifest_rejects_result_receipt_snapshot_that_differs_from_current_maps(
    tmp_path: Path,
) -> None:
    module = _module()
    production_paths, test_paths, snapshot = _synthetic_snapshot(module, tmp_path)
    evidence = _synthetic_evidence(module, snapshot)
    (tmp_path / production_paths[0]).write_bytes(b"current drift\n")
    current = module.capture_source_snapshot(
        root=tmp_path,
        production_paths=production_paths,
        test_paths=test_paths,
    )

    with pytest.raises(ValueError, match="current source snapshot"):
        module._build_synthetic_dependency_manifest_for_test(
            benchmark_release_id="synthetic-release",
            result_receipts_by_suite=evidence[0],
            result_receipt_refs_by_suite=evidence[1],
            review_receipts_by_suite=evidence[2],
            review_receipt_refs_by_suite=evidence[3],
            source_snapshot=current,
            production_paths=production_paths,
            test_paths=test_paths,
        )


def test_manifest_rejects_mixed_dependency_receipt_snapshots(tmp_path: Path) -> None:
    module = _module()
    production_paths, test_paths, snapshot = _synthetic_snapshot(module, tmp_path)
    result_receipts, result_refs, review_receipts, review_refs = (
        _synthetic_evidence(module, snapshot)
    )
    mixed_suite = module.DEPENDENCY_ORDER[-1]
    mixed_result = deepcopy(result_receipts[mixed_suite])
    mixed_result["source_snapshot_sha256"] = "c" * 64
    mixed_result["content_sha256"] = module.content_sha256(mixed_result)
    result_receipts[mixed_suite] = mixed_result
    result_refs[mixed_suite] = module.artifact_ref(mixed_result)
    mixed_review = deepcopy(review_receipts[mixed_suite])
    mixed_review["result_receipt_ref"] = result_refs[mixed_suite]
    mixed_review["content_sha256"] = module.content_sha256(mixed_review)
    review_receipts[mixed_suite] = mixed_review
    review_refs[mixed_suite] = module.artifact_ref(mixed_review)

    with pytest.raises(ValueError, match="current source snapshot"):
        module._build_synthetic_dependency_manifest_for_test(
            benchmark_release_id="synthetic-release",
            result_receipts_by_suite=result_receipts,
            result_receipt_refs_by_suite=result_refs,
            review_receipts_by_suite=review_receipts,
            review_receipt_refs_by_suite=review_refs,
            source_snapshot=snapshot,
            production_paths=production_paths,
            test_paths=test_paths,
        )


def test_final_seal_validation_rejects_current_source_mismatch(tmp_path: Path) -> None:
    module = _module()
    production_paths, test_paths, snapshot = _synthetic_snapshot(module, tmp_path)
    evidence = _synthetic_evidence(module, snapshot)
    manifest = module._build_synthetic_dependency_manifest_for_test(
        benchmark_release_id="synthetic-release",
        result_receipts_by_suite=evidence[0],
        result_receipt_refs_by_suite=evidence[1],
        review_receipts_by_suite=evidence[2],
        review_receipt_refs_by_suite=evidence[3],
        source_snapshot=snapshot,
        production_paths=production_paths,
        test_paths=test_paths,
    )
    task12 = module.build_dependency_result_receipt(
        suite_id="task12_release_gate_v1",
        pytest_argv=module.FROZEN_PYTEST_ARGV_BY_SUITE_ID["task12_release_gate_v1"],
        pre_source_snapshot=snapshot,
        post_source_snapshot=snapshot,
        exit_code=0,
        collected_count=1,
        failed_count=0,
    )
    (tmp_path / test_paths[0]).write_bytes(b"post seal drift\n")
    current = module.capture_source_snapshot(
        root=tmp_path,
        production_paths=production_paths,
        test_paths=test_paths,
    )

    with pytest.raises(ValueError, match="final seal source snapshot"):
        module._validate_synthetic_final_seal_source_binding_for_test(
            sealed_production_sha256_by_path=manifest[
                "production_sha256_by_path"
            ],
            sealed_test_sha256_by_path=manifest["test_sha256_by_path"],
            dependency_manifest=manifest,
            dependency_result_receipts_by_suite=evidence[0],
            task12_result_receipt=task12,
            current_source_snapshot=current,
            production_paths=production_paths,
            test_paths=test_paths,
        )


def test_stable_synthetic_dependency_manifest_is_pass_and_byte_stable(
    tmp_path: Path,
) -> None:
    module = _module()
    production_paths, test_paths, snapshot = _synthetic_snapshot(module, tmp_path)
    evidence = _synthetic_evidence(module, snapshot)

    manifest = module._build_synthetic_dependency_manifest_for_test(
        benchmark_release_id="synthetic-release",
        result_receipts_by_suite=evidence[0],
        result_receipt_refs_by_suite=evidence[1],
        review_receipts_by_suite=evidence[2],
        review_receipt_refs_by_suite=evidence[3],
        source_snapshot=snapshot,
        production_paths=production_paths,
        test_paths=test_paths,
    )
    output = tmp_path / "manifest.json"
    module.write_create_new_or_byte_identical(output, module.pretty_json_bytes(manifest))
    module.write_create_new_or_byte_identical(output, module.pretty_json_bytes(manifest))

    assert manifest["dependency_order"] == list(module.DEPENDENCY_ORDER)
    assert manifest["build_mode"] == "synthetic_test"
    assert output.read_bytes() == module.pretty_json_bytes(manifest)
    with pytest.raises(ValueError, match="release build mode"):
        module.validate_dependency_manifest_for_final_report(manifest)


def test_release_builder_rejects_an_injected_repository_root(tmp_path: Path) -> None:
    module = _module()
    _, _, snapshot = _synthetic_snapshot(module, tmp_path)
    evidence = _synthetic_evidence(module, snapshot)

    with pytest.raises(TypeError):
        module.build_release_dependency_manifest(
            benchmark_release_id="synthetic-release",
            result_receipts_by_suite=evidence[0],
            result_receipt_refs_by_suite=evidence[1],
            review_receipts_by_suite=evidence[2],
            review_receipt_refs_by_suite=evidence[3],
            root=tmp_path,
            build_mode="release",
        )


def test_release_builder_rejects_caller_fabricated_receipt_objects() -> None:
    module = _module()
    snapshot = module.capture_source_snapshot()
    evidence = _synthetic_evidence(module, snapshot)

    with pytest.raises(TypeError):
        module.build_release_dependency_manifest(
            benchmark_release_id="synthetic-release",
            result_receipts_by_suite=evidence[0],
            result_receipt_refs_by_suite=evidence[1],
            review_receipts_by_suite=evidence[2],
            review_receipt_refs_by_suite=evidence[3],
            root=module.ROOT,
            build_mode="release",
        )


def test_semantic_pytest_argv_strips_only_plugin_transport_options() -> None:
    module = _module()
    suite_id = "task05_worker_binding_v1"
    args = [
        "-p",
        module.PYTEST_PLUGIN_NAME,
        "--benchmark-v2-suite-id",
        suite_id,
        "--benchmark-v2-receipt-output=tmp/receipt.json",
        *module.FROZEN_PYTEST_ARGV_BY_SUITE_ID[suite_id][1:],
    ]

    assert module.semantic_pytest_argv(args) == module.FROZEN_PYTEST_ARGV_BY_SUITE_ID[
        suite_id
    ]


def test_plugin_transport_options_cannot_activate_an_implicitly_loaded_plugin() -> None:
    module = _module()

    class Invocation:
        args = (
            module.PYTEST_SUITE_OPTION,
            "task05_worker_binding_v1",
            module.PYTEST_RECEIPT_OPTION,
            "receipt.json",
        )

    class Config:
        invocation_params = Invocation()

        @staticmethod
        def getoption(name):
            return {
                module.PYTEST_SUITE_OPTION: "task05_worker_binding_v1",
                module.PYTEST_RECEIPT_OPTION: "receipt.json",
            }[name]

    with pytest.raises(ValueError, match="explicitly loaded"):
        module.pytest_configure(Config())


def test_explicit_plugin_load_requires_both_transport_options() -> None:
    module = _module()

    class Invocation:
        args = ("-p", module.PYTEST_PLUGIN_NAME)

    class Config:
        invocation_params = Invocation()

        @staticmethod
        def getoption(_name):
            return None

    with pytest.raises(ValueError, match="both transport options"):
        module.pytest_configure(Config())


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("PYTEST_ADDOPTS", "--ignore=tests"),
        ("PYTEST_PLUGINS", "foreign_plugin"),
    ],
)
def test_plugin_rejects_environment_semantic_injection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    module = _module()
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValueError, match=variable):
        _configured_plugin(
            module,
            tmp_path,
            suite_id="task06a_completed_result_identity_v1",
        )


def test_plugin_requires_external_plugin_autoload_to_be_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    monkeypatch.delenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", raising=False)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.delenv("PYTEST_PLUGINS", raising=False)

    with pytest.raises(ValueError, match="autoload"):
        _configured_plugin(
            module,
            tmp_path,
            suite_id="task06a_completed_result_identity_v1",
        )


def test_plugin_rejects_configured_addopts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.delenv("PYTEST_PLUGINS", raising=False)

    with pytest.raises(ValueError, match="addopts"):
        _configured_plugin(
            module,
            tmp_path,
            suite_id="task06a_completed_result_identity_v1",
            addopts=("--ignore=tests",),
        )


def test_plugin_rejects_premature_success_without_closed_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _, _, snapshot = _synthetic_snapshot(module, tmp_path)
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.delenv("PYTEST_PLUGINS", raising=False)
    monkeypatch.setattr(module, "capture_source_snapshot", lambda: deepcopy(snapshot))
    config, output = _configured_plugin(
        module,
        tmp_path,
        suite_id="task06a_completed_result_identity_v1",
    )

    class Item:
        nodeid = "tests/test_learning_workflow_stage_worker.py::test_one"

    class Session:
        items = [Item()]
        testsfailed = 0

        def __init__(self, configured):
            self.config = configured

    session = Session(config)
    module.pytest_sessionstart(session)
    module.pytest_sessionfinish(session, 0)
    receipt = json.loads(output.read_text(encoding="utf-8"))

    assert receipt["status"] == "FAIL"


def test_plugin_stable_in_process_session_can_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _, _, snapshot = _synthetic_snapshot(module, tmp_path)
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.delenv("PYTEST_PLUGINS", raising=False)
    monkeypatch.setattr(module, "capture_source_snapshot", lambda: deepcopy(snapshot))
    config, output = _configured_plugin(
        module,
        tmp_path,
        suite_id="task06a_completed_result_identity_v1",
    )

    class Item:
        nodeid = "tests/test_learning_workflow_stage_worker.py::test_one"

    class Session:
        items = [Item()]
        testsfailed = 0

        def __init__(self, configured):
            self.config = configured

    class Report:
        nodeid = Item.nodeid
        when = "call"
        passed = True
        failed = False
        skipped = False

    session = Session(config)
    module.pytest_sessionstart(session)
    module.pytest_collection_finish(session)
    module.pytest_runtest_logreport(Report())
    module.pytest_sessionfinish(session, 0)
    receipt = json.loads(output.read_text(encoding="utf-8"))

    assert receipt["status"] == "PASS"


def test_final_seal_production_api_rejects_synthetic_bypass(tmp_path: Path) -> None:
    module = _module()
    production_paths, test_paths, snapshot = _synthetic_snapshot(module, tmp_path)
    evidence = _synthetic_evidence(module, snapshot)
    manifest = module._build_synthetic_dependency_manifest_for_test(
        benchmark_release_id="synthetic-release",
        result_receipts_by_suite=evidence[0],
        result_receipt_refs_by_suite=evidence[1],
        review_receipts_by_suite=evidence[2],
        review_receipt_refs_by_suite=evidence[3],
        source_snapshot=snapshot,
        production_paths=production_paths,
        test_paths=test_paths,
    )
    task12 = module.build_dependency_result_receipt(
        suite_id="task12_release_gate_v1",
        pytest_argv=module.FROZEN_PYTEST_ARGV_BY_SUITE_ID["task12_release_gate_v1"],
        pre_source_snapshot=snapshot,
        post_source_snapshot=snapshot,
        exit_code=0,
        collected_count=1,
        failed_count=0,
    )

    with pytest.raises(ValueError, match="release dependency manifest"):
        module.validate_final_seal_source_binding(
            sealed_production_sha256_by_path=manifest[
                "production_sha256_by_path"
            ],
            sealed_test_sha256_by_path=manifest["test_sha256_by_path"],
            dependency_manifest=manifest,
        )


def test_release_manifest_validator_has_no_synthetic_bypass_parameter() -> None:
    module = _module()

    assert "allow_synthetic_test" not in inspect.signature(
        module.validate_release_dependency_manifest
    ).parameters


def test_production_builder_has_no_evidence_injection_or_capability_routes(
    tmp_path: Path,
) -> None:
    module = _module()

    assert set(inspect.signature(module.build_release_dependency_manifest).parameters) == {
        "benchmark_release_id"
    }
    assert not hasattr(module, "_ReleaseDependencyEvidence")
    assert not hasattr(module, "_Task12AcceptanceEvidence")
    assert not hasattr(module, "_PRODUCTION_CAPABILITY_TOKEN")
    assert not hasattr(module, "load_release_dependency_evidence")
    with pytest.raises(TypeError):
        module.build_release_dependency_manifest(
            benchmark_release_id="release",
            result_receipt_paths_by_suite={"fabricated": tmp_path / "receipt.json"},
        )


def test_current_production_builder_fails_closed_on_absent_canonical_evidence() -> None:
    module = _module()

    with pytest.raises(ValueError, match="result receipt.*missing"):
        module.build_release_dependency_manifest(benchmark_release_id="release")


def test_synthetic_builder_deep_copies_all_caller_inputs(tmp_path: Path) -> None:
    module = _module()
    production_paths, test_paths, snapshot = _synthetic_snapshot(module, tmp_path)
    evidence = _synthetic_evidence(module, snapshot)
    manifest = module._build_synthetic_dependency_manifest_for_test(
        benchmark_release_id="synthetic-release",
        result_receipts_by_suite=evidence[0],
        result_receipt_refs_by_suite=evidence[1],
        review_receipts_by_suite=evidence[2],
        review_receipt_refs_by_suite=evidence[3],
        source_snapshot=snapshot,
        production_paths=production_paths,
        test_paths=test_paths,
    )
    frozen = module.pretty_json_bytes(manifest)

    evidence[0][module.DEPENDENCY_ORDER[0]]["status"] = "FAIL"
    evidence[1][module.DEPENDENCY_ORDER[0]]["file_sha256"] = "0" * 64
    evidence[2][module.DEPENDENCY_ORDER[0]]["reviewer_independent"] = False
    snapshot["production_source_sha256_by_path"][production_paths[0]] = "0" * 64

    assert module.pretty_json_bytes(manifest) == frozen


@pytest.mark.parametrize(
    "hook_name", ["pytest_runtest_makereport", "pytest_sessionfinish"]
)
def test_any_foreign_pytest_hook_is_rejected(hook_name: str) -> None:
    module = _module()

    class ForeignPlugin:
        pass

    setattr(ForeignPlugin, hook_name, lambda *args, **kwargs: None)

    class PluginManager:
        @staticmethod
        def get_plugins():
            return {ForeignPlugin()}

    class Config:
        pluginmanager = PluginManager()

    assert module._foreign_collection_hook_present(Config()) is True


@pytest.mark.parametrize(
    "mutation",
    ["content_hash", "safety", "dag", "result_ref", "review_ref"],
)
def test_synthetic_validator_rejects_full_manifest_and_receipt_ref_drift(
    tmp_path: Path, mutation: str
) -> None:
    module = _module()
    production_paths, test_paths, snapshot = _synthetic_snapshot(module, tmp_path)
    evidence = _synthetic_evidence(module, snapshot)
    manifest = module._build_synthetic_dependency_manifest_for_test(
        benchmark_release_id="synthetic-release",
        result_receipts_by_suite=evidence[0],
        result_receipt_refs_by_suite=evidence[1],
        review_receipts_by_suite=evidence[2],
        review_receipt_refs_by_suite=evidence[3],
        source_snapshot=snapshot,
        production_paths=production_paths,
        test_paths=test_paths,
    )
    changed = deepcopy(manifest)
    if mutation == "content_hash":
        changed["content_sha256"] = "0" * 64
    elif mutation == "safety":
        changed["safety"]["display_only"] = False
        changed["content_sha256"] = module.content_sha256(changed)
    elif mutation == "dag":
        changed["dependency_order"].reverse()
        changed["content_sha256"] = module.content_sha256(changed)
    elif mutation == "result_ref":
        changed["result_receipt_refs"][module.DEPENDENCY_ORDER[0]][
            "file_sha256"
        ] = "0" * 64
        changed["content_sha256"] = module.content_sha256(changed)
    else:
        changed["review_receipt_refs"][module.DEPENDENCY_ORDER[0]][
            "file_sha256"
        ] = "0" * 64
        changed["content_sha256"] = module.content_sha256(changed)

    with pytest.raises(ValueError, match="manifest|receipt"):
        module._validate_synthetic_dependency_manifest_for_test(
            changed,
            result_receipts_by_suite=evidence[0],
            result_receipt_refs_by_suite=evidence[1],
            review_receipts_by_suite=evidence[2],
            review_receipt_refs_by_suite=evidence[3],
            current_source_snapshot=snapshot,
            production_paths=production_paths,
            test_paths=test_paths,
        )


def test_final_report_and_seal_apis_have_no_evidence_injection() -> None:
    module = _module()

    assert set(
        inspect.signature(module.validate_dependency_manifest_for_final_report).parameters
    ) == {"manifest"}
    assert set(inspect.signature(module.validate_final_seal_source_binding).parameters) == {
        "sealed_production_sha256_by_path",
        "sealed_test_sha256_by_path",
        "dependency_manifest",
    }


def test_source_snapshot_rejects_root_symlink_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    real_root = tmp_path / "real"
    source = real_root / "production/a.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"alpha\n")
    test_source = real_root / "tests/test_a.py"
    test_source.parent.mkdir(parents=True)
    test_source.write_bytes(b"test\n")
    alias_root = tmp_path / "alias"
    try:
        alias_root.symlink_to(real_root, target_is_directory=True)
    except OSError:
        alias_root.mkdir()
        original_is_symlink = Path.is_symlink
        monkeypatch.setattr(
            Path,
            "is_symlink",
            lambda self: self == alias_root or original_is_symlink(self),
        )

    with pytest.raises(ValueError, match="alias"):
        module.capture_source_snapshot(
            root=alias_root,
            production_paths=("production/a.py",),
            test_paths=("tests/test_a.py",),
        )



def test_source_snapshot_rejects_hard_link_alias(tmp_path: Path) -> None:
    module = _module()
    real_root = tmp_path / "real"
    source = real_root / "production/a.py"
    source.parent.mkdir(parents=True)
    test_source = real_root / "tests/test_a.py"
    test_source.parent.mkdir(parents=True)
    test_source.write_bytes(b"test\n")
    outside = tmp_path / "outside.py"
    outside.write_bytes(b"alpha\n")
    os.link(outside, source)
    with pytest.raises(ValueError, match="hard-link"):
        module.capture_source_snapshot(
            root=real_root,
            production_paths=("production/a.py",),
            test_paths=("tests/test_a.py",),
        )


def test_output_rejects_alias_ancestor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    real_root = tmp_path / "real"
    real_root.mkdir()
    alias_root = tmp_path / "alias"
    try:
        alias_root.symlink_to(real_root, target_is_directory=True)
    except OSError:
        alias_root.mkdir()
        original_is_symlink = Path.is_symlink
        monkeypatch.setattr(
            Path,
            "is_symlink",
            lambda self: self == alias_root or original_is_symlink(self),
        )

    with pytest.raises(ValueError, match="alias"):
        module.write_create_new_or_byte_identical(alias_root / "artifact.json", b"{}\n")



def test_output_rejects_existing_hard_link(tmp_path: Path) -> None:
    module = _module()
    real_root = tmp_path / "real"
    real_root.mkdir()
    original = tmp_path / "original.json"
    original.write_bytes(b"{}\n")
    hard_link = real_root / "artifact.json"
    os.link(original, hard_link)
    with pytest.raises(FileExistsError, match="hard-link"):
        module.write_create_new_or_byte_identical(hard_link, b"{}\n")


def test_module_has_no_launcher_or_runtime_dependency() -> None:
    module = _module()
    source_path = Path(module.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_roots = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }

    assert "subprocess" not in imported_roots
    assert "app" not in imported_roots
    assert not hasattr(module, "run_pytest")
    assert not hasattr(module, "launch_provider")
