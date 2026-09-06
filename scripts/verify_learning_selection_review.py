"""通过既有 API 验证实际选择草稿；测试修订不是用户最终确认。"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--simulate-review", action="store_true")
    parser.add_argument("--label", default="")
    args = parser.parse_args()
    output = (ROOT / args.out).resolve()
    if not output.is_relative_to(ROOT):
        raise ValueError("verification output escaped project root")
    output.mkdir(parents=True, exist_ok=False)
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    def post(endpoint, payload, name):
        response = client.post(endpoint, json=payload)
        response.raise_for_status()
        value = response.json()
        (output / (name + ".json")).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        if not value.get("success"):
            raise ValueError(f"{endpoint}: {value.get('error')}")
        return value["data"]

    loaded = post("/panel/load_learning_draft_review", {"source_path": args.trial, "discover_related_sidecars": False}, "loaded")
    projection = loaded["hybrid_review_projection"]
    assert projection["execution_origin"] == "actual_model"
    selected = next(item for item in projection["candidates"] if item["selection"] is not None)
    original = deepcopy(selected["model_proposal"])
    report = {"model_origin": "actual_model", "trial_path": args.trial, "initial_state": projection["learning_state"],
              "automated_review_simulation": args.simulate_review, "user_confirmed": False,
              "artifact_is_authorization": False, "execute_binding_enabled": False}
    if args.simulate_review:
        if not args.label.strip():
            raise ValueError("simulation label is required")
        expected = loaded["hybrid_review_projection_ref"]
        pending = post("/panel/save_learning_draft_review", {"source_path": args.trial, "review_patch": {
            "hybrid_review_decisions": [], "expected_hybrid_review_projection_ref": expected}}, "pending-save")
        assert pending["validation_status"] == "blocked_missing_semantics"
        assert not pending.get("runtime_path_graph_candidate_path")
        x1, y1, x2, y2 = selected["model_proposal"]["bbox_original"]
        bbox = [x1 + 1, y1 + 1, x2 - 1, y2 - 1]
        decisions = [
            {"decision_id": "decision/automated-roundtrip/rebox", "decision_type": "rebox", "candidate_id": selected["candidate_id"], "bbox": bbox},
            {"decision_id": "decision/automated-roundtrip/semantic", "decision_type": "semantic_edit", "candidate_id": selected["candidate_id"],
             "semantics": {"role": "button", "label": args.label, "description": "自动化验收模拟修订；不是用户最终确认"}},
        ]
        saved = post("/panel/save_learning_draft_review", {"source_path": args.trial, "review_patch": {
            "hybrid_review_decisions": decisions, "expected_hybrid_review_projection_ref": expected}}, "reviewed-save")
        path = saved["reviewed_template_candidate_path"]
        reloaded = post("/panel/load_learning_draft_review", {"source_path": path, "discover_related_sidecars": False}, "reloaded")
        after = reloaded["hybrid_review_projection"]
        updated = next(item for item in after["candidates"] if item["candidate_id"] == selected["candidate_id"])
        assert updated["model_proposal"] == original
        assert updated["reviewed_geometry"]["bbox"] == bbox
        assert updated["reviewed_semantics"]["label"] == args.label
        code = "from app.learn.draft_review import load_learning_draft_review; import json,sys; print(json.dumps(load_learning_draft_review(sys.argv[1],project_root=sys.argv[2])['hybrid_review_projection'],ensure_ascii=False))"
        fresh = subprocess.run([sys.executable, "-c", code, path, str(ROOT)], env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                               cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True)
        (output / "fresh-process-projection.json").write_text(fresh.stdout, encoding="utf-8")
        assert json.loads(fresh.stdout) == after
        graph = json.loads((ROOT / saved["runtime_path_graph_candidate_path"]).read_text(encoding="utf-8"))
        assert any(item.get("label") == args.label for item in graph["regions"])
        assert graph["states"] == [] and graph["action_templates"] == []
        assert graph["execute_binding_enabled"] is False
        report.update(reviewed_template_candidate_path=path, fresh_process_equal=True,
                      original_model_proposal_unchanged=True, learning_regions_consumed=True,
                      state_and_action_semantics="not_fabricated", missing_semantics_negative="blocked_missing_semantics")
    (output / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
