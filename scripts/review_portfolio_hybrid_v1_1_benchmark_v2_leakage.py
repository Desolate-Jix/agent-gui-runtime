"""Create the public Benchmark-v2 leakage review."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.learn.hybrid.benchmark_v2_contracts import (  # noqa: E402
    BENCHMARK_RELEASE_ID,
    PROVIDER_MANIFEST_CONTRACT,
)
from app.learn.hybrid.benchmark_v2_provider_corpus import (  # noqa: E402
    canonical_json_bytes,
    validate_preloaded_provider_corpus,
    validate_provider_manifest,
)
from app.learn.hybrid.benchmark_v2_pathless import pathless_artifact_ref  # noqa: E402
from app.learn.hybrid.benchmark_v2_pathless import validate_pathless_recursive  # noqa: E402
from app.learn.hybrid.benchmark_v2_predictions import (  # noqa: E402
    _accepted_closure_index,
    _accepted_envelope,
    _prediction_external_refs,
    _provider_case_index,
)
from app.learn.hybrid.benchmark_v2_public_score import (  # noqa: E402
    scan_benchmark_v2_public_value,
)


CONTRACT = "benchmark_v2_leakage_review_v1"
SAFETY = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
    "display_only": True,
}
FINDING_CODES = (
    "ABSOLUTE_PATH",
    "FORBIDDEN_FIELD_NAME",
    "FORBIDDEN_LOGICAL_PATH",
    "FORBIDDEN_TEXT_FRAGMENT",
    "INVALID_BASE64_PAYLOAD",
    "SCAN_BOUND_EXCEEDED",
)
_FORBIDDEN_FIELDS = {
    "acceptable_regions",
    "annotator_identity_hash",
    "gold",
    "gold_path",
    "private_manifest_path",
    "private_output",
    "reviewer_identity_hash",
    "target_id",
}
_FORBIDDEN_TEXT = (
    "gold.v1.json",
    "corpus-manifest.v1.json",
    "benchmark_v2_privileged_projector.py",
)
_SHA = re.compile(r"[0-9a-f]{64}")
_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")
_URI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_RELATIVE_FILE = re.compile(r"(?:^|/)[^/\s]+\.[A-Za-z0-9]{1,16}(?:$|[?#])")
_IMAGE = re.compile(
    r"^tests/fixtures/portfolio_hybrid_v1_1/corpus/(regression|holdout)/case-[0-9]{3}\.png$"
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require_sha(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise ValueError(f"{name} SHA is invalid")
    return value


def _closed_ref(value: object, fields: set[str], name: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{name} is not closed")
    result = deepcopy(dict(value))
    for key, child in result.items():
        if key.endswith("sha256"):
            _require_sha(child, f"{name} {key}")
    return result


def _provider_manifest_ref(raw: bytes) -> dict[str, str]:
    return {
        "contract_version": PROVIDER_MANIFEST_CONTRACT,
        "relative_path": "benchmark-v2-provider-manifest.json",
        "file_sha256": _sha256(raw),
    }


def _accepted_run_ref(value: Mapping[str, object], raw: bytes) -> dict[str, str]:
    return {
        "contract_version": "benchmark_v2_accepted_regression_score_input_v2",
        "file_sha256": _sha256(raw),
        "content_sha256": str(value["content_sha256"]),
    }


def _validate_accepted_run(
    value: object,
    raw: bytes,
    *,
    validated_provider_corpus: Mapping[str, object] | None = None,
) -> dict[str, object]:
    fields = {
        "contract_version",
        "content_sha256",
        "benchmark_release_id",
        "partition",
        "corpus_parent_ref",
        "provider_manifest_ref",
        "provider_corpus_ref",
        "selection_policy",
        "attempt_ref",
        "attempt_ledger_ref",
        "automatic_prediction_ref",
        "selected_lifecycle_ref",
        "verified_parent_projections",
        "prediction_run_envelope",
        "lifecycle_bundle_envelope",
        "safety",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("accepted regression input is not closed")
    accepted = deepcopy(dict(value))
    if raw != _pretty_bytes(accepted):
        raise ValueError("accepted regression input bytes are not canonical")
    if (
        accepted["contract_version"]
        != "benchmark_v2_accepted_regression_score_input_v2"
        or accepted["benchmark_release_id"] != BENCHMARK_RELEASE_ID
        or accepted["partition"] != "regression"
        or accepted["selection_policy"]
        != "first_complete_lifecycle_verified_attempt"
        or accepted["safety"] != SAFETY
    ):
        raise ValueError("accepted regression input contract is invalid")
    expected = _sha256(
        _canonical_bytes(
            {key: child for key, child in accepted.items() if key != "content_sha256"}
        )
    )
    if accepted["content_sha256"] != expected:
        raise ValueError("accepted regression input content hash is invalid")
    try:
        _validate_public_envelopes(accepted)
        _validate_accepted_public_lineage(
            accepted,
            validated_provider_corpus=validated_provider_corpus,
        )
    except ValueError as error:
        raise ValueError("accepted regression public lineage is invalid") from error
    return accepted


def _validate_accepted_public_lineage(
    accepted: Mapping[str, object],
    *,
    validated_provider_corpus: Mapping[str, object] | None,
) -> None:
    prediction, prediction_ref = _accepted_envelope(
        accepted["prediction_run_envelope"], name="Task11 accepted prediction run"
    )
    lifecycle, _ = _accepted_envelope(
        accepted["lifecycle_bundle_envelope"], name="Task11 accepted lifecycle bundle"
    )
    if (
        prediction.get("contract_version") != "benchmark_v2_prediction_run_v3"
        or lifecycle.get("contract_version") != "benchmark_v2_lifecycle_bundle_v3"
    ):
        raise ValueError("accepted regression v3 contracts differ")
    prediction_by_ref, prediction_children = _accepted_closure_index(
        prediction, name="Task11 accepted prediction run"
    )
    lifecycle_by_ref, _ = _accepted_closure_index(
        lifecycle, name="Task11 accepted lifecycle bundle"
    )
    shared_contracts = {
        "benchmark_v2_runner_event_verified_projection_v1",
        "benchmark_v2_projected_attempt_ledger_v1",
    }
    prediction_shared = {
        key: envelope
        for key, (item, envelope) in prediction_by_ref.items()
        if item.get("contract_version") in shared_contracts
    }
    lifecycle_shared = {
        key: envelope
        for key, (item, envelope) in lifecycle_by_ref.items()
        if item.get("contract_version") in shared_contracts
    }
    if prediction_shared != lifecycle_shared:
        raise ValueError("accepted shared closure differs")
    parents = accepted.get("verified_parent_projections")
    parent_contracts = {
        "runner_ledger_prefix_projection_envelope": "benchmark_v2_runner_ledger_prefix_verified_projection_v1",
        "attempt_journal_projection_envelope": "benchmark_v2_attempt_journal_verified_projection_v1",
        "actual_body_projection_envelope": "benchmark_v2_actual_body_verified_projection_v1",
        "actual_result_projection_envelope": "benchmark_v2_actual_result_verified_projection_v1",
    }
    if not isinstance(parents, Mapping) or set(parents) != set(parent_contracts):
        raise ValueError("accepted verified parent set differs")
    decoded: dict[str, dict[str, object]] = {}
    parent_refs: dict[str, dict[str, object]] = {}
    for field, contract in parent_contracts.items():
        item, ref = _accepted_envelope(parents[field], name=f"Task11 {field}")
        if item.get("contract_version") != contract:
            raise ValueError("accepted verified parent contract differs")
        decoded[field] = item
        parent_refs[field] = ref
    prefix = decoded["runner_ledger_prefix_projection_envelope"]
    journal = decoded["attempt_journal_projection_envelope"]
    body = decoded["actual_body_projection_envelope"]
    result = decoded["actual_result_projection_envelope"]
    validate_pathless_recursive(
        registry_name="verified_parents_v1",
        roots=[
            parent_refs["attempt_journal_projection_envelope"],
            parent_refs["actual_result_projection_envelope"],
        ],
        envelopes=[deepcopy(dict(parents[field])) for field in parent_contracts],
        external_refs={
            "benchmark_v2_runner_ledger_prefix_verified_projection_v1.attempt_ledger_pre_result_ref": prefix["attempt_ledger_pre_result_ref"],
            "benchmark_v2_runner_ledger_prefix_verified_projection_v1.attempt_ref": prefix["attempt_ref"],
            "benchmark_v2_runner_ledger_prefix_verified_projection_v1.body_file_ref": prefix["body_file_ref"],
            "benchmark_v2_runner_ledger_prefix_verified_projection_v1.cleanup_event_projection_ref": prefix["cleanup_event_projection_ref"],
            "benchmark_v2_runner_ledger_prefix_verified_projection_v1.result_file_ref": prefix["result_file_ref"],
            "benchmark_v2_runner_ledger_prefix_verified_projection_v1.result_event_projection_ref": prefix["result_event_projection_ref"],
            "benchmark_v2_attempt_journal_verified_projection_v1.attempt_ref": journal["attempt_ref"],
            "benchmark_v2_attempt_journal_verified_projection_v1.terminal_event_ref": journal["terminal_event_ref"],
            "benchmark_v2_attempt_journal_verified_projection_v1.cleanup_projection_ref": journal["cleanup_projection_ref"],
            "benchmark_v2_actual_body_verified_projection_v1.attempt_ref": body["attempt_ref"],
            "benchmark_v2_actual_body_verified_projection_v1.pre_vista_evidence_refs": body["pre_vista_evidence_refs"],
            "benchmark_v2_actual_result_verified_projection_v1.attempt_ref": result["attempt_ref"],
            "benchmark_v2_actual_result_verified_projection_v1.cleanup_projection_ref": result["cleanup_projection_ref"],
            "benchmark_v2_actual_result_verified_projection_v1.attempt_ledger_pre_result_ref": result["attempt_ledger_pre_result_ref"],
            "benchmark_v2_actual_result_verified_projection_v1.result_event_projection_ref": result["result_event_projection_ref"],
        },
        context={},
    )
    attempt_ref = accepted["attempt_ref"]
    ledger_ref = accepted["attempt_ledger_ref"]
    automatic_ref = accepted["automatic_prediction_ref"]
    lifecycle_ref = accepted["selected_lifecycle_ref"]
    if (
        prediction.get("benchmark_release_id") != accepted["benchmark_release_id"]
        or lifecycle.get("benchmark_release_id") != accepted["benchmark_release_id"]
        or prediction.get("partition") != "regression"
        or lifecycle.get("partition") != "regression"
        or prediction.get("corpus_parent_ref") != accepted["corpus_parent_ref"]
        or prediction.get("provider_manifest_ref") != accepted["provider_manifest_ref"]
        or prediction.get("provider_corpus_ref") != accepted["provider_corpus_ref"]
        or prediction.get("attempt_ref") != attempt_ref
        or lifecycle.get("attempt_ref") != attempt_ref
        or prediction.get("projected_attempt_ledger_ref") != ledger_ref
        or lifecycle.get("projected_attempt_ledger_ref") != ledger_ref
        or prediction.get("automatic_prediction_ref") != automatic_ref
        or prediction.get("selected_lifecycle_ref") != lifecycle_ref
        or lifecycle.get("selected_lifecycle_ref") != lifecycle_ref
        or prediction.get("raw_ledger_prefix_verification_ref")
        != parent_refs["runner_ledger_prefix_projection_envelope"]
        or lifecycle.get("raw_ledger_prefix_verification_ref")
        != parent_refs["runner_ledger_prefix_projection_envelope"]
        or any(item.get("attempt_ref") != attempt_ref for item in (prefix, journal, body, result))
        or result.get("body_projection_ref")
        != parent_refs["actual_body_projection_envelope"]
        or result.get("runner_ledger_prefix_projection_ref")
        != parent_refs["runner_ledger_prefix_projection_envelope"]
        or result.get("result_event_projection_ref") != prefix.get("result_event_projection_ref")
        or result.get("attempt_ledger_pre_result_ref") != prefix.get("attempt_ledger_pre_result_ref")
        or result.get("cleanup_projection_ref") != journal.get("cleanup_projection_ref")
        or prefix.get("body_file_ref")
        != {"file_sha256": body.get("raw_file_sha256"), "content_sha256": body.get("body_content_sha256")}
        or prefix.get("result_file_ref")
        != {"file_sha256": result.get("raw_file_sha256"), "content_sha256": result.get("result_content_sha256")}
    ):
        raise ValueError("accepted top-level lineage differs")

    def resolve(
        index: Mapping[bytes, tuple[dict[str, object], dict[str, object]]],
        ref: object,
        contract: str,
    ) -> dict[str, object]:
        if not isinstance(ref, Mapping):
            raise ValueError("accepted child ref is invalid")
        found = index.get(_canonical_bytes(ref))
        if found is None or found[0].get("contract_version") != contract:
            raise ValueError("accepted child ref is unresolved")
        return found[0]

    automatic = resolve(prediction_by_ref, automatic_ref, "automatic_prediction_v3")
    ledger = resolve(
        prediction_by_ref, ledger_ref, "benchmark_v2_projected_attempt_ledger_v1"
    )
    selected = resolve(
        lifecycle_by_ref,
        lifecycle_ref,
        "benchmark_v2_lifecycle_verified_projection_v1",
    )
    result_event = resolve(
        lifecycle_by_ref,
        result["result_event_projection_ref"],
        "benchmark_v2_runner_event_verified_projection_v1",
    )
    cleanup_event = resolve(
        lifecycle_by_ref,
        prefix["cleanup_event_projection_ref"],
        "benchmark_v2_runner_event_verified_projection_v1",
    )
    terminal_event = resolve(
        lifecycle_by_ref,
        journal["terminal_event_ref"],
        "benchmark_v2_attempt_journal_terminal_event_verified_projection_v1",
    )
    cleanup = resolve(
        lifecycle_by_ref,
        result["cleanup_projection_ref"],
        "benchmark_v2_lifecycle_verified_projection_v1",
    )
    selected_parents = selected.get("parent_refs")
    cleanup_parents = cleanup.get("parent_refs")
    result_load = result_event.get("load_bearing_refs")
    cleanup_load = cleanup_event.get("load_bearing_refs")
    if (
        automatic.get("source_parent_ref") != parent_refs["actual_body_projection_envelope"]
        or ledger.get("selected_attempt_ref") != attempt_ref
        or ledger.get("selected_lifecycle_ref") != lifecycle_ref
        or ledger.get("raw_ledger_prefix_verification_ref")
        != parent_refs["runner_ledger_prefix_projection_envelope"]
        or not isinstance(selected_parents, Mapping)
        or selected_parents.get("attempt_journal_projection_ref")
        != parent_refs["attempt_journal_projection_envelope"]
        or selected_parents.get("cleanup_projection_ref") != result["cleanup_projection_ref"]
        or cleanup.get("attempt_ref") != attempt_ref
        or cleanup.get("lifecycle_kind") != "cleanup"
        or terminal_event.get("cleanup_projection_ref") != result["cleanup_projection_ref"]
        or not isinstance(cleanup_load, Mapping)
        or cleanup_load.get("cleanup_projection_ref") != result["cleanup_projection_ref"]
        or not isinstance(cleanup_parents, Mapping)
        or cleanup_load.get("cleanup_receipt_ref") != cleanup_parents.get("cleanup_receipt_ref")
        or terminal_event.get("cleanup_receipt_ref") != cleanup_parents.get("cleanup_receipt_ref")
        or not isinstance(result_load, Mapping)
        or result_load.get("result_file_ref") != prefix.get("result_file_ref")
        or result_load.get("attempt_ledger_pre_result_ref")
        != prefix.get("attempt_ledger_pre_result_ref")
    ):
        raise ValueError("accepted transitive lineage differs")
    if validated_provider_corpus is not None:
        _, cases, digest = _provider_case_index(validated_provider_corpus)
        if automatic.get("case_arm_multiset_sha256") != digest:
            raise ValueError("accepted provider case multiset differs")
        dependencies = automatic.get("provider_group_dependencies")
        if not isinstance(dependencies, list):
            raise ValueError("accepted provider dependencies differ")
        provider_groups = {
            str(item["provider_group_ref"]["id"]): deepcopy(dict(item))
            for item in dependencies
            if isinstance(item, Mapping)
            and isinstance(item.get("provider_group_ref"), Mapping)
        }
        runner_envelopes = [
            deepcopy(dict(envelope))
            for envelope, item in zip(
                prediction["sealed_artifact_envelopes"],
                prediction_children,
                strict=True,
            )
            if item.get("contract_version") in shared_contracts
        ]
        external = _prediction_external_refs(
            prediction_run=prediction,
            automatic=automatic,
            artifacts=prediction_children,
            runner_and_ledger_envelopes=runner_envelopes,
        )
        validate_pathless_recursive(
            registry_name="prediction_run_v3",
            roots=[prediction_ref],
            envelopes=[
                deepcopy(dict(accepted["prediction_run_envelope"])),
                *[
                    deepcopy(dict(item))
                    for item in prediction["sealed_artifact_envelopes"]
                ],
            ],
            external_refs=external,
            context={
                "provider_groups": provider_groups,
                "cases": cases,
                "actual_body_projection_ref": parent_refs["actual_body_projection_envelope"],
                "attempt_ref": attempt_ref,
                "raw_ledger_prefix_verification_ref": parent_refs[
                    "runner_ledger_prefix_projection_envelope"
                ],
                "projected_attempt_ledger_ref": ledger_ref,
                "selected_lifecycle_ref": lifecycle_ref,
            },
        )


def _validate_public_envelopes(value: object) -> None:
    if isinstance(value, Mapping):
        if "canonical_bytes_b64" in value:
            if set(value) != {"ref", "canonical_bytes_b64"}:
                raise ValueError("accepted public envelope is not closed")
            encoded = value["canonical_bytes_b64"]
            if not isinstance(encoded, str):
                raise ValueError("accepted public envelope encoding is invalid")
            try:
                raw = base64.b64decode(encoded, validate=True)
                decoded = json.loads(raw.decode("utf-8"))
            except (ValueError, binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("accepted public envelope encoding is invalid") from error
            if not isinstance(decoded, Mapping) or raw != _canonical_bytes(decoded):
                raise ValueError("accepted public envelope bytes are not canonical")
            try:
                decoded_ref = pathless_artifact_ref(decoded)
            except ValueError as error:
                if "unknown pathless contract" not in str(error):
                    raise
                ref = value["ref"]
                if not isinstance(ref, Mapping) or set(ref) != {
                    "id",
                    "content_sha256",
                }:
                    raise ValueError("accepted public envelope ref differs") from error
                if {
                    "artifact_id",
                    "content_sha256",
                }.issubset(decoded):
                    decoded_ref = {
                        "id": decoded["artifact_id"],
                        "content_sha256": decoded["content_sha256"],
                    }
                    expected_content = _sha256(
                        _canonical_bytes(
                            {
                                key: child
                                for key, child in decoded.items()
                                if key != "content_sha256"
                            }
                        )
                    )
                    if decoded["content_sha256"] != expected_content:
                        raise ValueError(
                            "accepted public envelope content hash differs"
                        ) from error
                else:
                    decoded_ref = dict(ref)
                    if ref["content_sha256"] != _sha256(raw):
                        raise ValueError(
                            "accepted public envelope content hash differs"
                        ) from error
            if decoded_ref != value["ref"]:
                raise ValueError("accepted public envelope ref differs")
            _validate_public_envelopes(decoded)
            return
        for child in value.values():
            _validate_public_envelopes(child)
    elif isinstance(value, list):
        for child in value:
            _validate_public_envelopes(child)


def _allowed_paths(value: object) -> dict[tuple[object, ...], str]:
    allowed: dict[tuple[object, ...], str] = {}
    if not isinstance(value, Mapping):
        return allowed
    contract = value.get("contract_version")
    if contract == PROVIDER_MANIFEST_CONTRACT:
        runtime = value.get("sealed_runtime")
        if isinstance(runtime, Mapping):
            for group in ("code_refs", "release_code_refs", "profile_refs"):
                refs = runtime.get(group)
                if isinstance(refs, list):
                    for index, ref in enumerate(refs):
                        if isinstance(ref, Mapping) and isinstance(
                            ref.get("relative_path"), str
                        ):
                            allowed[("sealed_runtime", group, index, "relative_path")] = str(
                                ref["relative_path"]
                            )
    elif contract == "portfolio_hybrid_v1_1_provider_corpus_v2":
        cases = value.get("cases")
        if isinstance(cases, list):
            for index, case in enumerate(cases):
                image = case.get("image") if isinstance(case, Mapping) else None
                path = image.get("path") if isinstance(image, Mapping) else None
                match = _IMAGE.fullmatch(path) if isinstance(path, str) else None
                if match is not None and match.group(1) == case.get("partition"):
                    allowed[("cases", index, "image", "path")] = path
    return allowed


def _decoded(value: str) -> str:
    current = value
    for _ in range(64):
        candidate = unquote(current)
        if candidate == current:
            break
        current = candidate
    return current


def _path_code(value: str, key: str) -> str | None:
    decoded = _decoded(value)
    if (
        decoded.startswith(("/", "\\\\"))
        or _DRIVE.match(decoded)
        or _URI.match(decoded)
    ):
        return "ABSOLUTE_PATH"
    if (
        "\\" in decoded
        or any(part in {".", ".."} for part in decoded.replace("\\", "/").split("/"))
        or key.casefold() == "path"
        or key.casefold().endswith("_path")
        or ("/" in decoded and _RELATIVE_FILE.search(decoded) is not None)
    ):
        return "FORBIDDEN_LOGICAL_PATH"
    return None


def _collect_public_leakage_codes(value: object) -> list[str]:
    allowed = _allowed_paths(value)
    codes: set[str] = set()
    state = {"nodes": 0, "decoded": 0}
    decoder = json.JSONDecoder()

    def visit(
        item: object,
        *,
        path: tuple[object, ...],
        depth: int,
        decode_depth: int,
        key_name: str = "",
    ) -> None:
        state["nodes"] += 1
        if state["nodes"] > 100_000 or depth > 32:
            codes.add("SCAN_BOUND_EXCEEDED")
            return
        if isinstance(item, Mapping):
            for key, child in item.items():
                if not isinstance(key, str):
                    codes.add("SCAN_BOUND_EXCEEDED")
                    continue
                visit(
                    key,
                    path=path + (key, "<key>"),
                    depth=depth + 1,
                    decode_depth=decode_depth,
                )
                if key.casefold() in _FORBIDDEN_FIELDS:
                    codes.add("FORBIDDEN_FIELD_NAME")
                child_path = path + (key,)
                if key == "canonical_bytes_b64" or key.endswith("_bytes_b64"):
                    if not isinstance(child, str) or decode_depth >= 8:
                        codes.add(
                            "SCAN_BOUND_EXCEEDED"
                            if decode_depth >= 8
                            else "INVALID_BASE64_PAYLOAD"
                        )
                        continue
                    try:
                        raw = base64.b64decode(child, validate=True)
                        text = raw.decode("utf-8")
                    except (ValueError, binascii.Error, UnicodeDecodeError):
                        codes.add("INVALID_BASE64_PAYLOAD")
                        continue
                    state["decoded"] += len(raw)
                    if state["decoded"] > 67_108_864:
                        codes.add("SCAN_BOUND_EXCEEDED")
                        continue
                    stripped = text.lstrip()
                    if stripped:
                        try:
                            parsed, end = decoder.raw_decode(stripped)
                        except json.JSONDecodeError:
                            visit(
                                text,
                                path=child_path,
                                depth=depth + 1,
                                decode_depth=decode_depth + 1,
                            )
                        else:
                            if stripped[end:].strip():
                                codes.add("INVALID_BASE64_PAYLOAD")
                            else:
                                visit(
                                    parsed,
                                    path=child_path,
                                    depth=depth + 1,
                                    decode_depth=decode_depth + 1,
                                )
                    continue
                visit(
                    child,
                    path=child_path,
                    depth=depth + 1,
                    decode_depth=decode_depth,
                    key_name=key,
                )
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(
                    child,
                    path=path + (index,),
                    depth=depth + 1,
                    decode_depth=decode_depth,
                    key_name=key_name,
                )
        elif isinstance(item, str):
            if len(item.encode("utf-8")) > 16_777_216:
                codes.add("SCAN_BOUND_EXCEEDED")
                return
            lowered = item.casefold()
            if any(fragment in lowered for fragment in _FORBIDDEN_TEXT):
                codes.add("FORBIDDEN_TEXT_FRAGMENT")
            exception = allowed.get(path)
            if (
                path[-2:] == ("provider_manifest_ref", "relative_path")
                and item == "benchmark-v2-provider-manifest.json"
            ) or (
                path[-2:] == ("provider_corpus_ref", "relative_path")
                and item == "provider-corpus.v2.json"
            ):
                exception = item
            path_code = _path_code(item, key_name)
            if path_code is not None and exception != item:
                codes.add(path_code)

    visit(value, path=(), depth=0, decode_depth=0)
    return sorted(codes)


def find_public_leakage_codes(value: object) -> list[str]:
    """Run the shared authority, then expose only Task-11 finding codes."""

    try:
        scan_benchmark_v2_public_value(value)
    except ValueError as error:
        codes = _collect_public_leakage_codes(value)
        if codes:
            return codes
        message = str(error).casefold()
        if "bound exceeded" in message:
            return ["SCAN_BOUND_EXCEEDED"]
        if any(fragment in message for fragment in ("base64", "utf-8", "trailing json")):
            return ["INVALID_BASE64_PAYLOAD"]
        if "forbidden field name" in message:
            return ["FORBIDDEN_FIELD_NAME"]
        if "forbidden text fragment" in message:
            return ["FORBIDDEN_TEXT_FRAGMENT"]
        if "filesystem or logical path" in message:
            return ["FORBIDDEN_LOGICAL_PATH"]
        return ["SCAN_BOUND_EXCEEDED"]
    return []


def build_leakage_review(
    *,
    provider_manifest_ref: Mapping[str, object],
    provider_corpus_ref: Mapping[str, object],
    accepted_run_ref: Mapping[str, object],
    finding_codes: list[str],
) -> dict[str, object]:
    codes = sorted(set(finding_codes))
    if any(code not in FINDING_CODES for code in codes):
        raise ValueError("leakage review finding code is invalid")
    body: dict[str, object] = {
        "contract_version": CONTRACT,
        "benchmark_release_id": BENCHMARK_RELEASE_ID,
        "provider_manifest_ref": deepcopy(dict(provider_manifest_ref)),
        "provider_corpus_ref": deepcopy(dict(provider_corpus_ref)),
        "accepted_run_ref": deepcopy(dict(accepted_run_ref)),
        "finding_codes": codes,
        "status": "PASS" if not codes else "FAIL",
        "safety": dict(SAFETY),
    }
    body["content_sha256"] = _sha256(_canonical_bytes(body))
    return validate_leakage_review(body)


def validate_leakage_review(value: object) -> dict[str, object]:
    fields = [
        "contract_version",
        "benchmark_release_id",
        "provider_manifest_ref",
        "provider_corpus_ref",
        "accepted_run_ref",
        "finding_codes",
        "status",
        "safety",
        "content_sha256",
    ]
    if not isinstance(value, Mapping) or set(value) != set(fields):
        raise ValueError("leakage review is not closed")
    review = deepcopy(dict(value))
    provider = _closed_ref(
        review["provider_manifest_ref"],
        {"contract_version", "relative_path", "file_sha256"},
        "leakage review provider ref",
    )
    corpus = _closed_ref(
        review["provider_corpus_ref"],
        {
            "contract_version",
            "relative_path",
            "file_sha256",
            "content_sha256",
            "source_parent_ref",
        },
        "leakage review corpus ref",
    )
    accepted = _closed_ref(
        review["accepted_run_ref"],
        {"contract_version", "file_sha256", "content_sha256"},
        "leakage review accepted ref",
    )
    parent = _closed_ref(
        corpus["source_parent_ref"],
        {"contract_version", "artifact_id", "file_sha256", "content_sha256"},
        "leakage review corpus parent ref",
    )
    corpus["source_parent_ref"] = parent
    codes = review["finding_codes"]
    if (
        review["contract_version"] != CONTRACT
        or review["benchmark_release_id"] != BENCHMARK_RELEASE_ID
        or provider["contract_version"] != PROVIDER_MANIFEST_CONTRACT
        or provider["relative_path"] != "benchmark-v2-provider-manifest.json"
        or corpus["contract_version"]
        != "portfolio_hybrid_v1_1_provider_corpus_v2"
        or corpus["relative_path"] != "provider-corpus.v2.json"
        or accepted["contract_version"]
        != "benchmark_v2_accepted_regression_score_input_v2"
        or not isinstance(codes, list)
        or any(not isinstance(code, str) or code not in FINDING_CODES for code in codes)
        or codes != sorted(set(codes))
        or review["status"] != ("PASS" if not codes else "FAIL")
        or review["safety"] != SAFETY
    ):
        raise ValueError("leakage review contract is invalid")
    expected = _sha256(
        _canonical_bytes(
            {key: child for key, child in review.items() if key != "content_sha256"}
        )
    )
    if review["content_sha256"] != expected:
        raise ValueError("leakage review content hash is invalid")
    review["provider_manifest_ref"] = provider
    review["provider_corpus_ref"] = corpus
    review["accepted_run_ref"] = accepted
    return review


def _pretty_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ).encode("utf-8") + b"\n"


def _write_new_or_identical(path: Path, raw: bytes) -> None:
    output = Path(path)
    if output.exists():
        if not output.is_file() or output.is_symlink() or output.read_bytes() != raw:
            raise FileExistsError("output exists with different bytes")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if not output.is_file() or output.is_symlink() or output.read_bytes() != raw:
            raise FileExistsError("output exists with different bytes") from None


def publish_leakage_review(
    *, output_path: Path, review: Mapping[str, object]
) -> dict[str, object]:
    validated = validate_leakage_review(review)
    raw = _pretty_bytes(validated)
    _write_new_or_identical(Path(output_path), raw)
    return {
        "content_sha256": validated["content_sha256"],
        "review_ref": {
            "contract_version": CONTRACT,
            "file_sha256": _sha256(raw),
            "content_sha256": validated["content_sha256"],
        },
        "status": validated["status"],
    }


def review_leakage(
    *, provider_manifest_path: Path, regression_run_ref_path: Path, output_path: Path
) -> dict[str, object]:
    provider_raw = Path(provider_manifest_path).read_bytes()
    try:
        provider_value = json.loads(provider_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("provider manifest is not UTF-8 JSON") from error
    if provider_raw != canonical_json_bytes(provider_value, pretty=True):
        raise ValueError("provider manifest bytes are not canonical")
    provider = validate_provider_manifest(provider_value)
    corpus_ref = deepcopy(provider["provider_corpus_ref"])
    corpus_path = Path(provider_manifest_path).parent / str(corpus_ref["relative_path"])
    corpus_raw = corpus_path.read_bytes()
    corpus = validate_preloaded_provider_corpus(
        raw=corpus_raw, expected_sha256=str(corpus_ref["file_sha256"])
    )
    if corpus["content_sha256"] != corpus_ref["content_sha256"]:
        raise ValueError("provider corpus content ref differs")
    accepted_raw = Path(regression_run_ref_path).read_bytes()
    try:
        accepted_value = json.loads(accepted_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("accepted regression input is not UTF-8 JSON") from error
    accepted = _validate_accepted_run(
        accepted_value,
        accepted_raw,
        validated_provider_corpus=corpus,
    )
    manifest_ref = _provider_manifest_ref(provider_raw)
    if (
        accepted["provider_manifest_ref"] != manifest_ref
        or accepted["provider_corpus_ref"] != corpus_ref
        or accepted["corpus_parent_ref"] != corpus_ref["source_parent_ref"]
    ):
        raise ValueError("accepted regression release lineage differs")
    findings: set[str] = set()
    for item in (provider, corpus, accepted):
        findings.update(find_public_leakage_codes(item))
    review = build_leakage_review(
        provider_manifest_ref=manifest_ref,
        provider_corpus_ref=corpus_ref,
        accepted_run_ref=_accepted_run_ref(accepted, accepted_raw),
        finding_codes=sorted(findings),
    )
    return publish_leakage_review(output_path=output_path, review=review)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--provider-manifest", required=True)
    parser.add_argument("--regression-run-ref", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    tokens = list(sys.argv[1:] if argv is None else argv)
    for flag in ("--provider-manifest", "--regression-run-ref", "--output"):
        if tokens.count(flag) > 1:
            _parser().error(f"argument {flag}: may not be repeated")
    args = _parser().parse_args(tokens)
    summary = review_leakage(
        provider_manifest_path=Path(args.provider_manifest),
        regression_run_ref_path=Path(args.regression_run_ref),
        output_path=Path(args.output),
    )
    print(_canonical_bytes(summary).decode("utf-8"))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print("benchmark v2 leakage review failed", file=sys.stderr)
        raise SystemExit(1) from None
