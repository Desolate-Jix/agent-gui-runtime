"""CLI for the deliberately offline-first simple-native diagnostic."""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def _arguments() -> argparse.Namespace:
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('preflight','replay','actual'), default='preflight')
    parser.add_argument('--config', type=Path, default=ROOT/'configs/benchmarks/simple_native_provider_smoke_v1.json')
    parser.add_argument('--artifact-dir', type=Path)
    parser.add_argument('--replay-dir', type=Path)
    parser.add_argument('--operator-approved-model-start', action='store_true')
    return parser.parse_args()

def _config(path: Path) -> dict[str, object]:
    value=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value,dict) or value.get('contract_version') != 'simple_native_provider_smoke_v1': raise ValueError('simple-native config is invalid')
    screens=value.get('screens')
    if not isinstance(screens,list) or [item.get('case_id') if isinstance(item,dict) else None for item in screens] != [f'case-{i:03d}' for i in range(1,6)]: raise ValueError('config must contain exactly five regression cases')
    if sum(len(item.get('target_ids',[])) for item in screens if isinstance(item,dict)) != 25: raise ValueError('config must contain exactly 25 targets')
    return value

def preflight(config: dict[str, object]) -> None:
    for screen in config['screens']:
        assert isinstance(screen,dict)
        path=ROOT/str(screen['path'])
        if not path.is_file(): raise ValueError(f'screenshot missing: {path}')
        actual=sha256(path.read_bytes()).hexdigest()
        if actual != screen.get('sha256'): raise ValueError(f'screenshot sha256 mismatch: {path}')
        if 'holdout' in path.as_posix().lower(): raise ValueError('holdout is forbidden')
    provider=config.get('provider')
    if not isinstance(provider,dict) or 'gold' in json.dumps(provider).lower(): raise ValueError('provider configuration leaks scorer data')

def _cases(config: dict[str, object]):
    from app.learn.hybrid.simple_native_smoke import ProviderCase
    result=[]
    for screen in config['screens']:
        assert isinstance(screen,dict); width,height=screen['image_size']
        candidates=[{'candidate_id':f"candidate/{screen['case_id']}/{i}", 'bbox_original':[10+i*10,10,19+i*10,20], 'active':True} for i in range(5)]
        result.append(ProviderCase(case_id=screen['case_id'], image_path=ROOT/screen['path'], image_size=(width,height), targets=tuple(screen['target_ids']), runtime_request={'screenshot':{'image_size':{'width':width,'height':height}},'candidates':candidates}))
    return result

def _replay_slots(replay_dir: Path):
    from app.learn.hybrid.simple_native_smoke import SimpleNativeSlots
    for name in ('omni.jsonl','qwen.jsonl','vista.jsonl'):
        if not (replay_dir/name).is_file(): raise ValueError(f'replay fixture missing: {name}')
    return SimpleNativeSlots(omni=lambda _: {'items':[{'bbox':[0.0,0.0,1.0,1.0],'type':'text','content':'replay','interactivity':True}]}, qwen=lambda _, projection: {'bindings':[{'i':x['i'],'role':'button','label':'replay','status':'BOUND','confidence':0.5} for x in projection['candidates']]}, vista=lambda _, __: '[500,500]')

def main() -> int:
    args=_arguments()
    try:
        config=_config(args.config); preflight(config)
        if args.mode == 'preflight': print('preflight: validated five regression screens; no model callers constructed'); return 0
        if args.mode == 'actual':
            if not args.operator_approved_model_start: raise ValueError('actual requires --operator-approved-model-start')
            raise ValueError('actual requires current user approval; model callers are not constructed by default')
        if args.artifact_dir is None or args.replay_dir is None: raise ValueError('replay requires --artifact-dir and --replay-dir')
        from app.learn.hybrid.simple_native_smoke import run_simple_native_regression_diagnostic
        artifact=run_simple_native_regression_diagnostic(cases=_cases(config),slots=_replay_slots(args.replay_dir),artifact_dir=args.artifact_dir)
        print(f'replay: {artifact.path}')
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(str(error),file=sys.stderr); return 2
if __name__ == '__main__': raise SystemExit(main())
