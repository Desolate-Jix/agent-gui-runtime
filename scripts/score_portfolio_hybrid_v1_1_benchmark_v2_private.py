"""Closed-stdin child entrypoint for private Benchmark-v2 scoring."""
from __future__ import annotations
import argparse,json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from app.learn.hybrid.benchmark_scorer_v2 import execute_closed_child_envelope,run_private_scorer

def main()->int:
    parser=argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--private-manifest")
    parser.add_argument("--prediction-run-ref")
    parser.add_argument("--private-output")
    parser.add_argument("--public-ref-output")
    parser.add_argument("--closed-launch-handle",type=int,help=argparse.SUPPRESS)
    known=("--private-manifest","--prediction-run-ref","--private-output","--public-ref-output","--closed-launch-handle")
    if any(sys.argv[1:].count(flag)>1 for flag in known): parser.error("duplicate scorer option")
    args=parser.parse_args()
    public_values=(args.private_manifest,args.prediction_run_ref,args.private_output,args.public_ref_output)
    hidden=args.closed_launch_handle is not None
    if hidden==any(value is not None for value in public_values) or (not hidden and not all(value is not None for value in public_values)): parser.error("select exactly one complete scorer mode")
    try:
        if hidden:
            public=execute_closed_child_envelope(args.closed_launch_handle)
        else:
            public=run_private_scorer(private_manifest_path=Path(args.private_manifest),prediction_run_ref_path=Path(args.prediction_run_ref),private_output_path=Path(args.private_output),public_ref_path=Path(args.public_ref_output))
        stdout={k:public[k] for k in ("status","score_ref","content_sha256")}
        print(json.dumps(stdout,ensure_ascii=False,sort_keys=True,separators=(",",":")))
        return 0
    except Exception:
        print("ERROR: private scoring failed closed; sensitive details redacted",file=sys.stderr); return 2
if __name__=="__main__": raise SystemExit(main())
