"""CLI for the deliberately offline-first simple-native diagnostic."""
from __future__ import annotations
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from collections import deque
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PROMPTS = {'omni': 'Return official Omni items only.', 'qwen': 'Return only a bare per-goal binding array.', 'vista': 'Return only [x,y] normalized to 0..1000.'}

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
    corpus_path = ROOT / str(provider.get('provider_corpus_path') or '')
    if not corpus_path.is_file() or not isinstance(json.loads(corpus_path.read_text(encoding='utf-8')), dict): raise ValueError('provider corpus is unavailable')
    hashes=config.get('prompt_hashes')
    if not isinstance(hashes, dict) or any(hashes.get(name) != sha256(text.encode('utf-8')).hexdigest() for name,text in PROMPTS.items()): raise ValueError('prompt hash mismatch')
    limits=config.get('limits')
    if not isinstance(limits, dict) or not all(isinstance(limits.get(name),int) and limits[name] > 0 for name in ('timeout_seconds','max_output_bytes')): raise ValueError('output limits are invalid')
    for screen in config['screens']:
        if len(set(screen['target_ids'])) != 5: raise ValueError('target IDs must be unique')
        from PIL import Image
        with Image.open(ROOT / screen['path']) as image:
            if [image.width,image.height] != screen['image_size']: raise ValueError('screenshot dimensions mismatch')

def _cases(config: dict[str, object]):
    """Derive the fixed 25 provider-visible goals from the sealed provider corpus only."""
    from app.learn.hybrid.simple_native_smoke import ProviderCase
    provider = config["provider"]
    assert isinstance(provider, dict)
    corpus_path = ROOT / str(provider["provider_corpus_path"])
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    if not isinstance(corpus, dict) or corpus.get("contract_version") != "portfolio_hybrid_v1_1_provider_corpus_v2":
        raise ValueError("provider corpus identity is invalid")
    source_cases = corpus.get("cases")
    if not isinstance(source_cases, list):
        raise ValueError("provider corpus cases are invalid")
    result=[]
    for screen in config["screens"]:
        assert isinstance(screen,dict); width,height=screen["image_size"]
        selected=[item for item in source_cases if isinstance(item,dict) and item.get("partition")=="regression" and isinstance(item.get("image"),dict) and item["image"].get("path")==screen["path"]]
        selected_ids=[item.get("case_id") for item in selected]
        if selected_ids != screen["target_ids"] or len(selected) != 5 or len(set(selected_ids)) != 5:
            raise ValueError("provider corpus target identity mismatch")
        result.append(ProviderCase(
            case_id=str(screen["case_id"]),
            image_path=ROOT / str(screen["path"]),
            image_size=(width, height),
            image_sha256=str(screen["sha256"]),
            goals=tuple(str(item["goal"]) for item in selected),
        ))
    return result

def _replay_slots(replay_dir: Path):
    """Consume bounded JSONL replay evidence in call order; malformed lines fail closed."""
    from app.learn.hybrid.simple_native_smoke import SimpleNativeSlots
    def load(name: str) -> deque[object]:
        path = replay_dir / name
        if not path.is_file(): raise ValueError(f"replay fixture missing: {name}")
        try:
            values=deque(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        except json.JSONDecodeError as error: raise ValueError(f"replay fixture invalid: {name}") from error
        if not values: raise ValueError(f"replay fixture empty: {name}")
        return values
    omni,qwen,vista=load("omni.jsonl"),load("qwen.jsonl"),load("vista.jsonl")
    def take(values: deque[object], name: str) -> object:
        if not values: raise ValueError(f"replay fixture exhausted: {name}")
        return values.popleft()
    return SimpleNativeSlots(omni=lambda _: take(omni,"omni.jsonl"), qwen=lambda _, __: take(qwen,"qwen.jsonl"), vista=lambda _, __: str(take(vista,"vista.jsonl")))

def main(*, actual_slots_factory=None) -> int:
    args=_arguments()
    try:
        config=_config(args.config); preflight(config)
        if args.mode == 'preflight': print('preflight: validated five regression screens; no model callers constructed'); return 0
        if args.mode == 'actual':
            if not args.operator_approved_model_start: raise ValueError('actual requires --operator-approved-model-start')
            if args.artifact_dir is None: raise ValueError('actual requires --artifact-dir')
            if actual_slots_factory is None:
                from app.learn.hybrid.simple_native_callers import make_actual_simple_native_slots
                actual_slots_factory = make_actual_simple_native_slots
            slots = actual_slots_factory(
                config={
                    "provider": deepcopy(config["provider"]),
                    "limits": deepcopy(config["limits"]),
                },
                artifact_dir=args.artifact_dir,
            )
        else:
            if args.artifact_dir is None or args.replay_dir is None: raise ValueError('replay requires --artifact-dir and --replay-dir')
            slots = _replay_slots(args.replay_dir)
        from app.learn.hybrid.simple_native_smoke import run_simple_native_regression_diagnostic, score_simple_native_regression
        artifact=run_simple_native_regression_diagnostic(cases=_cases(config),slots=slots,artifact_dir=args.artifact_dir)
        report=score_simple_native_regression(provider_artifact=artifact, gold_path=ROOT / str(config["scorer_gold_path"]))
        (args.artifact_dir / "regression-report.json").write_text(json.dumps({"provider_artifact_sha256": report.provider_artifact_sha256, "correct_selected": report.correct_selected, "wrong_selected": report.wrong_selected, "abstained": report.abstained, "denominator": report.target_count, "regression_diagnostic_only": True, "promotion_eligible": False}, ensure_ascii=False), encoding="utf-8")
        print(f'{args.mode}: {artifact.path}')
        return 0
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        print(str(error),file=sys.stderr); return 2
if __name__ == '__main__': raise SystemExit(main())
