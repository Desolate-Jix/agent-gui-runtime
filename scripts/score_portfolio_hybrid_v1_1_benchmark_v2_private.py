"""Closed-stdin child entrypoint for private Benchmark-v2 scoring."""
from __future__ import annotations
import argparse,json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from app.learn.hybrid.benchmark_scorer_v2 import execute_closed_child_envelope

def main()->int:
    parser=argparse.ArgumentParser(); parser.add_argument("--closed-launch-handle",type=int,required=True); args=parser.parse_args()
    try:
        public=execute_closed_child_envelope(args.closed_launch_handle)
        stdout={k:public[k] for k in ("status","score_ref","content_sha256")}
        print(json.dumps(stdout,ensure_ascii=False,sort_keys=True,separators=(",",":")))
        return 0
    except Exception:
        print("ERROR: private scoring failed closed; sensitive details redacted",file=sys.stderr); return 2
if __name__=="__main__": raise SystemExit(main())
