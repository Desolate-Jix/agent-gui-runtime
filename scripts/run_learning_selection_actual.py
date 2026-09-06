"""已知静态样例的真实 Omni → GUIActor → 审核草稿，无动作调用。"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.learn.hybrid.static_capture import seal_static_capture_bundle
from app.learn.recognition.uei.omniparser_shadow_adapter import TrustedOmniParserConfiguration
from app.learn.workflow_service import run_learning_selection_actual_no_action


def _copy_exact(source: Path, target: Path) -> None:
    raw = source.read_bytes()
    if target.exists() and target.read_bytes() != raw:
        raise ValueError("existing static input differs")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(raw)


def _verify_known_case(case: dict, manifest_raw: bytes) -> None:
    """本轮入口只接受已核验公共十例，不自行引入新留出集。"""
    catalog = json.loads((ROOT / "configs/learning_selection_public_cases.json").read_text(encoding="utf-8"))
    if sha256(manifest_raw).hexdigest() != catalog["manifest_sha256"]:
        raise ValueError("manifest is not the pinned existing public regression")
    matched = [item for item in catalog["cases"] if item["case_id"] == case.get("request_id")]
    if len(matched) != 1 or any(case.get("request", {}).get(key) != matched[0][key]
                               for key in ("goal", "capture_sha256", "source_width", "source_height")):
        raise ValueError("case is not the pinned existing public regression")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-json", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--refinement-mode", choices=("never", "conditional", "always"), default="conditional")
    parser.add_argument("--omni-assets-root", type=Path, default=Path("D:/agent-gui-runtime"))
    parser.add_argument("--artifact-root", type=Path, default=Path("E:/") / "\u6a21\u578b\u6d4b\u8bd5")
    args = parser.parse_args()
    case = json.loads(args.case_json.read_text(encoding="utf-8-sig"))
    manifest_raw = args.manifest.read_bytes()
    _verify_known_case(case, manifest_raw)
    request = case["request"]
    source = Path(request["image_path"])
    digest = sha256(source.read_bytes()).hexdigest()
    if digest != request["capture_sha256"]:
        raise ValueError("static case image hash differs")
    image = ROOT / "artifacts/screenshots/learning-selection-static" / (digest + source.suffix.lower())
    _copy_exact(source, image)
    manifest = json.loads(manifest_raw.decode("utf-8-sig"))
    manifest_digest = sha256(manifest_raw).hexdigest()
    manifest_path = ROOT / "artifacts/static-manifests" / (manifest_digest + ".json")
    _copy_exact(args.manifest, manifest_path)
    run_id = "selection-actual-" + uuid4().hex
    bundle = seal_static_capture_bundle(
        project_root=ROOT, image_path=image, run_id=run_id, workflow_revision=0,
        static_asset={"case_id": case["request_id"], "dataset": manifest["dataset"], "revision": manifest["revision"],
                      "source_manifest_ref": {"relative_path": manifest_path.relative_to(ROOT).as_posix(), "sha256": manifest_digest}},
    )
    assets = args.omni_assets_root.resolve()
    config = TrustedOmniParserConfiguration(
        interpreter=assets / "tools/omniparser-v2.0.1/.venv/Scripts/python.exe",
        worker_script=ROOT / "scripts/run_uei_omniparser_shadow_worker.py",
        code_path=assets / "tools/omniparser-v2.0.1",
        weights_path=assets / "models/omniparser/v2.0.1/weights",
        cache_path=Path("~/.cache/huggingface/hub").expanduser(),
    )
    result = run_learning_selection_actual_no_action(
        project_root=ROOT, run_id=run_id, workflow_revision=0, capture_bundle_ref=bundle["bundle_ref"],
        image_path=image, target_text=request["goal"], omni_configuration=config,
        artifact_root=args.artifact_root, out_dir=args.out, refinement_mode=args.refinement_mode,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["outcome"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
