"""Closed-stdin child entrypoint for private Benchmark-v2 scoring."""
from __future__ import annotations
import argparse,json,os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from app.learn.hybrid.benchmark_scorer_v2 import _score_private_child

def main()->int:
    parser=argparse.ArgumentParser(); parser.add_argument("--closed-stdin",action="store_true",required=True); parser.parse_args()
    try:
        envelope=json.loads(sys.stdin.read())
        fields={"private_manifest_path","prediction_run_path","lifecycle_path","private_output_path","public_ref_path"}
        if not isinstance(envelope,dict) or set(envelope)!=fields: raise ValueError("closed stdin invalid")
        public=_score_private_child(child_capability=os.environ.get("BENCHMARK_V2_SCORER_CHILD_CAPABILITY",""),**{k:Path(v) for k,v in envelope.items()})
        stdout={k:public[k] for k in ("status","score_ref","content_sha256")}
        print(json.dumps(stdout,ensure_ascii=False,sort_keys=True,separators=(",",":")))
        return 0
    except Exception:
        print("ERROR: private scoring failed closed; sensitive details redacted",file=sys.stderr); return 2
if __name__=="__main__": raise SystemExit(main())
