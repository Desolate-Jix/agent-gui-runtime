from __future__ import annotations

from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
from typing import Mapping

import pytest
from PIL import Image

from app.learn.hybrid.benchmark_v2_contracts import (
    ARM_ORDER,
    BENCHMARK_RELEASE_ID,
    PROVIDER_CODE_REFS,
    PROVIDER_CORPUS_CONTRACT,
    PROVIDER_MANIFEST_CONTRACT,
    PARENT_REF,
    SAFETY,
    canonical_json_bytes,
    content_sha256,
)
from app.learn.hybrid.benchmark_v2_provider_corpus import (
    validate_preloaded_provider_corpus,
)
from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch


def _sealed(value: dict[str, object]) -> dict[str, object]:
    result = deepcopy(value)
    result["content_sha256"] = content_sha256(result)
    return result


def _write_fixture(root: Path) -> tuple[Path, dict[str, object]]:
    provider_root = root / "provider"
    provider_root.mkdir(parents=True)
    cases: list[dict[str, object]] = []
    for partition_index, partition in enumerate(("regression", "holdout")):
        for index in range(12):
            group_number = partition_index * 12 + index
            group = hashlib.sha256(f"group-{group_number}".encode()).hexdigest()
            relative = (
                f"tests/fixtures/portfolio_hybrid_v1_1/corpus/{partition}/"
                f"case-{group_number:03d}.png"
            )
            image_path = root / relative
            image_path.parent.mkdir(parents=True, exist_ok=True)
            Image.new(
                "RGB",
                (1280, 720),
                color=(group_number + 1, group_number + 2, group_number + 3),
            ).save(image_path, format="PNG", optimize=False)
            image_sha = hashlib.sha256(image_path.read_bytes()).hexdigest()
            layout = {
                "layout_id": f"layout-{group_number}",
                "title": f"Screen {group_number}",
                "surface": "desktop",
                "density": "medium",
                "precision_case": "standard",
                "source_kind": "privacy_safe_synthetic",
                "source_provenance": f"fixture-{group_number}",
            }
            for target in range(5):
                cases.append(
                    {
                        "case_id": hashlib.sha256(
                            f"case-{group_number}-{target}".encode()
                        ).hexdigest(),
                        "partition": partition,
                        "screen_group": group,
                        "goal": f"Find target {target}",
                        "image": {
                            "path": relative,
                            "sha256": image_sha,
                            "width": 1280,
                            "height": 720,
                        },
                        "layout": deepcopy(layout),
                    }
                )
    corpus = {
        "contract_version": PROVIDER_CORPUS_CONTRACT,
        "benchmark_release_id": BENCHMARK_RELEASE_ID,
        "source_parent_ref": deepcopy(PARENT_REF),
        "provider_boundary": {
            "opaque_case_ids": True,
            "opaque_screen_groups": True,
            "filter_complete": True,
            "path_scope": "provider_safe_only",
        },
        "cases": cases,
        "safety": deepcopy(SAFETY),
    }
    corpus["content_sha256"] = content_sha256(corpus)
    corpus_raw = canonical_json_bytes(corpus, pretty=True)
    corpus_path = provider_root / "provider-corpus.v2.json"
    corpus_path.write_bytes(corpus_raw)
    corpus_file_sha = hashlib.sha256(corpus_raw).hexdigest()
    manifest = {
        "contract_version": PROVIDER_MANIFEST_CONTRACT,
        "benchmark_release_id": BENCHMARK_RELEASE_ID,
        "provider_corpus_ref": {
            "contract_version": PROVIDER_CORPUS_CONTRACT,
            "relative_path": "provider-corpus.v2.json",
            "file_sha256": corpus_file_sha,
            "content_sha256": corpus["content_sha256"],
            "source_parent_ref": deepcopy(corpus["source_parent_ref"]),
        },
        "sealed_runtime": {
            "code_refs": [
                {
                    "role": role,
                    "relative_path": relative,
                    "file_sha256": hashlib.sha256(relative.encode()).hexdigest(),
                }
                for role, relative in PROVIDER_CODE_REFS
            ],
            "profile_refs": [
                {
                    "role": "hybrid_config",
                    "relative_path": "configs/learn_hybrid_v1_1.json",
                    "file_sha256": "b" * 64,
                }
            ],
        },
        "workload": {
            "contract_version": "provider_sandbox_workload_request_v1",
            "command": "validate_provider_corpus",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        },
        "arm_order": list(ARM_ORDER),
        "safety": deepcopy(SAFETY),
    }
    manifest_path = provider_root / "provider-manifest.v2.json"
    manifest_path.write_bytes(canonical_json_bytes(manifest, pretty=True))
    return manifest_path, corpus


class _OCR:
    def __init__(self, *, empty: bool = False, wrong_path: bool = False) -> None:
        self.empty = empty
        self.wrong_path = wrong_path
        self.paths: list[str] = []

    def scan_image(self, image_path: str) -> OCRResult:
        self.paths.append(image_path)
        matches = [] if self.empty else [
            OCRTextMatch(
                text="Target",
                score=0.99,
                bbox=OCRBoundingBox(x=4, y=5, width=40, height=20),
            )
        ]
        return OCRResult(
            image_path=(
                str(Path(image_path).with_name("fabricated.png").resolve())
                if self.wrong_path
                else str(Path(image_path).resolve())
            ),
            matches=matches,
            metadata={"engine": "deterministic-test", "match_count": len(matches)},
        )


class _Windows:
    def __init__(
        self,
        *,
        empty_uia: bool = False,
        stale_pid: bool = False,
        stale_hwnd: bool = False,
        stale_create_time: bool = False,
        fail_close_once: bool = False,
    ) -> None:
        self.empty_uia = empty_uia
        self.stale_pid = stale_pid
        self.stale_hwnd = stale_hwnd
        self.stale_create_time = stale_create_time
        self.fail_close_once = fail_close_once
        self.active = 0
        self.maximum_active = 0
        self.launched: list[dict[str, object]] = []
        self.closed: list[str] = []
        self.close_calls = 0
        self.cleanup_by_journal: dict[str, dict[str, object]] = {}

    def launch(self, **kwargs: object) -> dict[str, object]:
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        image_path = Path(str(kwargs["image_path"]))
        operation_id = str(kwargs["operation_id"])
        journal_path = Path(str(kwargs["journal_path"]))
        owner: dict[str, object] = {
            "owner_id": f"owner-{operation_id}",
            "operation_id": operation_id,
            "hwnd": 1000 + len(self.launched),
            "process_identity": {"pid": 2000 + len(self.launched), "create_time_ns": 3000},
            "screenshot_sha256": str(kwargs["expected_sha256"]),
            "screenshot_path": str(image_path.resolve()),
            "image_dimensions": {"width": 1280, "height": 720},
            "journal_path": str(journal_path.resolve()),
            "window_rect": {"left": 10, "top": 20, "right": 1290, "bottom": 740},
            "client_rect": {"left": 0, "top": 0, "right": 1280, "bottom": 720},
            "window_title": "Fixture",
            "window_class": "FixtureClass",
            "scope_name": f"scope-{operation_id}",
            "uia_root_identity": _sealed({"kind": "uia-root", "operation_id": operation_id}),
            "journal_root": _sealed({"kind": "owner-journal", "operation_id": operation_id}),
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "display_only": True,
        }
        owner["content_sha256"] = content_sha256(owner)
        self.launched.append(owner)
        return deepcopy(owner)

    def snapshot(self, *, owner: Mapping[str, object]) -> dict[str, object]:
        pid = int(owner["process_identity"]["pid"]) + (1 if self.stale_pid else 0)
        hwnd = int(owner["hwnd"]) + (1 if self.stale_hwnd else 0)
        process_identity = deepcopy(owner["process_identity"])
        if self.stale_create_time:
            process_identity["create_time_ns"] += 1
        controls = [] if self.empty_uia else [
            {
                "provider": "windows_uia",
                "control_id": "uia-root",
                "name": "Fixture",
                "control_type": "Window",
                "automation_id": None,
                "class_name": "FixtureClass",
                "bbox": {"x": 0, "y": 0, "w": 1280, "h": 720},
                "screen_bbox": {"x": 10, "y": 20, "w": 1280, "h": 720},
                "enabled": True,
                "visible": True,
                "patterns": ["Invoke"],
            }
        ]
        snapshot = {
            "provider": "windows_uia",
            "provider_version": "windows_uia_provider_v1",
            "status": "ok",
            "window": {
                "handle": hwnd,
                "title": "Fixture",
                "process_id": pid,
                "process_name": "python.exe",
                "bbox": {"x": 0, "y": 0, "w": 1280, "h": 720},
            },
            "control_count": len(controls),
            "controls": controls,
        }
        return _sealed(
            {
                "contract_version": "portfolio_hybrid_benchmark_v2_owned_window_snapshot_v1",
                "owner_binding_ref": {
                    "id": owner["owner_id"],
                    "content_sha256": owner["content_sha256"],
                },
                "operation_id": owner["operation_id"],
                "exact_hwnd": hwnd,
                "process_identity": process_identity,
                "job_member_pids": [owner["process_identity"]["pid"]],
                "screenshot_sha256": owner["screenshot_sha256"],
                "uia_root_identity": deepcopy(owner["uia_root_identity"]),
                "uia_snapshot": snapshot,
                "pre_raw_identity_sha256": "c" * 64,
                "post_raw_identity_sha256": "c" * 64,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
                "display_only": True,
            }
        )

    def close(self, *, journal_path: Path, reason: str) -> dict[str, object]:
        journal_key = str(Path(journal_path).resolve())
        existing = self.cleanup_by_journal.get(journal_key)
        if existing is not None:
            return deepcopy(existing)
        self.close_calls += 1
        if self.fail_close_once and self.close_calls == 1:
            raise RuntimeError("transient cleanup failure")
        self.active -= 1
        self.closed.append(reason)
        receipt = _sealed({"cleanup_status": "verified", "reason": reason})
        self.cleanup_by_journal[journal_key] = deepcopy(receipt)
        return receipt


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch,
    runtime_module: object,
    corpus: Mapping[str, object],
    windows: _Windows,
    ocr: _OCR,
) -> None:
    case_refs = [
        {
            "case_id": case["case_id"],
            "case_content_sha256": content_sha256(case),
        }
        for case in corpus["cases"]
    ]
    corpus_file_ref = _sealed(
        {
            "contract_version": "benchmark_v2_provider_corpus_file_ref_v1",
            "relative_path": "provider-corpus.v2.json",
            "file_sha256": hashlib.sha256(
                canonical_json_bytes(corpus, pretty=True)
            ).hexdigest(),
            "source_parent_ref": deepcopy(corpus["source_parent_ref"]),
        }
    )
    monkeypatch.setattr(
        runtime_module,
        "load_provider_corpus",
        lambda *, child_path, expected_sha256: validate_preloaded_provider_corpus(
            raw=Path(child_path).read_bytes(), expected_sha256=expected_sha256
        ),
    )
    monkeypatch.setattr(runtime_module, "get_production_provider_case_resolver", lambda: object())
    monkeypatch.setattr(runtime_module, "provider_case_resolver_case_refs", lambda resolver: deepcopy(case_refs))
    monkeypatch.setattr(runtime_module, "provider_case_resolver_corpus_file_ref", lambda resolver: deepcopy(corpus_file_ref))
    monkeypatch.setattr(runtime_module, "launch_owned_window", windows.launch)
    monkeypatch.setattr(runtime_module, "snapshot_owned_window", windows.snapshot)
    monkeypatch.setattr(runtime_module, "close_owned_window", windows.close)
    monkeypatch.setattr(runtime_module, "ocr_service", ocr)
    monkeypatch.setattr(
        runtime_module,
        "load_hybrid_config",
        lambda project_root: {"mode": "hybrid_v1_1"},
    )
    monkeypatch.setattr(
        runtime_module,
        "get_production_server_worker_window_binding_publisher",
        lambda: object(),
    )
    monkeypatch.setattr(
        runtime_module,
        "publish_server_worker_window_binding",
        lambda **kwargs: _sealed(
            {
                "window_binding_ref": {
                    "id": kwargs["owner"]["owner_id"],
                    "content_sha256": kwargs["owner"]["content_sha256"],
                },
                "capture_ref": deepcopy(kwargs["capture_ref"]),
                "owner_journal_ref": deepcopy(kwargs["owner"]["journal_root"]),
            }
        ),
    )


def _runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **window_options: bool):
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module

    manifest_path, corpus = _write_fixture(tmp_path)
    windows = _Windows(**window_options)
    ocr = _OCR()
    _install_fakes(monkeypatch, runtime_module, corpus, windows, ocr)
    runtime = runtime_module._BenchmarkV2ProductionRuntime(
        project_root=tmp_path,
        authority_root=tmp_path / "runtime_state" / "binding-authority",
    )
    manifest = runtime.load_provider_manifest(path=manifest_path)
    return runtime_module, runtime, manifest, corpus, windows, ocr


def test_production_runtime_public_surface_is_closed_and_singleton_stable() -> None:
    from app.learn.hybrid.benchmark_v2_runtime import (
        BenchmarkV2ProductionRuntimePort,
        get_production_benchmark_v2_runtime,
    )

    assert get_production_benchmark_v2_runtime() is get_production_benchmark_v2_runtime()
    assert list(inspect.signature(BenchmarkV2ProductionRuntimePort.load_provider_manifest).parameters) == [
        "self",
        "path",
    ]
    assert list(inspect.signature(BenchmarkV2ProductionRuntimePort.prepare_screen_groups).parameters) == [
        "self",
        "provider_manifest",
        "partition",
        "attempt_ref",
        "attempt_dir",
    ]
    runtime = get_production_benchmark_v2_runtime()
    assert not hasattr(runtime, "composition")
    assert not hasattr(runtime, "store")
    assert not hasattr(runtime, "worker_registry")


def test_prepare_screen_groups_is_lazy_exact_and_shares_capture_lineage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, runtime, manifest, _, windows, ocr = _runtime(monkeypatch, tmp_path)
    attempt_ref = _sealed({"attempt_id": "attempt-1"})
    assert windows.active == 0

    groups = []
    for partition in ("regression", "holdout"):
        iterator = iter(
            runtime.prepare_screen_groups(
                provider_manifest=manifest,
                partition=partition,
                attempt_ref=attempt_ref,
                attempt_dir=tmp_path / "attempt",
            )
        )
        for _ in range(12):
            group = next(iterator)
            groups.append(group)
            assert windows.active == 1
            assert len(group["case_refs"]) == 5
            assert group["capture_image_path"].startswith("artifacts/screenshots/")
            sources = group["capture_bundle"]["context"]["sources"]
            assert {source["source_kind"] for source in sources} == {"ocr", "uia"}
            assert {
                source["capture_lineage_ref"]["content_sha256"] for source in sources
            } == {group["capture_bundle"]["capture_lineage_ref"]["content_sha256"]}
            assert Path(ocr.paths[-1]).read_bytes() == Path(
                windows.launched[-1]["screenshot_path"]
            ).read_bytes()
        with pytest.raises(StopIteration):
            next(iterator)

    assert len({group["screen_group"] for group in groups}) == 24
    assert sum(len(group["case_refs"]) for group in groups) == 120
    assert windows.maximum_active == 1
    assert windows.active == 0
    assert len(windows.closed) == 24


def test_screen_group_iterator_context_closes_retained_early_break(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=_sealed({"attempt_id": "attempt-early-break"}),
        attempt_dir=tmp_path / "attempt",
    )

    with iterator:
        for _group in iterator:
            assert windows.active == 1
            break

    assert windows.active == 0
    assert len(windows.closed) == 1
    iterator.close()
    assert len(windows.closed) == 1


def test_screen_group_iterator_retries_exact_owner_after_transient_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, runtime, manifest, _, windows, _ = _runtime(
        monkeypatch,
        tmp_path,
        fail_close_once=True,
    )
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=_sealed({"attempt_id": "attempt-cleanup-retry"}),
        attempt_dir=tmp_path / "attempt",
    )
    next(iterator)

    with pytest.raises(RuntimeError, match="transient cleanup failure"):
        iterator.close()
    assert windows.active == 1
    assert windows.close_calls == 1
    assert windows.closed == []

    iterator.close()
    assert windows.active == 0
    assert windows.close_calls == 2
    assert len(windows.closed) == 1
    with pytest.raises(StopIteration):
        next(iterator)


def test_prepare_failure_retains_exact_cleanup_owner_until_retry_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_module, runtime, manifest, _, windows, _ = _runtime(
        monkeypatch,
        tmp_path,
        fail_close_once=True,
    )
    monkeypatch.setattr(runtime_module, "ocr_service", _OCR(empty=True))
    attempt_ref = _sealed({"attempt_id": "attempt-prepare-cleanup-retry"})
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=tmp_path / "attempt",
    )

    with pytest.raises(BaseExceptionGroup, match="prepare and cleanup"):
        next(iterator)
    assert windows.active == 1
    assert windows.close_calls == 1
    assert windows.closed == []
    assert runtime._active is None
    assert runtime._pending_cleanup is not None

    blocked = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt_ref,
        attempt_dir=tmp_path / "attempt",
    )
    with pytest.raises(RuntimeError, match="already owns"):
        next(blocked)
    assert len(windows.launched) == 1

    iterator.close()
    assert windows.active == 0
    assert windows.close_calls == 2
    assert len(windows.closed) == 1
    assert runtime._pending_cleanup is None


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ("ocr", "OCR"),
        ("fabricated_ocr", "OCR"),
        ("uia", "UIA"),
        ("stale", "window|HWND|process"),
        ("stale_hwnd", "window|HWND|process"),
        ("stale_create_time", "window|HWND|process"),
    ],
)
def test_prepare_rejects_empty_or_stale_evidence_and_closes_window(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: str,
    message: str,
) -> None:
    runtime_module, runtime, manifest, corpus, windows, _ = _runtime(
        monkeypatch,
        tmp_path,
        empty_uia=failure == "uia",
        stale_pid=failure == "stale",
        stale_hwnd=failure == "stale_hwnd",
        stale_create_time=failure == "stale_create_time",
    )
    if failure == "ocr":
        empty = _OCR(empty=True)
        monkeypatch.setattr(runtime_module, "ocr_service", empty)
    elif failure == "fabricated_ocr":
        fabricated = _OCR(wrong_path=True)
        monkeypatch.setattr(runtime_module, "ocr_service", fabricated)
    with pytest.raises(ValueError, match=message):
        next(
            iter(
                runtime.prepare_screen_groups(
                    provider_manifest=manifest,
                    partition="regression",
                    attempt_ref=_sealed({"attempt_id": "attempt-fail"}),
                    attempt_dir=tmp_path / "attempt",
                )
            )
        )
    assert windows.active == 0
    assert len(windows.closed) == 1


def test_missing_source_and_wrong_corpus_sha_fail_before_window_launch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, runtime, manifest, corpus, windows, _ = _runtime(monkeypatch, tmp_path)
    for case in corpus["cases"]:
        if case["partition"] == "regression":
            (tmp_path / case["image"]["path"]).unlink(missing_ok=True)
    with pytest.raises(ValueError, match="source|image|screenshot"):
        next(
            iter(
                runtime.prepare_screen_groups(
                    provider_manifest=manifest,
                    partition="regression",
                    attempt_ref=_sealed({"attempt_id": "attempt-missing"}),
                    attempt_dir=tmp_path / "attempt",
                )
            )
        )
    assert windows.launched == []

    manifest_path, _ = _write_fixture(tmp_path / "other")
    decoded = json.loads(manifest_path.read_text(encoding="utf-8"))
    decoded["provider_corpus_ref"]["file_sha256"] = "0" * 64
    manifest_path.write_bytes(canonical_json_bytes(decoded, pretty=True))
    with pytest.raises(ValueError, match="SHA"):
        runtime.load_provider_manifest(path=manifest_path)
