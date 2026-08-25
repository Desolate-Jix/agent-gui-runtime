"""Run only the sealed, deterministic pre-VISTA benchmark dry-run."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.learn.hybrid.benchmark import PRE_VISTA_ARM_IDS
from app.learn.hybrid.benchmark_scorer_v1 import SCORER_SCHEMA_V1


MANIFEST_TEMPLATE = ROOT / "tests/fixtures/portfolio_hybrid_v1_1/manifest.template.json"
GATE_CONFIG = ROOT / "configs/benchmarks/portfolio_hybrid_v1_1_gate.json"
BENCHMARK_PRODUCER = ROOT / "app/learn/hybrid/benchmark.py"
SCORER = ROOT / "app/learn/hybrid/benchmark_scorer_v1.py"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_dry_run_report(*, partition: str, phase: str) -> dict[str, Any]:
    if partition != "regression" or phase != "pre-vista":
        raise ValueError("Task 5A permits a regression-only dry-run before VISTA")
    required_files = (MANIFEST_TEMPLATE, GATE_CONFIG, BENCHMARK_PRODUCER, SCORER)
    missing = [str(path) for path in required_files if not path.is_file()]
    if missing:
        raise ValueError(f"sealed interface file is missing: {missing[0]}")
    gate = json.loads(GATE_CONFIG.read_text(encoding="utf-8"))
    return {
        "contract_version": "portfolio_hybrid_v1_1_benchmark_dry_run_v1",
        "benchmark_id": "portfolio-hybrid-v1-1",
        "partition": partition,
        "phase": phase,
        "dry_run": True,
        "status": "sealed_interfaces_ready_corpus_seal_pending",
        "arms": list(PRE_VISTA_ARM_IDS),
        "manifest_template_sha256": _sha256_file(MANIFEST_TEMPLATE),
        "gate_config_sha256": gate["config_sha256"],
        "gate_file_sha256": _sha256_file(GATE_CONFIG),
        "benchmark_producer_sha256": _sha256_file(BENCHMARK_PRODUCER),
        "scorer_sha256": _sha256_file(SCORER),
        "scorer_schema": SCORER_SCHEMA_V1,
        "provider_launch_count": 0,
        "prediction_count": 0,
        "holdout_prediction_count": 0,
        "owned_process_count": 0,
        "cleanup": {
            "status": "verified_no_owned_processes",
            "provider_processes_started": 0,
            "helper_processes_started": 0,
            "lease_files_created": 0,
        },
        "evidence_scope": {
            "regression_data_only": True,
            "untouched_holdout_proof": False,
            "public_private_split_frozen": True,
        },
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--partition", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.dry_run or args.partition != "regression" or args.phase != "pre-vista":
        parser.error("Task 5A permits a regression-only dry-run before VISTA")
    try:
        report = build_dry_run_report(partition=args.partition, phase=args.phase)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
