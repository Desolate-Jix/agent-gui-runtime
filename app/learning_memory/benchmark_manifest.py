"""本机基准候选的不可变清单及来源校验。"""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
import math
from pathlib import Path, PurePosixPath
import re


FAMILIES = ("query_verify", "unique_row_detail", "current_detail_downstream")
SCHEMA = "workflow_benchmark_manifest.v1"
_SPEC_KEYS = {"benchmark_id", "model", "cases", "artifacts"}
_CASE_KEYS = {"case_id", "task_family", "variation", "cohort", "seed", "inputs",
              "success_rule", "timeout_seconds", "cold_or_warm", "is_negative", "routes"}
_SOURCES = {"local", "agent_current", "agent_delegate", "external_api"}
_VARIATIONS = {"stable", "unseen", "layout", "ambiguous", "negative", "recovery"}
_COHORTS = {"scored", "learning", "warmup"}
_CASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SCORING = "app/learning_memory/benchmark_scoring.py"
_FIXTURE = "tests/fixtures/learning_workflow_app.py"


def digest(value) -> str:
    """用无空格、排序键的 UTF-8 JSON 字节计算 SHA256。"""
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    return sha256(encoded).hexdigest()


def _file_hash(path: Path) -> str:
    try:
        return sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise ValueError(f"benchmark file missing or unreadable: {path}") from error


def _source_files(root: Path) -> dict[str, str]:
    paths = set()
    for directory in (root / "app", root / "scripts"):
        if directory.is_dir():
            paths.update(path for path in directory.rglob("*.py") if path.is_file())
    for path in (root / "pyproject.toml", root / _FIXTURE, *root.glob("requirements*.txt")):
        if path.is_file():
            paths.add(path)
    result = {path.relative_to(root).as_posix(): _file_hash(path) for path in paths}
    if _SCORING not in result:
        raise ValueError("benchmark scoring source missing")
    return dict(sorted(result.items()))


def _success_rule(value):
    if not isinstance(value, dict) or set(value) != {"all"} or not isinstance(value["all"], list) or not value["all"]:
        raise ValueError("success_rule requires nonempty all conditions")
    for condition in value["all"]:
        if not isinstance(condition, dict) or set(condition) != {"path", "equals"}:
            raise ValueError("success_rule condition requires path and equals")
        path = condition["path"]
        if not isinstance(path, list) or not path or any(
                not ((isinstance(part, str) and bool(part)) or (type(part) is int and part >= 0))
                for part in path):
            raise ValueError("success_rule path requires nonempty string or nonnegative integer parts")
        try:
            digest(condition["equals"])
        except (TypeError, ValueError) as error:
            raise ValueError("success_rule equals must be a JSON value") from error


def _validate_content(value: dict, *, frozen: bool) -> None:
    expected = _SPEC_KEYS | ({"schema", "source_files", "scoring_sha256", "manifest_sha256"} if frozen else set())
    if not isinstance(value, dict) or set(value) not in (expected, expected | {"purpose"}):
        raise ValueError("benchmark manifest fields invalid")
    purpose = value.get("purpose", "formal")
    if purpose not in {"pilot", "formal"}:
        raise ValueError("benchmark purpose invalid")
    if frozen and value["schema"] != SCHEMA:
        raise ValueError("benchmark manifest schema invalid")
    if not isinstance(value["benchmark_id"], str) or not value["benchmark_id"].strip():
        raise ValueError("benchmark_id must be nonempty")
    model = value["model"]
    if (not isinstance(model, dict) or set(model) != {"source", "model", "config_digest"}
            or not isinstance(model["source"], str) or model["source"] not in _SOURCES
            or not isinstance(model["model"], str)
            or not model["model"].strip() or not isinstance(model["config_digest"], str)
            or not _SHA.fullmatch(model["config_digest"])):
        raise ValueError("benchmark model identity invalid")
    cases = value["cases"]
    if not isinstance(cases, list):
        raise ValueError("benchmark cases must be a list")
    seen = set()
    quota = Counter()
    b_quota = Counter()
    warmups = Counter()
    for case in cases:
        if not isinstance(case, dict) or set(case) not in (_CASE_KEYS, _CASE_KEYS | {"c_workflow"}):
            raise ValueError("benchmark case fields invalid")
        if "c_workflow" in case:
            from .benchmark_provenance import validate_binding
            validate_binding(case["c_workflow"])
        case_id = case["case_id"]
        if not isinstance(case_id, str) or not _CASE_ID.fullmatch(case_id) or case_id in seen:
            raise ValueError("benchmark case_id must be globally unique legal ASCII")
        seen.add(case_id)
        family, variation, cohort = case["task_family"], case["variation"], case["cohort"]
        if (not isinstance(family, str) or family not in FAMILIES
                or not isinstance(variation, str) or variation not in _VARIATIONS
                or not isinstance(cohort, str) or cohort not in _COHORTS):
            raise ValueError("benchmark case family, variation, or cohort invalid")
        if type(case["seed"]) is not int or case["seed"] < 0:
            raise ValueError("benchmark seed must be a nonnegative integer")
        if not isinstance(case["inputs"], dict) or not case["inputs"]:
            raise ValueError("benchmark inputs must be a nonempty object")
        try:
            digest(case["inputs"])
        except (TypeError, ValueError) as error:
            raise ValueError("benchmark inputs must contain JSON values") from error
        _success_rule(case["success_rule"])
        timeout = case["timeout_seconds"]
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("benchmark timeout_seconds must be finite and positive")
        if case["cold_or_warm"] not in {"cold", "warm"}:
            raise ValueError("benchmark cold_or_warm invalid")
        if type(case["is_negative"]) is not bool or case["is_negative"] != (variation in {"negative", "recovery"}):
            raise ValueError("benchmark negative/recovery cases must be separately classified")
        routes = case["routes"]
        if (not isinstance(routes, list) or len(routes) not in (2, 3)
                or any(not isinstance(route, str) for route in routes)
                or len(routes) != len(set(routes))
                or not {"A", "C"} <= set(routes) or set(routes) - {"A", "B", "C"}):
            raise ValueError("benchmark routes must include one A/C pair and optional B")
        if cohort == "scored" and not case["is_negative"]:
            quota[(family, variation)] += 1
            if "B" in routes:
                b_quota[family] += 1
        if cohort == "warmup":
            for route in routes:
                warmups[(family, route)] += 1
                if warmups[(family, route)] > 3:
                    raise ValueError("benchmark warmup limit exceeded")
    if purpose == "pilot":
        scored = [case for case in cases if case["cohort"] == "scored"]
        if (len(scored) != 6 or len({case["task_family"] for case in scored}) != 1
                or any(case["is_negative"] or set(case["routes"]) != {"A", "C"} for case in scored)
                or Counter(case["variation"] for case in scored) != {"stable": 2, "unseen": 2, "layout": 2}
                or any(set(case["routes"]) != {"A", "C"} for case in cases)
                or len({case["task_family"] for case in cases}) != 1):
            raise ValueError("benchmark pilot requires one family and six positive 2/2/2 A/C pairs")
    elif any(quota[(family, variation)] < needed for family in FAMILIES
           for variation, needed in (("stable", 8), ("unseen", 6), ("layout", 6))) or any(
            b_quota[family] < 5 for family in FAMILIES):
        raise ValueError("benchmark scored case quota incomplete")
    artifacts = value["artifacts"]
    if not isinstance(artifacts, list):
        raise ValueError("benchmark artifacts must be a list")
    artifact_fields = {"kind", "path", "version"} | ({"sha256"} if frozen else set())
    for item in artifacts:
        if (not isinstance(item, dict) or set(item) != artifact_fields
                or not isinstance(item["kind"], str)
                or item["kind"] not in {"workflow", "recipe", "runtime_config"}
                or not isinstance(item["path"], str) or not Path(item["path"]).is_absolute()
                or not isinstance(item["version"], str) or not item["version"].strip()):
            raise ValueError("benchmark artifact descriptor invalid")
        if frozen and (not isinstance(item["sha256"], str) or not _SHA.fullmatch(item["sha256"])):
            raise ValueError("benchmark artifact digest invalid")
    for case in cases:
        if "c_workflow" in case:
            binding = case["c_workflow"]
            matching = [item for item in artifacts if item["kind"] == "workflow"
                        and Path(item["path"]).resolve() == Path(binding["artifact_path"]).resolve()
                        and item["version"] == binding["program_id"]]
            if len(matching) != 1:
                raise ValueError("benchmark_c_workflow_artifact_binding_invalid")
    if frozen:
        sources = value["source_files"]
        if not isinstance(sources, dict) or _SCORING not in sources:
            raise ValueError("benchmark source files invalid")
        for path, checksum in sources.items():
            parts = PurePosixPath(path).parts if isinstance(path, str) else ()
            if (not parts or ".." in parts or path.startswith("/") or "\\" in path
                    or not (path.startswith("app/") and path.endswith(".py")
                            or path.startswith("scripts/") and path.endswith(".py")
                            or path in {"pyproject.toml", _FIXTURE}
                            or re.fullmatch(r"requirements[^/]*\.txt", path))
                    or not isinstance(checksum, str) or not _SHA.fullmatch(checksum)):
                raise ValueError("benchmark source file entry invalid")
        if value["scoring_sha256"] != sources[_SCORING]:
            raise ValueError("benchmark scoring digest mismatch")
        checksum = value["manifest_sha256"]
        if not isinstance(checksum, str) or not _SHA.fullmatch(checksum) or checksum != digest({
                key: item for key, item in value.items() if key != "manifest_sha256"}):
            raise ValueError("benchmark manifest checksum changed")


def freeze_manifest(spec: dict, *, root: Path, destination: Path) -> dict:
    _validate_content(spec, frozen=False)
    root = Path(root).resolve()
    sources = _source_files(root)
    artifacts = []
    for item in spec["artifacts"]:
        path = Path(item["path"])
        if not path.is_file():
            raise ValueError(f"benchmark artifact missing: {path}")
        artifacts.append({**item, "sha256": _file_hash(path)})
    for case in spec["cases"]:
        if "c_workflow" in case:
            from .benchmark_provenance import inspect_program
            binding = case["c_workflow"]
            try:
                program = json.loads(Path(binding["artifact_path"]).read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise ValueError("benchmark_c_workflow_artifact_unavailable") from error
            inspect_program(binding, program)
    manifest = {**spec, "artifacts": artifacts, "schema": SCHEMA, "source_files": sources,
                "scoring_sha256": sources[_SCORING]}
    manifest["manifest_sha256"] = digest(manifest)
    _validate_content(manifest, frozen=True)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    return manifest


def load_manifest(path: Path) -> dict:
    try:
        with Path(path).open("r", encoding="utf-8") as stream:
            manifest = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("benchmark manifest unavailable") from error
    _validate_content(manifest, frozen=True)
    return manifest


def verify_candidate(manifest: dict, *, root: Path) -> None:
    _validate_content(manifest, frozen=True)
    actual = _source_files(Path(root).resolve())
    if actual != manifest["source_files"] or actual[_SCORING] != manifest["scoring_sha256"]:
        raise ValueError("benchmark candidate source changed")
    for item in manifest["artifacts"]:
        if _file_hash(Path(item["path"])) != item["sha256"]:
            raise ValueError(f"benchmark artifact changed: {item['path']}")


__all__ = ["FAMILIES", "digest", "freeze_manifest", "load_manifest", "verify_candidate"]
