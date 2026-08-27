"""Benchmark-v2 真实屏幕组准备边界；不授予任何桌面动作权限。"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Iterator, Mapping, Protocol

from app.core.ocr_service import ocr_service
from app.learn.hybrid.benchmark_v2_contracts import (
    canonical_json_bytes,
    content_sha256,
)
from app.learn.hybrid.benchmark_v2_incumbent_operation import (
    compose_benchmark_v2_hybrid_screen_group_start,
    compose_benchmark_v2_workflow_window_binding,
)
from app.learn.hybrid.benchmark_v2_provider_corpus import (
    get_production_provider_case_resolver,
    load_provider_corpus,
    provider_case_resolver_case_refs,
    provider_case_resolver_corpus_file_ref,
    validate_provider_manifest,
)
from app.learn.hybrid.benchmark_v2_window_owner import (
    close_owned_window,
    launch_owned_window,
    snapshot_owned_window,
)
from app.learn.hybrid.benchmark_v2_worker_binding import (
    get_production_server_worker_window_binding_publisher,
    publish_server_worker_window_binding,
)
from app.learn.hybrid.capture import (
    seal_hybrid_capture_bundle,
    seal_hybrid_capture_identity,
)
from app.learn.hybrid.contracts import load_hybrid_config
from app.learn.recognition.uei.builtin_learning_projection import (
    seal_builtin_ocr_evidence,
    seal_builtin_uia_evidence,
)
from app.learn.recognition.uei.canonical import seal_immutable
from app.learn.recognition.uei.store import UEIObjectStore


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SCREENSHOT_ROOT = Path("artifacts") / "screenshots" / "benchmark-v2"
_AUTHORITY_ROOT = (
    _PROJECT_ROOT / "runtime_state" / "benchmark-v2-worker-window-binding-authority"
).resolve()
_OMNI_PROVIDER_ID = "local.runtime/omniparser"
_OMNI_PROFILE_ID = "local.runtime/omniparser/shadow-v2"
_OMNI_PROVIDER_VERSION = "v2.0.1"
_SAFE_LIMITS = {
    "max_json_bytes": 1024 * 1024,
    "max_depth": 8,
    "max_array_items": 4096,
    "max_object_properties": 64,
    "max_string_chars": 4096,
    "allowed_json_types": [
        "object",
        "array",
        "string",
        "number",
        "boolean",
        "null",
    ],
}


class BenchmarkV2ScreenGroupIterator(Iterator[Mapping[str, object]], Protocol):
    def close(self) -> None: ...

    def __enter__(self) -> "BenchmarkV2ScreenGroupIterator": ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...


class BenchmarkV2ProductionRuntimePort(Protocol):
    def load_provider_manifest(self, *, path: Path) -> Mapping[str, object]: ...

    def prepare_screen_groups(
        self,
        *,
        provider_manifest: Mapping[str, object],
        partition: str,
        attempt_ref: Mapping[str, object],
        attempt_dir: Path,
    ) -> BenchmarkV2ScreenGroupIterator: ...


class _OwnedScreenGroupIterator:
    __slots__ = ("_iterator", "_cleanup", "_iterator_done", "_closed")

    def __init__(
        self,
        iterator: Iterator[Mapping[str, object]],
        *,
        cleanup: Callable[[], object],
    ) -> None:
        self._iterator = iterator
        self._cleanup = cleanup
        self._iterator_done = False
        self._closed = False

    def __iter__(self) -> "_OwnedScreenGroupIterator":
        return self

    def __next__(self) -> Mapping[str, object]:
        if self._closed:
            raise StopIteration
        if self._iterator_done:
            raise RuntimeError("benchmark screen-group cleanup is still pending")
        try:
            return next(self._iterator)
        except StopIteration:
            self._iterator_done = True
            self._closed = True
            raise
        except BaseException:
            self._iterator_done = True
            raise

    def close(self) -> None:
        if self._closed:
            return
        if not self._iterator_done:
            close = getattr(self._iterator, "close", None)
            if not callable(close):
                raise RuntimeError("benchmark screen-group iterator is not closable")
            try:
                close()
            finally:
                self._iterator_done = True
        self._cleanup()
        self._closed = True

    def __enter__(self) -> "_OwnedScreenGroupIterator":
        if self._closed:
            raise RuntimeError("benchmark screen-group iterator is already closed")
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.close()


class _LoadedProviderManifest(dict[str, object]):
    __slots__ = ("_source_path", "_corpus", "_case_refs", "_corpus_file_ref")

    def __init__(
        self,
        value: Mapping[str, object],
        *,
        source_path: Path,
        corpus: Mapping[str, object],
        case_refs: list[Mapping[str, object]],
        corpus_file_ref: Mapping[str, object],
    ) -> None:
        super().__init__(deepcopy(dict(value)))
        self._source_path = source_path
        self._corpus = deepcopy(dict(corpus))
        self._case_refs = [deepcopy(dict(item)) for item in case_refs]
        self._corpus_file_ref = deepcopy(dict(corpus_file_ref))


class _BenchmarkV2ProductionRuntime:
    __slots__ = (
        "_project_root",
        "_authority_root",
        "_lock",
        "_active",
        "_pending_cleanup",
        "_preparing",
    )

    def __init__(self, *, project_root: Path, authority_root: Path) -> None:
        self._project_root = Path(project_root).resolve()
        self._authority_root = Path(authority_root).resolve()
        self._lock = RLock()
        self._active: dict[str, Any] | None = None
        self._pending_cleanup: dict[str, object] | None = None
        self._preparing = False

    def load_provider_manifest(self, *, path: Path) -> Mapping[str, object]:
        manifest_path = _canonical_file(path, name="provider manifest")
        raw = manifest_path.read_bytes()
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("provider manifest is not canonical UTF-8 JSON") from error
        if raw != canonical_json_bytes(decoded, pretty=True):
            raise ValueError("provider manifest bytes are not canonical")
        if not isinstance(decoded, Mapping):
            raise ValueError("provider manifest must be an object")
        manifest = validate_provider_manifest(decoded)
        ref = manifest["provider_corpus_ref"]
        corpus_path = (manifest_path.parent / str(ref["relative_path"])).resolve()
        if corpus_path.parent != manifest_path.parent or not corpus_path.is_file():
            raise ValueError("provider corpus source is missing")
        corpus = load_provider_corpus(
            child_path=corpus_path,
            expected_sha256=str(ref["file_sha256"]),
        )
        if (
            corpus.get("content_sha256") != ref["content_sha256"]
            or corpus.get("source_parent_ref") != ref["source_parent_ref"]
        ):
            raise ValueError("provider manifest and corpus lineage differ")
        resolver = get_production_provider_case_resolver()
        case_refs = provider_case_resolver_case_refs(resolver)
        corpus_file_ref = provider_case_resolver_corpus_file_ref(resolver)
        expected_case_refs = {
            (str(case["case_id"]), content_sha256(case)) for case in corpus["cases"]
        }
        observed_case_refs = {
            (str(case["case_id"]), str(case["case_content_sha256"]))
            for case in case_refs
        }
        if expected_case_refs != observed_case_refs:
            raise ValueError("production provider case resolver differs from corpus")
        if (
            corpus_file_ref.get("file_sha256") != ref["file_sha256"]
            or corpus_file_ref.get("source_parent_ref") != ref["source_parent_ref"]
        ):
            raise ValueError("production provider corpus ref differs from manifest")
        return _LoadedProviderManifest(
            manifest,
            source_path=manifest_path,
            corpus=corpus,
            case_refs=case_refs,
            corpus_file_ref=corpus_file_ref,
        )

    def prepare_screen_groups(
        self,
        *,
        provider_manifest: Mapping[str, object],
        partition: str,
        attempt_ref: Mapping[str, object],
        attempt_dir: Path,
    ) -> BenchmarkV2ScreenGroupIterator:
        loaded = _loaded_manifest(provider_manifest)
        if partition not in {"regression", "holdout"}:
            raise ValueError("benchmark partition is invalid")
        attempt = _sealed_parent(attempt_ref, name="attempt ref")
        directory = Path(attempt_dir)
        if not directory.is_absolute():
            directory = directory.resolve()
        if directory != directory.resolve():
            raise ValueError("benchmark attempt directory must be canonical")
        groups = _partition_groups(loaded, partition=partition)
        owner_token = object()

        def generate() -> Iterator[Mapping[str, object]]:
            for screen_group, cases, case_refs in groups:
                with self._lock:
                    if (
                        self._active is not None
                        or self._pending_cleanup is not None
                        or self._preparing
                    ):
                        raise RuntimeError("benchmark runtime already owns one live screen group")
                    self._preparing = True
                try:
                    prepared = self._prepare_one(
                        loaded=loaded,
                        attempt_ref=attempt,
                        attempt_dir=directory,
                        partition=partition,
                        screen_group=screen_group,
                        cases=cases,
                        case_refs=case_refs,
                        owner_token=owner_token,
                    )
                finally:
                    with self._lock:
                        self._preparing = False
                try:
                    yield deepcopy(prepared["screen_group_start"])
                finally:
                    self._close_active(
                        owner_token=owner_token,
                        reason="benchmark_v2_screen_group_iterator_advanced",
                    )

        return _OwnedScreenGroupIterator(
            generate(),
            cleanup=lambda: self._close_active(
                owner_token=owner_token,
                reason="benchmark_v2_screen_group_iterator_closed"
            ),
        )

    def open_screen_group(
        self, *, provider_group: Mapping[str, object]
    ) -> Mapping[str, object]:
        with self._lock:
            active = self._active
            if (
                active is None
                or provider_group.get("content_sha256")
                != active["screen_group_start"]["content_sha256"]
            ):
                raise ValueError("benchmark screen group is not the current owned group")
            return deepcopy(active["workflow_window_binding"])

    def close_screen_group(
        self, *, window_binding: Mapping[str, object], reason: str
    ) -> Mapping[str, object]:
        with self._lock:
            active = self._active
            if (
                active is None
                or window_binding.get("content_sha256")
                != active["workflow_window_binding"]["content_sha256"]
            ):
                raise ValueError("benchmark window binding is not the current owned group")
            owner_token = active["owner_token"]
        return self._close_active(owner_token=owner_token, reason=reason)

    def _prepare_one(
        self,
        *,
        loaded: _LoadedProviderManifest,
        attempt_ref: Mapping[str, object],
        attempt_dir: Path,
        partition: str,
        screen_group: str,
        cases: list[dict[str, Any]],
        case_refs: list[dict[str, object]],
        owner_token: object,
    ) -> dict[str, Any]:
        del attempt_dir
        image = cases[0]["image"]
        source = _project_file(
            self._project_root,
            Path(str(image["path"])),
            name="provider screenshot source",
        )
        raw = _read_exact_file(source)
        image_sha = sha256(raw).hexdigest()
        if image_sha != image["sha256"]:
            raise ValueError("provider screenshot source SHA differs from corpus")
        destination = (
            self._project_root
            / _SCREENSHOT_ROOT
            / str(attempt_ref["content_sha256"])[:24]
            / f"{screen_group}.png"
        ).resolve()
        _create_identical(destination, raw)
        operation_digest = sha256(
            canonical_json_bytes(
                {
                    "attempt_ref": dict(attempt_ref),
                    "partition": partition,
                    "screen_group": screen_group,
                    "image_sha256": image_sha,
                }
            )
        ).hexdigest()
        operation_id = f"benchmark-v2-{operation_digest[:48]}"
        run_id = f"benchmark-v2-run-{operation_digest}"
        journal_path = self._authority_root / f"{operation_id}.owner.json"
        owner: Mapping[str, object] | None = None
        try:
            self._authority_root.mkdir(parents=True, exist_ok=True)
            owner = launch_owned_window(
                image_path=destination,
                expected_sha256=image_sha,
                operation_id=operation_id,
                journal_path=journal_path,
            )
            with self._lock:
                if self._pending_cleanup is not None or self._active is not None:
                    raise RuntimeError("benchmark runtime acquired a second cleanup owner")
                self._pending_cleanup = {
                    "owner_token": owner_token,
                    "journal_path": journal_path,
                    "owner_id": owner["owner_id"],
                }
            snapshot_record = _validate_snapshot_record(
                snapshot_owned_window(owner=owner), owner=owner
            )
            uia_snapshot = snapshot_record["uia_snapshot"]
            window_binding = _capture_window_binding(owner, uia_snapshot)
            identity = seal_hybrid_capture_identity(
                project_root=self._project_root,
                image_path=destination,
                run_id=run_id,
                workflow_revision=0,
                window_binding=window_binding,
            )
            ocr_value = ocr_service.scan_image(str(destination.resolve()))
            if not hasattr(ocr_value, "to_dict"):
                raise ValueError("built-in OCR did not return its exact result contract")
            ocr_result = ocr_value.to_dict()
            if (
                ocr_result.get("image_path") != str(destination.resolve())
                or not isinstance(ocr_result.get("matches"), list)
                or not ocr_result["matches"]
                or not isinstance(ocr_result.get("metadata"), dict)
                or ocr_result["metadata"].get("match_count")
                != len(ocr_result["matches"])
            ):
                raise ValueError("built-in OCR result is empty or does not bind the exact PNG")
            ocr_ref = seal_builtin_ocr_evidence(
                project_root=self._project_root,
                image_path=destination,
                capture_id=str(identity["capture_id"]),
                captured_at=str(identity["captured_at"]),
                ocr_result=ocr_result,
                expected_image_sha256=image_sha,
                expected_image_size={
                    "width": int(image["width"]),
                    "height": int(image["height"]),
                },
                capture_lineage_ref=identity["capture_lineage_ref"],
                capture_envelope=identity.capture_envelope,
            )
            uia_ref = seal_builtin_uia_evidence(
                project_root=self._project_root,
                image_path=destination,
                capture_lineage_ref=identity["capture_lineage_ref"],
                capture_envelope=identity.capture_envelope,
                uia_snapshot=uia_snapshot,
                window_binding=window_binding,
            )
            context = {
                "capture_lineage_ref": deepcopy(identity["capture_lineage_ref"]),
                "sources": [
                    _capture_source(
                        source_kind="ocr",
                        evidence_ref=ocr_ref,
                        identity=identity,
                        run_id=run_id,
                        window_binding=window_binding,
                    ),
                    _capture_source(
                        source_kind="uia",
                        evidence_ref=uia_ref,
                        identity=identity,
                        run_id=run_id,
                        window_binding=window_binding,
                    ),
                ],
                "derived_views": [],
            }
            bundle = seal_hybrid_capture_bundle(
                project_root=self._project_root,
                image_path=destination,
                run_id=run_id,
                workflow_revision=0,
                window_binding=window_binding,
                ocr_uia_context=context,
                capture_envelope=identity.capture_envelope,
            )
            request_ref, registration_ref, manifest_ref = _seal_omni_parents(
                project_root=self._project_root,
                capture_lineage_ref=identity["capture_lineage_ref"],
                capture_id=str(identity["capture_id"]),
            )
            capture_ref = {
                "id": str(identity["capture_id"]),
                "content_sha256": str(identity["capture_lineage_ref"]["content_sha256"]),
            }
            authority = publish_server_worker_window_binding(
                publisher=get_production_server_worker_window_binding_publisher(),
                run_id=run_id,
                stage="screen_understanding",
                operation_id=operation_id,
                owner=owner,
                capture_ref=capture_ref,
            )
            workflow_window_binding = compose_benchmark_v2_workflow_window_binding(
                run_id=run_id,
                operation_id=operation_id,
                window_binding_ref=authority["window_binding_ref"],
                capture_ref=capture_ref,
                owner_journal_ref=authority["owner_journal_ref"],
                expected_uia_root_ref=owner["uia_root_identity"],
            )
            relative_capture = destination.relative_to(self._project_root).as_posix()
            screen_group_start = compose_benchmark_v2_hybrid_screen_group_start(
                attempt_ref=attempt_ref,
                partition=partition,
                screen_group=screen_group,
                provider_corpus_ref=loaded._corpus_file_ref,
                case_refs=case_refs,
                hybrid_capture_bundle_ref=bundle["bundle_ref"],
                request_ref=request_ref,
                registration_ref=registration_ref,
                manifest_ref=manifest_ref,
                capture_image_path=relative_capture,
                hybrid_config=load_hybrid_config(self._project_root),
                capture_bundle=bundle,
            )
            prepared = {
                "screen_group_start": screen_group_start,
                "workflow_window_binding": workflow_window_binding,
                "owner": deepcopy(dict(owner)),
                "journal_path": journal_path,
            }
            with self._lock:
                if self._active is not None:
                    raise RuntimeError("benchmark runtime acquired a second live window")
                pending = self._pending_cleanup
                if (
                    pending is None
                    or pending["owner_token"] is not owner_token
                    or pending["journal_path"] != journal_path
                ):
                    raise RuntimeError("benchmark cleanup ownership changed before publish")
                self._active = {**prepared, "owner_token": owner_token}
            return deepcopy(prepared)
        except BaseException as primary:
            if owner is not None:
                try:
                    self._close_active(
                        owner_token=owner_token,
                        reason="benchmark_v2_screen_group_prepare_failed",
                    )
                except BaseException as cleanup:
                    raise BaseExceptionGroup(
                        "benchmark screen group prepare and cleanup failed",
                        [primary, cleanup],
                    )
            raise

    def _close_active(
        self, *, owner_token: object, reason: str
    ) -> Mapping[str, object]:
        with self._lock:
            active = self._active
            pending = self._pending_cleanup
            if active is None and pending is None:
                return _sealed_parent(
                    {"content_sha256": "0" * 64}, name="empty close replay"
                )
            if pending is None or pending["owner_token"] is not owner_token:
                raise RuntimeError("benchmark cleanup owner differs")
            if active is not None and active["owner_token"] is not owner_token:
                raise RuntimeError("benchmark active owner differs")
            receipt = close_owned_window(
                journal_path=Path(str(pending["journal_path"])),
                reason=reason,
            )
            sealed = _sealed_parent(receipt, name="window cleanup receipt")
            self._active = None
            self._pending_cleanup = None
            return sealed


def _loaded_manifest(value: Mapping[str, object]) -> _LoadedProviderManifest:
    if type(value) is not _LoadedProviderManifest:
        raise ValueError("provider manifest must come from this production runtime")
    validate_provider_manifest(value)
    return value


def _partition_groups(
    loaded: _LoadedProviderManifest, *, partition: str
) -> list[tuple[str, list[dict[str, Any]], list[dict[str, object]]]]:
    ref_by_id = {str(ref["case_id"]): deepcopy(ref) for ref in loaded._case_refs}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for case in loaded._corpus["cases"]:
        if case["partition"] == partition:
            grouped.setdefault(str(case["screen_group"]), []).append(deepcopy(case))
    result = []
    for screen_group in sorted(grouped):
        cases = grouped[screen_group]
        if len(cases) != 5:
            raise ValueError("provider screen group no longer contains five cases")
        refs = [ref_by_id[str(case["case_id"])] for case in cases]
        result.append((screen_group, cases, refs))
    if len(result) != 12:
        raise ValueError("provider partition no longer contains twelve screen groups")
    return result


def _canonical_file(path: Path, *, name: str) -> Path:
    if not isinstance(path, Path):
        raise ValueError(f"{name} must be a server-owned Path")
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"{name} is not a file")
    return resolved


def _project_file(root: Path, path: Path, *, name: str) -> Path:
    try:
        candidate = (root / path).resolve(strict=True)
    except OSError as error:
        raise ValueError(f"{name} is missing") from error
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{name} escapes project root") from error
    if not candidate.is_file():
        raise ValueError(f"{name} is missing")
    return candidate


def _read_exact_file(path: Path) -> bytes:
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    if (
        before.st_size != len(raw)
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        raise ValueError("provider screenshot changed during exact read")
    return raw


def _create_identical(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_BINARY)
    except FileExistsError:
        if path.read_bytes() != raw:
            raise ValueError("benchmark capture destination is already occupied")
        return
    try:
        offset = 0
        while offset < len(raw):
            offset += os.write(descriptor, raw[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if path.read_bytes() != raw:
        raise ValueError("benchmark capture copy is not byte-identical")


def _sealed_parent(value: Mapping[str, object], *, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{name} must be a sealed object")
    result = deepcopy(dict(value))
    digest = result.get("content_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError(f"{name} content SHA is invalid")
    if len(result) > 1 and content_sha256(result) != digest:
        raise ValueError(f"{name} content SHA differs")
    return result


def _validate_snapshot_record(
    value: Mapping[str, object], *, owner: Mapping[str, object]
) -> dict[str, Any]:
    fields = {
        "contract_version",
        "owner_binding_ref",
        "operation_id",
        "exact_hwnd",
        "process_identity",
        "job_member_pids",
        "screenshot_sha256",
        "uia_root_identity",
        "uia_snapshot",
        "pre_raw_identity_sha256",
        "post_raw_identity_sha256",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "display_only",
        "content_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("owned window snapshot record is not closed")
    record = deepcopy(dict(value))
    if (
        record["contract_version"]
        != "portfolio_hybrid_benchmark_v2_owned_window_snapshot_v1"
        or record["content_sha256"] != content_sha256(record)
        or record["owner_binding_ref"]
        != {"id": owner["owner_id"], "content_sha256": owner["content_sha256"]}
        or record["operation_id"] != owner["operation_id"]
        or record["exact_hwnd"] != owner["hwnd"]
        or record["process_identity"] != owner["process_identity"]
        or record["screenshot_sha256"] != owner["screenshot_sha256"]
        or record["uia_root_identity"] != owner["uia_root_identity"]
        or record["pre_raw_identity_sha256"]
        != record["post_raw_identity_sha256"]
        or record["artifact_is_authorization"] is not False
        or record["execute_binding_enabled"] is not False
        or record["display_only"] is not True
    ):
        raise ValueError("owned window snapshot has stale HWND or process lineage")
    return record


def _capture_window_binding(
    owner: Mapping[str, object], uia_snapshot: Mapping[str, object]
) -> dict[str, object]:
    window = uia_snapshot.get("window")
    if (
        not isinstance(window, Mapping)
        or window.get("handle") != owner["hwnd"]
        or window.get("process_id") != owner["process_identity"]["pid"]
    ):
        raise ValueError("UIA snapshot window/HWND process lineage is stale")
    rect = owner.get("window_rect")
    if not isinstance(rect, Mapping):
        raise ValueError("owned window rectangle is missing")
    return {
        "window_binding_id": str(owner["owner_id"]),
        "process_id": int(owner["process_identity"]["pid"]),
        "process_name": str(window["process_name"]),
        "rect": deepcopy(dict(rect)),
    }


def _capture_source(
    *,
    source_kind: str,
    evidence_ref: Mapping[str, object],
    identity: Mapping[str, object],
    run_id: str,
    window_binding: Mapping[str, object],
) -> dict[str, object]:
    return {
        "source_kind": source_kind,
        "capture_lineage_ref": deepcopy(identity["capture_lineage_ref"]),
        "run_id": run_id,
        "workflow_revision": 0,
        "window_binding": deepcopy(dict(window_binding)),
        "evidence_contract_version": "provider_safe_result_v1",
        "evidence_ref": deepcopy(dict(evidence_ref)),
    }


def _seal_omni_parents(
    *, project_root: Path, capture_lineage_ref: Mapping[str, object], capture_id: str
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    store = UEIObjectStore(root=project_root / "artifacts" / "uei-shadow-store")
    token = sha256((capture_id + ":omni").encode()).hexdigest()[:24]
    request_ref = store.put(seal_immutable({
        "contract_version": "screen_parse_request_v1",
        "request_id": f"request/benchmark-v2-omni/{token}",
        "capture_lineage_ref": deepcopy(dict(capture_lineage_ref)),
        "requested_profiles": [{
            "provider_id": _OMNI_PROVIDER_ID,
            "profile_id": _OMNI_PROFILE_ID,
            "mode": "Shadow",
        }],
        "privacy_policy": "restricted",
        "requester_id": "server",
    }))
    registration_ref = store.put(seal_immutable({
        "contract_version": "trusted_provider_registration_v1",
        "registration_id": "registration/benchmark-v2/omniparser/v2",
        "provider_id": _OMNI_PROVIDER_ID,
        "profile_ids": [_OMNI_PROFILE_ID],
        "enabled": True,
        "allowed_modes": ["Shadow"],
        "allowed_privacy_policies": ["restricted"],
        "egress_policy": "local_only",
        "wire_payload_policy": "restricted_store_only",
        "safe_payload_limits": deepcopy(_SAFE_LIMITS),
        "required_conformance_suite": "uei-v1-static-projection",
    }))
    manifest_ref = store.put(seal_immutable({
        "contract_version": "provider_manifest_v1",
        "manifest_id": "manifest/benchmark-v2/omniparser/v2",
        "provider_id": _OMNI_PROVIDER_ID,
        "provider_version": _OMNI_PROVIDER_VERSION,
        "profiles": [{
            "profile_id": _OMNI_PROFILE_ID,
            "operation": "screen_parse",
            "input_contract": "screen_parse_request_v1",
            "output_contract": "provider_safe_result_v1",
            "declared_output_kinds": ["element", "icon"],
            "supported_coordinate_spaces": ["capture_pixel_xyxy"],
            "supports_capture_artifact": True,
            "privacy_capabilities": ["restricted"],
            "mode_allowlist": ["Shadow"],
        }],
    }))
    return request_ref, registration_ref, manifest_ref


_PRODUCTION_RUNTIME = _BenchmarkV2ProductionRuntime(
    project_root=_PROJECT_ROOT,
    authority_root=_AUTHORITY_ROOT,
)


def get_production_benchmark_v2_runtime() -> BenchmarkV2ProductionRuntimePort:
    return _PRODUCTION_RUNTIME


__all__ = [
    "BenchmarkV2ProductionRuntimePort",
    "BenchmarkV2ScreenGroupIterator",
    "get_production_benchmark_v2_runtime",
]
