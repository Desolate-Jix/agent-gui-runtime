from __future__ import annotations

import argparse
import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def bind_support_to_manifest(
    *,
    manifest_path: str | Path,
    case_id: str,
    support_path: str | Path,
    out_path: str | Path,
    json_stdout: bool = False,
    validate_only: bool = False,
) -> dict[str, Any]:
    manifest_path = Path(manifest_path)
    support_path = Path(support_path)
    out_path = Path(out_path)
    manifest = _read_json(manifest_path)
    support = _read_json(support_path)
    cases = manifest.get("cases") if isinstance(manifest.get("cases"), list) else []
    target_index = next((index for index, item in enumerate(cases) if str(item.get("case_id") or "") == case_id), -1)
    if target_index < 0:
        return _emit(
            {
                "status": "rejected",
                "failure_category": "case_not_found",
                "case_id": case_id,
                "manifest_path": str(manifest_path),
            },
            json_stdout=json_stdout,
        )
    target = cases[target_index]
    screenshot_path = _resolve_path(str(target.get("screenshot_path") or ""), base=manifest_path.parent)
    validity = _support_validity(payload=support, screenshot_path=screenshot_path, support_path=support_path)
    if validity.get("status") != "checksum_match":
        result = {
            "status": "rejected",
            "failure_category": str(validity.get("failure_category") or validity.get("status") or "support_not_bindable"),
            "case_id": case_id,
            "manifest_path": str(manifest_path),
            "support_path": str(support_path),
            "validity": validity,
        }
        return _emit(result, json_stdout=json_stdout)
    if validate_only:
        result = {
            "status": "validated",
            "bindable": True,
            "case_id": case_id,
            "manifest_path": str(manifest_path),
            "support_path": str(support_path),
            "validity": validity,
            "safety": {
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
                "no_dispatch": True,
            },
        }
        return _emit(result, json_stdout=json_stdout)
    updated = deepcopy(manifest)
    updated_cases = updated.get("cases") if isinstance(updated.get("cases"), list) else []
    updated_cases[target_index]["supplemental_sources_path"] = str(support_path)
    updated_cases[target_index]["supplemental_sources_binding"] = {
        "status": "bound_by_checksum",
        "support_type": str(support.get("support_type") or "unknown"),
        "screenshot_sha256": validity.get("screenshot_sha256"),
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "no_dispatch": True,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {
        "status": "bound",
        "case_id": case_id,
        "manifest_path": str(manifest_path),
        "out_path": str(out_path),
        "support_path": str(support_path),
        "validity": validity,
        "safety": {
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "no_dispatch": True,
        },
    }
    return _emit(result, json_stdout=json_stdout)


def _support_validity(*, payload: dict[str, Any], screenshot_path: Path, support_path: Path) -> dict[str, Any]:
    if not screenshot_path.exists():
        return {
            "status": "screenshot_missing",
            "failure_category": "screenshot_missing",
            "screenshot_path": str(screenshot_path),
            "support_path": str(support_path),
        }
    expected = _support_checksum(payload)
    if not expected:
        return {
            "status": "checksum_not_declared",
            "failure_category": "checksum_not_declared",
            "screenshot_path": str(screenshot_path),
            "support_path": str(support_path),
        }
    actual = _sha256_file(screenshot_path)
    if actual != expected:
        return {
            "status": "stale_fixture",
            "failure_category": "stale_supplemental_sources",
            "expected_screenshot_sha256": expected,
            "actual_screenshot_sha256": actual,
            "screenshot_path": str(screenshot_path),
            "support_path": str(support_path),
        }
    if not _has_sources(payload):
        return {
            "status": "sources_missing",
            "failure_category": "support_sources_missing",
            "screenshot_sha256": actual,
            "screenshot_path": str(screenshot_path),
            "support_path": str(support_path),
        }
    return {
        "status": "checksum_match",
        "screenshot_sha256": actual,
        "screenshot_path": str(screenshot_path),
        "support_path": str(support_path),
    }


def _support_checksum(payload: dict[str, Any]) -> str:
    direct = str(payload.get("screenshot_sha256") or "").strip().lower()
    if len(direct) == 64:
        return direct
    screenshot = payload.get("screenshot") if isinstance(payload.get("screenshot"), dict) else {}
    nested = str(screenshot.get("sha256") or "").strip().lower()
    return nested if len(nested) == 64 else ""


def _has_sources(payload: dict[str, Any]) -> bool:
    sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
    if sources:
        return True
    observe_bundle = payload.get("observe_bundle") if isinstance(payload.get("observe_bundle"), dict) else {}
    return isinstance(observe_bundle.get("sources"), dict) and bool(observe_bundle.get("sources"))


def _resolve_path(value: str, *, base: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    repo_relative = (PROJECT_ROOT / path).resolve()
    if repo_relative.exists():
        return repo_relative
    return (base / path).resolve()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _emit(result: dict[str, Any], *, json_stdout: bool) -> dict[str, Any]:
    if json_stdout:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--support", required=True)
    parser.add_argument("--out")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not args.validate_only and not args.out:
        parser.error("--out is required unless --validate-only is set")
    bind_support_to_manifest(
        manifest_path=args.manifest,
        case_id=args.case_id,
        support_path=args.support,
        out_path=args.out or "__validate_only_no_output__.json",
        json_stdout=args.json,
        validate_only=args.validate_only,
    )


if __name__ == "__main__":
    main()
