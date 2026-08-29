"""Rebuild the public Benchmark-v2 regression probe-authority projection."""

from __future__ import annotations

import base64
import binascii
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping
from urllib.parse import unquote

from app.learn.hybrid.benchmark_v2_contracts import BENCHMARK_RELEASE_ID
from app.learn.hybrid.benchmark_v2_lifecycle import (
    read_benchmark_v2_attempt_journal,
    validate_benchmark_v2_lifecycle_probe_receipt_v2,
)
from app.learn.hybrid.benchmark_v2_predictions import (
    validate_benchmark_v2_accepted_regression_score_input_v2,
)
from app.learn.hybrid.benchmark_v2_public_score import (
    MAX_BASE64_DECODE_DEPTH,
    MAX_CONTAINER_DEPTH,
    MAX_DECODED_BYTES,
    MAX_PERCENT_DECODE_DEPTH,
    MAX_STRING_UTF8_BYTES,
    MAX_VISITED_NODES,
    scan_benchmark_v2_public_value,
)


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_PROVIDERS = ("omni", "qwen", "vista")
_KINDS = ("cancel", "timeout")
_ZERO_SHA256 = "0" * 64
_LEDGER_CONTRACT = "portfolio_hybrid_benchmark_v2_ledger_event_envelope_v2"
_ATTEMPT_CONTRACT = "benchmark_v2_runner_attempt_ref_v1"
_ATTEMPT_PAYLOAD_CONTRACT = "benchmark_v2_runner_regression_attempt_payload_v1"
_CLEANUP_PAYLOAD_CONTRACT = "benchmark_v2_runner_cleanup_payload_v1"
_RESULT_PAYLOAD_CONTRACT = "benchmark_v2_runner_result_payload_v1"
_RESULT_CONTRACT = "benchmark_v2_runner_probe_result_v2"
_RECEIPT_CONTRACT = "benchmark_v2_lifecycle_probe_receipt_v2"
_SUMMARY_CONTRACT = "benchmark_v2_runner_probe_summary_v2"
_PRE_RESULT_CONTRACT = "benchmark_v2_probe_ledger_pre_result_verified_projection_v1"
_HORIZON_CONTRACT = "benchmark_v2_probe_ledger_horizon_verified_projection_v1"
_BUNDLE_CONTRACT = "benchmark_v2_regression_probe_authority_bundle_v1"
_SAFETY = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
    "display_only": True,
}
_RUNNER_SAFETY = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
}
_ZERO_COUNTS = {
    "service_operations": 0,
    "windows": 0,
    "providers": 0,
    "listeners": 0,
    "leases": 0,
}
_ATTEMPT_FIELDS = {
    "contract_version", "attempt_id", "partition", "mode", "provider_id",
    "artifact_is_authorization", "execute_binding_enabled", "content_sha256",
}
_PRE_RESULT_FIELDS = {
    "contract_version", "artifact_id", "benchmark_release_id", "partition",
    "provider_id", "probe_kind", "attempt_ref", "raw_prefix_sha256",
    "through_cleanup_terminal_sequence", "through_cleanup_terminal_envelope_sha256",
    "result_terminal_sequence", "result_terminal_envelope_sha256", "verified",
    "safety", "content_sha256",
}
_HORIZON_FIELDS = {
    "contract_version", "artifact_id", "benchmark_release_id", "partition",
    "probe_kind", "raw_prefix_sha256", "through_result_terminal_sequence",
    "through_result_terminal_envelope_sha256", "attempts", "selected_attempt_refs",
    "verified", "safety", "content_sha256",
}
_BUNDLE_FIELDS = {
    "contract_version", "artifact_id", "benchmark_release_id", "partition",
    "provider_manifest_ref", "provider_corpus_ref", "accepted_run_ref",
    "selection_policy", "required_matrix", "probe_ledger_horizon_refs",
    "probe_cells", "status", "safety", "content_sha256",
}
_ACCEPTED_FIELDS = {
    "contract_version", "content_sha256", "benchmark_release_id", "partition",
    "corpus_parent_ref", "provider_manifest_ref", "provider_corpus_ref",
    "selection_policy", "attempt_ref", "attempt_ledger_ref",
    "automatic_prediction_ref", "selected_lifecycle_ref",
    "verified_parent_projections", "prediction_run_envelope",
    "lifecycle_bundle_envelope", "safety",
}
_RESULT_FIELDS = {
    "contract_version", "attempt_ref", "attempt_dir", "provider_id", "probe_kind",
    "body_ref", "cleanup_receipt_ref", "lifecycle_probe_receipt_ref", "status",
    "artifact_is_authorization", "execute_binding_enabled", "content_sha256",
}
_SUMMARY_FIELDS = {
    "contract_version", "benchmark_release_id", "partition", "probe_kind",
    "collection_policy", "attempts", "status", "artifact_is_authorization",
    "execute_binding_enabled", "content_sha256",
}
_LAST_REBUILT_PROJECTIONS: tuple[dict[str, object], ...] = ()
_ATTEMPT_ID_RE = re.compile(r"^attempt-[A-Za-z0-9][A-Za-z0-9._-]*$")
_RAW_PUBLIC_TOKEN_RE = re.compile(
    r"(?:^|[/\\_.:-])(?:gold|private|observer|process|socket|listener|lease|pid)"
    r"(?:$|[/\\_.:-])",
    re.IGNORECASE,
)
_RAW_PUBLIC_FIELD_RE = re.compile(
    r"(?:^|_)(?:observer(?:_identity)?|process(?:_identity|_identities)?|socket"
    r"|listener|lease|owner_journal|attempt_dir)(?:$|_)",
    re.IGNORECASE,
)
_STANDARD_BASE64_RE = re.compile(r"^[A-Za-z0-9+/]*={0,2}$")
_URLSAFE_BASE64_RE = re.compile(r"^[A-Za-z0-9_-]*={0,2}$")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _pretty_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def _content_sha256(value: Mapping[str, object]) -> str:
    return hashlib.sha256(
        _canonical_bytes(
            {key: deepcopy(item) for key, item in value.items() if key != "content_sha256"}
        )
    ).hexdigest()


def _sealed(value: object, *, name: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    item = deepcopy(dict(value))
    digest = item.get("content_sha256")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or digest != digest.casefold()
        or any(character not in "0123456789abcdef" for character in digest)
        or _content_sha256(item) != digest
    ):
        raise ValueError(f"{name} content SHA differs")
    return item


def _decode_json(raw: bytes, *, name: str, pretty: bool) -> dict[str, object]:
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{name} is not canonical UTF-8 JSON") from error
    expected = _pretty_bytes(decoded) if pretty else _canonical_bytes(decoded) + b"\n"
    if not isinstance(decoded, Mapping) or raw != expected:
        raise ValueError(f"{name} is not canonical JSON")
    return _sealed(decoded, name=name)


def _read_json(path: Path, *, name: str, pretty: bool) -> tuple[dict[str, object], bytes]:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise ValueError(f"{name} fixed file is missing")
    raw = resolved.read_bytes()
    return _decode_json(raw, name=name, pretty=pretty), raw


def _is_reparse(path: Path) -> bool:
    candidate = Path(path)
    if candidate.is_symlink():
        return True
    try:
        attributes = int(getattr(candidate.lstat(), "st_file_attributes", 0))
    except OSError:
        return False
    return bool(attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)))


def _require_ordinary_path(path: Path, *, name: str, kind: str) -> Path:
    absolute = Path(os.path.abspath(path))
    existing = absolute if absolute.exists() or _is_reparse(absolute) else absolute.parent
    for candidate in (existing, *existing.parents):
        if _is_reparse(candidate):
            raise ValueError(f"{name} traverses a symlink, junction, or reparse point")
    if absolute.resolve(strict=False) != absolute:
        raise ValueError(f"{name} resolves through an alias")
    if kind == "file" and not absolute.is_file():
        raise ValueError(f"{name} fixed file is missing")
    if kind == "directory" and not absolute.is_dir():
        raise ValueError(f"{name} directory is missing")
    return absolute


def _ref(value: Mapping[str, object]) -> dict[str, str]:
    return {
        "id": str(value["artifact_id"]),
        "content_sha256": str(value["content_sha256"]),
    }


def _attempt_ref(value: object, *, provider: str, kind: str) -> dict[str, object]:
    attempt = _sealed(value, name="probe attempt ref")
    if (
        set(attempt) != _ATTEMPT_FIELDS
        or attempt.get("contract_version") != _ATTEMPT_CONTRACT
        or attempt.get("partition") != "regression"
        or attempt.get("mode") != f"{kind}_probe"
        or attempt.get("provider_id") != provider
        or not isinstance(attempt.get("attempt_id"), str)
        or _ATTEMPT_ID_RE.fullmatch(str(attempt["attempt_id"])) is None
        or attempt.get("artifact_is_authorization") is not False
        or attempt.get("execute_binding_enabled") is not False
    ):
        raise ValueError("probe attempt ref contract differs")
    return attempt


def _public_attempt_ref(attempt: Mapping[str, object]) -> dict[str, str]:
    return {
        "id": "runner-attempt/" + str(attempt["attempt_id"]),
        "content_sha256": str(attempt["content_sha256"]),
    }


def _seal_projection(
    *, contract_version: str, prefix: str, semantic_payload: Mapping[str, object]
) -> dict[str, object]:
    semantic = {
        "contract_version": contract_version,
        **deepcopy(dict(semantic_payload)),
    }
    semantic_sha = hashlib.sha256(
        contract_version.encode("utf-8") + b"\0" + _canonical_bytes(semantic)
    ).hexdigest()
    item: dict[str, object] = {
        "artifact_id": f"{prefix}/{semantic_sha}",
        **semantic,
    }
    item["content_sha256"] = _content_sha256(item)
    return item


def _load_provider_inputs(
    provider_manifest_path: Path,
) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    from app.learn.hybrid.benchmark_v2_predictions import _parse_provider_inputs

    manifest_path = Path(provider_manifest_path).resolve()
    if manifest_path.name != "benchmark-v2-provider-manifest.json":
        raise ValueError("provider manifest basename differs")
    corpus_path = manifest_path.parent / "provider-corpus.v2.json"
    return _parse_provider_inputs(
        provider_manifest_bytes=manifest_path.read_bytes(),
        provider_corpus_bytes=corpus_path.read_bytes(),
    )


def _validate_accepted(
    path: Path,
    *,
    manifest_ref: Mapping[str, object],
    corpus_ref: Mapping[str, object],
    provider_manifest_bytes: bytes,
    provider_corpus_bytes: bytes,
) -> tuple[dict[str, object], bytes]:
    accepted, raw = _read_json(path, name="accepted regression run", pretty=True)
    corpus_parent = corpus_ref.get("source_parent_ref")
    attempt = accepted.get("attempt_ref")
    if (
        set(accepted) != _ACCEPTED_FIELDS
        or accepted.get("contract_version")
        != "benchmark_v2_accepted_regression_score_input_v2"
        or accepted.get("benchmark_release_id") != BENCHMARK_RELEASE_ID
        or accepted.get("partition") != "regression"
        or accepted.get("selection_policy")
        != "first_complete_lifecycle_verified_attempt"
        or accepted.get("provider_manifest_ref") != dict(manifest_ref)
        or accepted.get("provider_corpus_ref") != dict(corpus_ref)
        or accepted.get("corpus_parent_ref") != corpus_parent
        or accepted.get("safety") != _SAFETY
        or not isinstance(attempt, Mapping)
        or set(attempt) != {"id", "content_sha256"}
    ):
        raise ValueError("accepted regression release, manifest, corpus, or attempt join differs")
    public_attempt_id = attempt.get("id")
    if not isinstance(public_attempt_id, str) or not public_attempt_id.startswith(
        "runner-attempt/"
    ):
        raise ValueError("accepted regression attempt ref is invalid")
    attempt_id = public_attempt_id.removeprefix("runner-attempt/")
    if _ATTEMPT_ID_RE.fullmatch(attempt_id) is None:
        raise ValueError("accepted regression attempt identifier is invalid")
    attempt_root = _require_ordinary_path(
        Path(path).resolve().parent / "attempts",
        name="accepted regression attempt root",
        kind="directory",
    )
    attempt_dir = _require_ordinary_path(
        attempt_root / attempt_id,
        name="accepted regression attempt directory",
        kind="directory",
    )
    if attempt_dir.parent != attempt_root or attempt_dir.name != attempt_id:
        raise ValueError("accepted regression attempt directory is not the fixed child")
    fixed_paths = {
        name: _require_ordinary_path(
            attempt_dir / name,
            name=f"accepted regression {name}",
            kind="file",
        )
        for name in ("body.json", "result.json", "cleanup.json")
    }
    validated = validate_benchmark_v2_accepted_regression_score_input_v2(
        accepted,
        actual_body_bytes=fixed_paths["body.json"].read_bytes(),
        actual_result_bytes=fixed_paths["result.json"].read_bytes(),
        cleanup_receipt_bytes=fixed_paths["cleanup.json"].read_bytes(),
        expected_attempt_dir=attempt_dir,
        provider_manifest_bytes=provider_manifest_bytes,
        provider_corpus_bytes=provider_corpus_bytes,
    )
    if validated != accepted:
        raise ValueError("canonical accepted regression validator changed the root")
    return validated, raw


def _validate_file_ref(
    value: object,
    *,
    expected_path: Path,
    name: str,
    pretty: bool,
) -> tuple[dict[str, object], bytes]:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"path", "file_sha256", "content_sha256"}
    ):
        raise ValueError(f"{name} file ref is invalid")
    path = Path(expected_path).resolve()
    if value.get("path") != str(path):
        raise ValueError(f"{name} does not reference its fixed file")
    item, raw = _read_json(path, name=name, pretty=pretty)
    if (
        value.get("file_sha256") != hashlib.sha256(raw).hexdigest()
        or value.get("content_sha256") != item.get("content_sha256")
    ):
        raise ValueError(f"{name} file bytes differ")
    return item, raw


@dataclass
class _AttemptState:
    attempt: dict[str, object]
    attempt_dir: Path
    opened_sequence: int
    observed_state: str = "opened"
    body: dict[str, object] | None = None
    cleanup: dict[str, object] | None = None
    cleanup_sequence: int | None = None
    cleanup_envelope: dict[str, object] | None = None
    result_sequence: int | None = None
    result_envelope: dict[str, object] | None = None


@dataclass(frozen=True)
class _Candidate:
    provider: str
    kind: str
    state: _AttemptState
    result: dict[str, object]
    result_raw: bytes
    receipt: dict[str, object]
    receipt_raw: bytes


@dataclass(frozen=True)
class _KindSelection:
    kind: str
    candidates: dict[str, _Candidate]
    states: tuple[_AttemptState, ...]
    raw_lines: tuple[bytes, ...]
    cutoff_sequence: int
    cutoff_envelope: dict[str, object]


@dataclass(frozen=True)
class BenchmarkV2ProbeAuthorityValidation:
    bundle: dict[str, object]
    profile_sha256_by_id: dict[str, str]


def _payload_fields(event_type: str) -> set[str]:
    common = {
        "contract_version", "attempt_ref", "attempt_dir", "mode", "provider_id",
        "status", "artifact_is_authorization", "execute_binding_enabled", "content_sha256",
    }
    if event_type == "regression_attempt":
        return common | {"output_ref"}
    if event_type == "cleanup":
        return common | {"cleanup_receipt_ref", "resource_counts"}
    return common | {"output_ref"}


def _read_result_candidate(
    *,
    output_ref: object,
    state: _AttemptState,
    provider: str,
    kind: str,
) -> tuple[dict[str, object], bytes, dict[str, object], bytes]:
    result_path = state.attempt_dir / "result.json"
    result, result_raw = _validate_file_ref(
        output_ref,
        expected_path=result_path,
        name="first complete probe result",
        pretty=False,
    )
    if (
        set(result) != _RESULT_FIELDS
        or result.get("contract_version") != _RESULT_CONTRACT
        or result.get("attempt_ref") != state.attempt
        or result.get("attempt_dir") != str(state.attempt_dir)
        or result.get("provider_id") != provider
        or result.get("probe_kind") != kind
        or result.get("status") != "terminal"
        or result.get("artifact_is_authorization") is not False
        or result.get("execute_binding_enabled") is not False
        or not isinstance(result.get("lifecycle_probe_receipt_ref"), Mapping)
        or set(result["lifecycle_probe_receipt_ref"])
        != {"contract_version", "file_sha256", "content_sha256"}
    ):
        raise ValueError("first complete probe result is invalid")
    if state.body is None or state.cleanup is None:
        raise ValueError("first complete result lacks body or cleanup predecessor")
    if (
        result.get("body_ref")
        != {"content_sha256": state.body["content_sha256"]}
        or result.get("cleanup_receipt_ref")
        != {"content_sha256": state.cleanup["content_sha256"]}
    ):
        raise ValueError("first complete probe result parent join differs")
    receipt_path = state.attempt_dir / "lifecycle-probe-receipt.json"
    receipt, receipt_raw = _read_json(
        receipt_path, name="lifecycle probe receipt", pretty=True
    )
    receipt_ref = result["lifecycle_probe_receipt_ref"]
    if (
        receipt_ref.get("contract_version") != _RECEIPT_CONTRACT
        or receipt_ref.get("file_sha256") != hashlib.sha256(receipt_raw).hexdigest()
        or receipt_ref.get("content_sha256") != receipt.get("content_sha256")
    ):
        raise ValueError("first complete lifecycle probe receipt bytes differ")
    return result, result_raw, receipt, receipt_raw


def _select_kind(ledger_path: Path, *, kind: str) -> _KindSelection:
    path = Path(ledger_path).resolve()
    if not path.is_file():
        raise ValueError(f"{kind} probe ledger fixed file is missing")
    raw = path.read_bytes()
    if not raw.endswith(b"\n"):
        raise ValueError("probe ledger is torn or not canonical")
    lines = raw.splitlines(keepends=True)
    previous = _ZERO_SHA256
    states_by_digest: dict[str, _AttemptState] = {}
    states: list[_AttemptState] = []
    candidates: dict[str, _Candidate] = {}
    cutoff: int | None = None
    cutoff_envelope: dict[str, object] | None = None
    for sequence, line in enumerate(lines):
        body = line[:-1]
        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("probe ledger prefix is not canonical JSON") from error
        if (
            not isinstance(decoded, Mapping)
            or _canonical_bytes(decoded) != body
            or set(decoded) != {"contract_version", "event", "event_sha256"}
            or decoded.get("contract_version") != _LEDGER_CONTRACT
        ):
            raise ValueError("probe ledger prefix envelope is invalid")
        envelope = deepcopy(dict(decoded))
        event = envelope.get("event")
        if (
            not isinstance(event, Mapping)
            or set(event)
            != {"partition", "sequence", "event_type", "previous_envelope_sha256", "event_payload"}
            or event.get("partition") != "regression"
            or event.get("sequence") != sequence
            or event.get("previous_envelope_sha256") != previous
            or event.get("event_type") not in {"regression_attempt", "cleanup", "result"}
            or envelope.get("event_sha256")
            != hashlib.sha256(_canonical_bytes(event)).hexdigest()
        ):
            raise ValueError("probe ledger prefix hash chain is invalid")
        event_type = str(event["event_type"])
        payload = _sealed(event.get("event_payload"), name="probe ledger event payload")
        expected_contract = {
            "regression_attempt": _ATTEMPT_PAYLOAD_CONTRACT,
            "cleanup": _CLEANUP_PAYLOAD_CONTRACT,
            "result": _RESULT_PAYLOAD_CONTRACT,
        }[event_type]
        if (
            set(payload) != _payload_fields(event_type)
            or payload.get("contract_version") != expected_contract
            or payload.get("mode") != f"{kind}_probe"
            or payload.get("provider_id") not in _PROVIDERS
            or payload.get("artifact_is_authorization") is not False
            or payload.get("execute_binding_enabled") is not False
        ):
            raise ValueError("probe ledger event payload contract differs")
        provider = str(payload["provider_id"])
        attempt = _attempt_ref(payload.get("attempt_ref"), provider=provider, kind=kind)
        attempt_dir = Path(str(payload.get("attempt_dir"))).resolve()
        if payload.get("attempt_dir") != str(attempt_dir):
            raise ValueError("probe ledger attempt directory is not canonical")
        digest = str(attempt["content_sha256"])
        state = states_by_digest.get(digest)
        if event_type == "regression_attempt" and payload.get("status") == "opened":
            if state is not None or payload.get("output_ref") is not None:
                raise ValueError("probe ledger has duplicate or invalid opened event")
            state = _AttemptState(attempt, attempt_dir, sequence)
            states_by_digest[digest] = state
            states.append(state)
        elif state is None or state.attempt != attempt or state.attempt_dir != attempt_dir:
            raise ValueError("probe ledger attempt lineage differs")
        elif event_type == "regression_attempt":
            if payload.get("status") != "body_complete" or state.observed_state != "opened":
                raise ValueError("probe ledger body transition is invalid")
            state.body, _ = _validate_file_ref(
                payload.get("output_ref"),
                expected_path=attempt_dir / "body.json",
                name="probe body",
                pretty=False,
            )
            state.observed_state = "body_complete"
        elif event_type == "cleanup":
            if (
                payload.get("status") != "terminal"
                or state.observed_state not in {"opened", "body_complete"}
                or payload.get("resource_counts") != _ZERO_COUNTS
            ):
                raise ValueError("probe ledger cleanup transition is invalid")
            state.cleanup, _ = _validate_file_ref(
                payload.get("cleanup_receipt_ref"),
                expected_path=attempt_dir / "cleanup.json",
                name="probe cleanup receipt",
                pretty=False,
            )
            state.cleanup_sequence = sequence
            state.cleanup_envelope = envelope
            state.observed_state = "cleanup"
        else:
            if payload.get("status") != "terminal" or state.observed_state != "cleanup":
                raise ValueError("probe ledger result transition is invalid")
            result, result_raw, receipt, receipt_raw = _read_result_candidate(
                output_ref=payload.get("output_ref"),
                state=state,
                provider=provider,
                kind=kind,
            )
            state.observed_state = "result"
            state.result_sequence = sequence
            state.result_envelope = envelope
            if provider not in candidates:
                candidates[provider] = _Candidate(
                    provider, kind, state, result, result_raw, receipt, receipt_raw
                )
        previous = hashlib.sha256(body).hexdigest()
        if len(candidates) == len(_PROVIDERS):
            cutoff = sequence
            cutoff_envelope = envelope
            break
    if cutoff is None or cutoff_envelope is None or set(candidates) != set(_PROVIDERS):
        raise ValueError(f"{kind} probe ledger lacks one first complete result per provider")
    return _KindSelection(
        kind,
        candidates,
        tuple(states),
        tuple(lines[: cutoff + 1]),
        cutoff,
        cutoff_envelope,
    )


def _load_lifecycle_parent_material(
    *,
    project_root: Path,
    attempt_ref: Mapping[str, object],
    attempt_dir: Path,
    provider_id: str,
    probe_kind: str,
    provider_manifest: Mapping[str, object],
) -> dict[str, object]:
    from app.learn.hybrid import benchmark_v2_runtime

    journal_path = (
        Path(project_root).resolve()
        / "runtime_state"
        / "benchmark-v2-attempts"
        / f"{attempt_ref['content_sha256']}.jsonl"
    )
    events = read_benchmark_v2_attempt_journal(
        journal_path=journal_path,
        attempt_ref=attempt_ref,
    )
    material = benchmark_v2_runtime._probe_terminal_material(
        events,
        provider_id=provider_id,
        probe_kind=probe_kind,
    )
    if not isinstance(material, Mapping):
        raise ValueError("probe lifecycle raw terminal material is unavailable")
    context = material.get("context")
    request = material.get("request")
    if not isinstance(context, Mapping) or not isinstance(request, Mapping):
        raise ValueError("probe lifecycle raw request material is unavailable")
    dispatch = benchmark_v2_runtime._read_committed_probe_dispatch_evidence(
        project_root=Path(project_root).resolve(),
        provider=provider_id,
        context_projection=context["provider_dispatch_context_projection"],
        expected_dispatch_receipt_ref=request["dispatch_receipt_ref"],
        expected_runtime_identity_ref=request["provider_runtime_attestation_ref"],
    )
    if not isinstance(dispatch, Mapping):
        raise ValueError("probe lifecycle dispatch parent is unavailable")
    cleanup, _ = _read_json(
        Path(attempt_dir) / "cleanup.json", name="probe cleanup receipt", pretty=False
    )
    stable, _ = _read_json(
        Path(attempt_dir) / "probe-stable-zero-evidence.json",
        name="probe stable-zero evidence",
        pretty=True,
    )
    trigger = material.get("trigger_observation")
    if not isinstance(trigger, Mapping):
        raise ValueError("probe trigger observation parent is unavailable")
    return {
        "stable_zero_evidence": stable,
        "cleanup_receipt": cleanup,
        "dispatch_runtime_parent": deepcopy(dict(dispatch["runtime_parent"])),
        "deadline_expiration": deepcopy(trigger.get("deadline_expiration")),
        "probe_trigger_terminal_event": deepcopy(material["terminal_event"]),
        "provider_manifest": deepcopy(dict(provider_manifest)),
    }


def _validate_raw_candidate(
    candidate: _Candidate,
    *,
    manifest: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    parents = _load_lifecycle_parent_material(
        project_root=_PROJECT_ROOT,
        attempt_ref=candidate.state.attempt,
        attempt_dir=candidate.state.attempt_dir,
        provider_id=candidate.provider,
        probe_kind=candidate.kind,
        provider_manifest=manifest,
    )
    stable = parents.get("stable_zero_evidence")
    samples = stable.get("samples") if isinstance(stable, Mapping) else None
    if (
        not isinstance(samples, list)
        or len(samples) < 3
        or any(
            not isinstance(sample, Mapping)
            or sample.get("resource_counts") != _ZERO_COUNTS
            for sample in samples
        )
    ):
        raise ValueError("probe stable-zero samples are insufficient or nonzero")
    deadline = parents.get("deadline_expiration")
    trigger = candidate.receipt.get("trigger_observation")
    if not isinstance(trigger, Mapping):
        raise ValueError("probe receipt trigger is unavailable")
    deadline_ref = trigger.get("deadline_expiration_ref")
    if candidate.kind == "cancel":
        if deadline is not None or deadline_ref is not None:
            raise ValueError("cancel probe has deadline expiration evidence")
    elif (
        not isinstance(deadline, Mapping)
        or deadline_ref != {"content_sha256": deadline.get("content_sha256")}
    ):
        raise ValueError("timeout probe deadline expiration evidence is missing")
    validated = validate_benchmark_v2_lifecycle_probe_receipt_v2(
        candidate.receipt,
        **parents,
    )
    if validated != candidate.receipt:
        raise ValueError("lifecycle probe validator changed authoritative receipt")
    return validated, parents


def _pre_result_projection(candidate: _Candidate, selection: _KindSelection) -> dict[str, object]:
    state = candidate.state
    if (
        state.cleanup_sequence is None
        or state.cleanup_envelope is None
        or state.result_sequence is None
        or state.result_envelope is None
    ):
        raise ValueError("selected probe terminal chain is incomplete")
    raw_prefix = b"".join(selection.raw_lines[: state.cleanup_sequence + 1])
    return _seal_projection(
        contract_version=_PRE_RESULT_CONTRACT,
        prefix="verified-probe-pre-result",
        semantic_payload={
            "benchmark_release_id": BENCHMARK_RELEASE_ID,
            "partition": "regression",
            "provider_id": candidate.provider,
            "probe_kind": candidate.kind,
            "attempt_ref": _public_attempt_ref(state.attempt),
            "raw_prefix_sha256": hashlib.sha256(raw_prefix).hexdigest(),
            "through_cleanup_terminal_sequence": state.cleanup_sequence,
            "through_cleanup_terminal_envelope_sha256": hashlib.sha256(
                _canonical_bytes(state.cleanup_envelope)
            ).hexdigest(),
            "result_terminal_sequence": state.result_sequence,
            "result_terminal_envelope_sha256": hashlib.sha256(
                _canonical_bytes(state.result_envelope)
            ).hexdigest(),
            "verified": True,
            "safety": deepcopy(_SAFETY),
        },
    )


def _horizon_projection(selection: _KindSelection) -> dict[str, object]:
    attempts = [
        {
            "attempt_ref": _public_attempt_ref(state.attempt),
            "provider_id": state.attempt["provider_id"],
            "observed_state": state.observed_state,
            "completion_state": (
                "complete" if state.observed_state == "result" else "incomplete"
            ),
            "result_terminal_sequence": state.result_sequence,
        }
        for state in sorted(selection.states, key=lambda item: item.opened_sequence)
    ]
    raw_prefix = b"".join(selection.raw_lines)
    return _seal_projection(
        contract_version=_HORIZON_CONTRACT,
        prefix="verified-probe-ledger-horizon",
        semantic_payload={
            "benchmark_release_id": BENCHMARK_RELEASE_ID,
            "partition": "regression",
            "probe_kind": selection.kind,
            "raw_prefix_sha256": hashlib.sha256(raw_prefix).hexdigest(),
            "through_result_terminal_sequence": selection.cutoff_sequence,
            "through_result_terminal_envelope_sha256": hashlib.sha256(
                _canonical_bytes(selection.cutoff_envelope)
            ).hexdigest(),
            "attempts": attempts,
            "selected_attempt_refs": [
                _public_attempt_ref(selection.candidates[provider].state.attempt)
                for provider in _PROVIDERS
            ],
            "verified": True,
            "safety": deepcopy(_SAFETY),
        },
    )


def _validate_summary(selection: _KindSelection) -> None:
    kind = selection.kind
    path = (
        _PROJECT_ROOT
        / "runtime_state"
        / "portfolio-hybrid-v1-1"
        / "benchmark-v2"
        / "regression"
        / f"{kind}-probes"
        / f"{kind}-probes.json"
    )
    summary, _ = _read_json(path, name=f"{kind} probe summary", pretty=False)
    expected = [selection.candidates[provider].result for provider in _PROVIDERS]
    if (
        set(summary) != _SUMMARY_FIELDS
        or summary.get("contract_version") != _SUMMARY_CONTRACT
        or summary.get("benchmark_release_id") != BENCHMARK_RELEASE_ID
        or summary.get("partition") != "regression"
        or summary.get("probe_kind") != kind
        or summary.get("collection_policy") != "one_requested_attempt_per_provider"
        or summary.get("attempts") != expected
        or summary.get("status") != "terminal"
        or summary.get("artifact_is_authorization") is not False
        or summary.get("execute_binding_enabled") is not False
    ):
        raise ValueError(f"{kind} probe summary lineage differs")


def _cell(
    candidate: _Candidate,
    *,
    receipt: Mapping[str, object],
    parents: Mapping[str, object],
    pre_result: Mapping[str, object],
    horizon: Mapping[str, object],
) -> dict[str, object]:
    operation = receipt.get("operation_ref")
    worker = operation.get("worker_ref") if isinstance(operation, Mapping) else None
    stable = receipt.get("stable_zero_observation")
    if not isinstance(operation, Mapping) or not isinstance(worker, Mapping):
        raise ValueError("probe operation and model-request lineage is unavailable")
    if not isinstance(stable, Mapping):
        raise ValueError("probe stable-zero projection is unavailable")
    deadline = parents.get("deadline_expiration")
    return {
        "provider_id": candidate.provider,
        "probe_kind": candidate.kind,
        "attempt_ref": _public_attempt_ref(candidate.state.attempt),
        "run_id": operation.get("run_id"),
        "operation_id": operation.get("operation_id"),
        "model_request_id": worker.get("model_request_id"),
        "runner_probe_result_ref": {
            "contract_version": _RESULT_CONTRACT,
            "file_sha256": hashlib.sha256(candidate.result_raw).hexdigest(),
            "content_sha256": candidate.result["content_sha256"],
        },
        "lifecycle_probe_receipt_ref": {
            "contract_version": _RECEIPT_CONTRACT,
            "file_sha256": hashlib.sha256(candidate.receipt_raw).hexdigest(),
            "content_sha256": receipt["content_sha256"],
        },
        "cleanup_receipt_ref": deepcopy(receipt["cleanup_receipt_ref"]),
        "stable_zero_ref": deepcopy(stable["evidence_ref"]),
        "ledger_pre_result_ref": _ref(pre_result),
        "ledger_horizon_ref": _ref(horizon),
        "deadline_expiration_ref": (
            None
            if deadline is None
            else {"content_sha256": deadline["content_sha256"]}
        ),
        "body_completion_state": receipt["body_completion_observation"]["state"],
        "termination_outcome": receipt["termination_observation"]["outcome"],
        "stable_zero_observations": stable["stable_zero_observations"],
        "status": "PASS",
    }


def _require_global_joins(
    cells: list[dict[str, object]],
    receipts: Mapping[tuple[str, str], Mapping[str, object]],
    *,
    accepted_attempt_ref: Mapping[str, object],
    manifest: Mapping[str, object],
) -> None:
    for field in ("attempt_ref", "run_id", "operation_id", "model_request_id"):
        values = [_canonical_bytes(cell[field]) for cell in cells]
        if len(values) != len(set(values)):
            raise ValueError(f"probe matrix {field} identities must be distinct")
    if any(cell["attempt_ref"] == dict(accepted_attempt_ref) for cell in cells):
        raise ValueError("accepted actual attempt must be distinct from every probe attempt")
    evaluation = manifest.get("evaluation_projection")
    policy = evaluation.get("provider_policy") if isinstance(evaluation, Mapping) else None
    revisions = policy.get("provider_revisions") if isinstance(policy, Mapping) else None
    if not isinstance(revisions, Mapping):
        raise ValueError("provider revision policy is unavailable")
    for provider in _PROVIDERS:
        cancel = receipts[(provider, "cancel")]["provider"]
        timeout = receipts[(provider, "timeout")]["provider"]
        if (
            cancel.get("profile_id") != timeout.get("profile_id")
            or cancel.get("profile_sha256") != timeout.get("profile_sha256")
        ):
            raise ValueError("probe provider profiles differ across cancel and timeout")
        if (
            cancel.get("provider_revision") != revisions.get(provider)
            or timeout.get("provider_revision") != revisions.get(provider)
        ):
            raise ValueError("probe provider revision differs from manifest policy")


def _validate_public_probe_authority(value: object) -> None:
    """递归拒绝公共 probe authority 中的路径、私有值与原始运行时身份。"""

    if not isinstance(value, Mapping):
        raise ValueError("probe authority public value is not an object")
    scanned = deepcopy(dict(value))
    frozen_paths = (
        ("provider_manifest_ref", "benchmark-v2-provider-manifest.json"),
        ("provider_corpus_ref", "provider-corpus.v2.json"),
    )
    for field, expected in frozen_paths:
        ref = scanned.get(field)
        if not isinstance(ref, Mapping) or ref.get("relative_path") != expected:
            raise ValueError("probe authority frozen provider path differs")
        sanitized = deepcopy(dict(ref))
        sanitized.pop("relative_path")
        scanned[field] = sanitized
    scan_benchmark_v2_public_value(scanned)

    state = {"nodes": 0, "decoded_bytes": 0}
    frozen_value_paths = {
        ("provider_manifest_ref", "relative_path"):
            "benchmark-v2-provider-manifest.json",
        ("provider_corpus_ref", "relative_path"): "provider-corpus.v2.json",
    }

    def bump(*, depth: int) -> None:
        state["nodes"] += 1
        if state["nodes"] > MAX_VISITED_NODES:
            raise ValueError("probe authority public scan node bound exceeded")
        if depth > MAX_CONTAINER_DEPTH:
            raise ValueError("probe authority public scan depth bound exceeded")

    def percent_variants(text: str) -> tuple[str, ...]:
        variants = [text]
        current = text
        for _index in range(MAX_PERCENT_DECODE_DEPTH):
            decoded = unquote(current)
            if decoded == current:
                return tuple(variants)
            variants.append(decoded)
            current = decoded
        if unquote(current) != current:
            raise ValueError("probe authority percent decode depth bound exceeded")
        return tuple(variants)

    def canonical_base64_bytes(text: str) -> bytes | None:
        if not text:
            return None
        unpadded = text.rstrip("=")
        if "=" in unpadded or len(text) - len(unpadded) > 2:
            return None
        remainder = len(unpadded) % 4
        if remainder == 1:
            return None
        padded = unpadded + "=" * ((4 - remainder) % 4)
        for alphabet, altchars in (
            (_STANDARD_BASE64_RE, None),
            (_URLSAFE_BASE64_RE, b"-_"),
        ):
            if alphabet.fullmatch(text) is None:
                continue
            try:
                decoded = base64.b64decode(
                    padded,
                    altchars=altchars,
                    validate=True,
                )
            except (ValueError, binascii.Error):
                continue
            encoded = (
                base64.b64encode(decoded)
                if altchars is None
                else base64.urlsafe_b64encode(decoded)
            ).decode("ascii")
            expected = encoded if text.endswith("=") else encoded.rstrip("=")
            if expected == text and encoded.rstrip("=") == unpadded:
                return decoded
        return None

    def inspect_text(
        text: str,
        *,
        path: tuple[object, ...],
        depth: int,
        decode_depth: int,
    ) -> None:
        bump(depth=depth)
        if len(text.encode("utf-8")) > MAX_STRING_UTF8_BYTES:
            raise ValueError("probe authority public string bound exceeded")
        exception = frozen_value_paths.get(path)
        if exception is not None:
            if text != exception:
                raise ValueError("probe authority frozen provider path differs")
            return
        variants = percent_variants(text)
        for variant in variants:
            scan_benchmark_v2_public_value({"value": variant})
            if _RAW_PUBLIC_TOKEN_RE.search(variant):
                raise ValueError(
                    "probe authority leaks private or raw runtime identity text"
                )
        candidate = variants[-1]
        decoded = canonical_base64_bytes(candidate)
        if decoded is None:
            return
        if decode_depth >= MAX_BASE64_DECODE_DEPTH:
            raise ValueError("probe authority base64 decode depth bound exceeded")
        state["decoded_bytes"] += len(decoded)
        if state["decoded_bytes"] > MAX_DECODED_BYTES:
            raise ValueError("probe authority decoded byte bound exceeded")
        try:
            decoded_text = decoded.decode("utf-8")
        except UnicodeDecodeError:
            return
        inspect_text(
            decoded_text,
            path=path,
            depth=depth + 1,
            decode_depth=decode_depth + 1,
        )
        try:
            parsed = json.loads(decoded_text)
        except json.JSONDecodeError:
            return
        if _canonical_bytes(parsed) != decoded:
            return
        visit(
            parsed,
            path=path,
            depth=depth + 1,
            decode_depth=decode_depth + 1,
        )

    def visit(
        item: object,
        *,
        path: tuple[object, ...],
        depth: int,
        decode_depth: int,
    ) -> None:
        bump(depth=depth)
        if isinstance(item, Mapping):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError("probe authority public key is not text")
                if _RAW_PUBLIC_FIELD_RE.search(key):
                    raise ValueError("probe authority leaks a raw runtime identity field")
                visit(
                    child,
                    path=path + (key,),
                    depth=depth + 1,
                    decode_depth=decode_depth,
                )
            return
        if isinstance(item, list):
            for index, child in enumerate(item):
                visit(
                    child,
                    path=path + (index,),
                    depth=depth + 1,
                    decode_depth=decode_depth,
                )
            return
        if isinstance(item, str):
            inspect_text(
                item,
                path=path,
                depth=depth,
                decode_depth=decode_depth,
            )

    visit(value, path=(), depth=0, decode_depth=0)


def _profile_sha256_by_id(
    receipts: Mapping[tuple[str, str], Mapping[str, object]],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for provider in _PROVIDERS:
        cancel = receipts[(provider, "cancel")].get("provider")
        timeout = receipts[(provider, "timeout")].get("provider")
        if not isinstance(cancel, Mapping) or not isinstance(timeout, Mapping):
            raise ValueError("probe runtime profile projection is unavailable")
        profile_id = cancel.get("profile_id")
        profile_sha = cancel.get("profile_sha256")
        if (
            timeout.get("profile_id") != profile_id
            or timeout.get("profile_sha256") != profile_sha
            or not isinstance(profile_id, str)
            or not profile_id
            or profile_id != profile_id.strip()
            or not isinstance(profile_sha, str)
            or re.fullmatch(r"[0-9a-f]{64}", profile_sha) is None
            or profile_id in result
        ):
            raise ValueError("probe runtime profiles are not three distinct joined profiles")
        result[profile_id] = profile_sha
    if len(result) != 3:
        raise ValueError("probe runtime profile map must contain exactly three profiles")
    return result


def _rebuild_benchmark_v2_regression_probe_authority(
    *,
    provider_manifest_path: Path,
    regression_run_ref_path: Path,
    ledger_root: Path,
) -> BenchmarkV2ProbeAuthorityValidation:
    """Independently rebuild one probe-authority bundle from the fixed raw ledgers."""

    global _LAST_REBUILT_PROJECTIONS
    manifest_path = Path(provider_manifest_path).resolve()
    corpus_path = manifest_path.parent / "provider-corpus.v2.json"
    provider_manifest_bytes = manifest_path.read_bytes()
    provider_corpus_bytes = corpus_path.read_bytes()
    manifest, _corpus, manifest_ref, corpus_ref = _load_provider_inputs(manifest_path)
    if manifest.get("benchmark_release_id") != BENCHMARK_RELEASE_ID:
        raise ValueError("provider manifest release differs")
    accepted, accepted_raw = _validate_accepted(
        Path(regression_run_ref_path),
        manifest_ref=manifest_ref,
        corpus_ref=corpus_ref,
        provider_manifest_bytes=provider_manifest_bytes,
        provider_corpus_bytes=provider_corpus_bytes,
    )
    root = Path(ledger_root).resolve()
    selections = {
        kind: _select_kind(root / "regression" / f"{kind}-probes.jsonl", kind=kind)
        for kind in _KINDS
    }
    for selection in selections.values():
        _validate_summary(selection)
    horizons = {kind: _horizon_projection(selections[kind]) for kind in _KINDS}
    pre_results: dict[tuple[str, str], dict[str, object]] = {}
    receipts: dict[tuple[str, str], dict[str, object]] = {}
    cells_by_key: dict[tuple[str, str], dict[str, object]] = {}
    for kind in _KINDS:
        selection = selections[kind]
        for provider in _PROVIDERS:
            candidate = selection.candidates[provider]
            receipt, parents = _validate_raw_candidate(candidate, manifest=manifest)
            if (
                receipt.get("benchmark_release_id") != BENCHMARK_RELEASE_ID
                or receipt.get("partition") != "regression"
                or receipt.get("probe_kind") != kind
                or receipt.get("attempt_ref") != candidate.state.attempt
                or not isinstance(receipt.get("provider"), Mapping)
                or receipt["provider"].get("provider_id") != provider
                or receipt.get("status") != "PASS"
                or receipt.get("body_completion_observation", {}).get("state")
                != "not_complete"
                or receipt.get("termination_observation", {}).get("outcome")
                != "same_incarnations_exited"
                or receipt.get("stable_zero_observation", {}).get(
                    "stable_zero_observations"
                )
                < 3
            ):
                raise ValueError("first complete lifecycle probe receipt is invalid")
            pre = _pre_result_projection(candidate, selection)
            pre_results[(provider, kind)] = pre
            receipts[(provider, kind)] = receipt
            cells_by_key[(provider, kind)] = _cell(
                candidate,
                receipt=receipt,
                parents=parents,
                pre_result=pre,
                horizon=horizons[kind],
            )
    cells = [
        cells_by_key[(provider, kind)]
        for provider in _PROVIDERS
        for kind in _KINDS
    ]
    _require_global_joins(
        cells,
        receipts,
        accepted_attempt_ref=accepted["attempt_ref"],
        manifest=manifest,
    )
    profiles = _profile_sha256_by_id(receipts)
    required_matrix = [
        [provider, kind] for provider in _PROVIDERS for kind in _KINDS
    ]
    semantic = {
        "benchmark_release_id": BENCHMARK_RELEASE_ID,
        "partition": "regression",
        "provider_manifest_ref": deepcopy(manifest_ref),
        "provider_corpus_ref": deepcopy(corpus_ref),
        "accepted_run_ref": {
            "contract_version": "benchmark_v2_accepted_regression_score_input_v2",
            "file_sha256": hashlib.sha256(accepted_raw).hexdigest(),
            "content_sha256": accepted["content_sha256"],
        },
        "selection_policy": "first_complete_verified_attempt_per_cell",
        "required_matrix": required_matrix,
        "probe_ledger_horizon_refs": [
            {"probe_kind": kind, "ledger_horizon_ref": _ref(horizons[kind])}
            for kind in _KINDS
        ],
        "probe_cells": cells,
        "status": "PASS",
        "safety": deepcopy(_SAFETY),
    }
    bundle = _seal_projection(
        contract_version=_BUNDLE_CONTRACT,
        prefix="probe-authority",
        semantic_payload=semantic,
    )
    if set(bundle) != _BUNDLE_FIELDS:
        raise ValueError("probe authority bundle is not closed")
    _validate_public_probe_authority(bundle)
    _LAST_REBUILT_PROJECTIONS = tuple(
        [pre_results[(provider, kind)] for provider in _PROVIDERS for kind in _KINDS]
        + [horizons[kind] for kind in _KINDS]
    )
    return BenchmarkV2ProbeAuthorityValidation(
        bundle=bundle,
        profile_sha256_by_id=profiles,
    )


def rebuild_benchmark_v2_regression_probe_authority(
    *,
    provider_manifest_path: Path,
    regression_run_ref_path: Path,
    ledger_root: Path,
) -> dict[str, object]:
    """Independently rebuild one public probe-authority bundle."""

    return _rebuild_benchmark_v2_regression_probe_authority(
        provider_manifest_path=provider_manifest_path,
        regression_run_ref_path=regression_run_ref_path,
        ledger_root=ledger_root,
    ).bundle


def _fixed_probe_authority_path() -> Path:
    return (
        _PROJECT_ROOT
        / "runtime_state"
        / "portfolio-hybrid-v1-1"
        / "benchmark-v2"
        / "regression"
        / "probe-authority.json"
    ).resolve()


def validate_benchmark_v2_regression_probe_authority_candidate(
    *,
    provider_manifest_path: Path,
    regression_run_ref_path: Path,
    ledger_root: Path,
    probe_authority_path: Path,
) -> BenchmarkV2ProbeAuthorityValidation:
    """重建一次并要求固定 consumer candidate 与权威字节完全相同。"""

    target = Path(probe_authority_path).resolve()
    if target != _fixed_probe_authority_path():
        raise ValueError("probe authority candidate does not match the fixed public path")
    if not target.is_file():
        raise ValueError("probe authority candidate fixed file is missing")
    candidate_raw = target.read_bytes()
    _decode_json(candidate_raw, name="probe authority candidate", pretty=True)
    rebuilt = _rebuild_benchmark_v2_regression_probe_authority(
        provider_manifest_path=provider_manifest_path,
        regression_run_ref_path=regression_run_ref_path,
        ledger_root=ledger_root,
    )
    if candidate_raw != _pretty_bytes(rebuilt.bundle):
        raise ValueError("probe authority candidate differs from authoritative bytes")
    return rebuilt


def materialize_benchmark_v2_regression_probe_authority(
    *,
    provider_manifest_path: Path,
    regression_run_ref_path: Path,
    ledger_root: Path,
    output_path: Path,
) -> dict[str, object]:
    """Write the rebuilt bundle once, or require byte-identical existing bytes."""

    target = Path(output_path).resolve()
    fixed_target = _fixed_probe_authority_path()
    if target != fixed_target:
        raise ValueError("probe authority output does not match the fixed public path")
    bundle = rebuild_benchmark_v2_regression_probe_authority(
        provider_manifest_path=provider_manifest_path,
        regression_run_ref_path=regression_run_ref_path,
        ledger_root=ledger_root,
    )
    expected = _pretty_bytes(bundle)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as stream:
            stream.write(expected)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if target.read_bytes() != expected:
            raise ValueError("existing probe authority differs from authoritative bytes")
    return bundle


__all__ = [
    "BenchmarkV2ProbeAuthorityValidation",
    "materialize_benchmark_v2_regression_probe_authority",
    "rebuild_benchmark_v2_regression_probe_authority",
    "validate_benchmark_v2_regression_probe_authority_candidate",
]
