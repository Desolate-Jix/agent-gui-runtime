const test = require("node:test");
const assert = require("node:assert/strict");

const {
  createHybridReviewState,
} = require("../../app/web_panel/learning_workflow_review.js");

function fixture() {
  return {
    contract_version: "hybrid_review_projection_v2",
    screen_facts: {
      capture_lineage_ref: { id: "capture-1", content_sha256: "ab".repeat(32) },
      displayed_image: { sha256: "cd".repeat(32), image_size: { width: 200, height: 100 } },
      warnings: ["screen_warning"],
    },
    projection_id: "hybrid-review-projection/v2/fixture",
    review_decisions: [],
    candidates: [{
      candidate_id: "candidate/abc",
      model_proposal: {
        bbox_original: [8, 18, 82, 52],
        coordinate_space: "capture_pixel_xyxy",
        qwen_binding: { role: "button", label: "Apply", description: "Open flow" },
        vista_proposal: { point: { coordinate_space: "capture_pixel_xyxy", xy: [40, 30] } },
        compact_provenance: { provider_id: "omni", source_item_id: "item-1" },
      },
      review_decisions: [],
      reviewed_geometry: { bbox: [8, 18, 82, 52], source: "model_original", revision: 0 },
      reviewed_semantics: { role: "button", label: "Apply", description: "Open flow", revision: 0 },
      human_point_proposal: null,
      tombstone: null,
      warnings: ["fusion_conflict"],
      reviewed_by_human: true,
    }],
    artifact_is_authorization: false,
    execute_binding_enabled: false,
  };
}

test("rebox preserves model bbox, appends a decision, and revokes current approval", () => {
  const state = createHybridReviewState(fixture());
  state.select("candidate/abc");
  state.rebox("candidate/abc", [10, 20, 80, 50]);

  const candidate = state.currentCandidate();
  assert.deepEqual(candidate.model_proposal.bbox_original, [8, 18, 82, 52]);
  assert.deepEqual(candidate.reviewed_geometry.bbox, [10, 20, 80, 50]);
  assert.equal(candidate.review_decisions.length, 1);
  assert.equal(candidate.review_decisions[0].decision_type, "rebox");
  assert.equal(candidate.reviewed_by_human, false);
  assert.deepEqual(state.screenFacts().warnings, ["screen_warning"]);
  assert.deepEqual(candidate.warnings, ["fusion_conflict"]);
});

test("snapshot reload preserves append-only decisions without aliasing model evidence", () => {
  const state = createHybridReviewState(fixture());
  state.rebox("candidate/abc", [10, 20, 80, 50]);
  const saved = state.snapshot();
  saved.candidates[0].model_proposal.bbox_original[0] = 999;

  assert.deepEqual(state.currentCandidate().model_proposal.bbox_original, [8, 18, 82, 52]);
  const reloaded = createHybridReviewState(state.snapshot());
  assert.deepEqual(reloaded.currentCandidate().reviewed_geometry.bbox, [10, 20, 80, 50]);
  assert.equal(reloaded.currentCandidate().review_decisions.length, 1);
});

test("semantic, point, tombstone, and add decisions preserve evidence and unique human ids", () => {
  const state = createHybridReviewState(fixture());
  state.editSemantics("candidate/abc", {
    role: "button", label: "Continue", description: "Advance",
  });
  state.proposeHumanPoint("candidate/abc", [40, 30]);
  state.tombstone("candidate/abc", "not_available");
  const first = state.add([100, 20, 140, 50], {
    role: "button", label: "Next", description: "",
  });
  state.tombstone(first.candidate_id, "deleted_by_reviewer");
  const reloaded = createHybridReviewState(state.snapshot());
  const second = reloaded.add([145, 20, 190, 50], {
    role: "button", label: "Next", description: "",
  });

  const original = reloaded.candidates().find((candidate) => candidate.candidate_id === "candidate/abc");
  assert.equal(original.reviewed_semantics.label, "Continue");
  assert.deepEqual(original.human_point_proposal.xy, [40, 30]);
  assert.deepEqual(original.model_proposal.vista_proposal.point.xy, [40, 30]);
  assert.equal(original.tombstone.reason, "not_available");
  assert.match(first.candidate_id, /^human\//);
  assert.match(second.candidate_id, /^human\//);
  assert.notEqual(first.candidate_id, second.candidate_id);
  assert.equal(reloaded.candidates().find((candidate) => candidate.candidate_id === first.candidate_id).tombstone.reason, "deleted_by_reviewer");
});

test("undo and redo rebuild derived state without rewriting model evidence", () => {
  const state = createHybridReviewState(fixture());
  state.rebox("candidate/abc", [10, 20, 80, 50]);
  state.editSemantics("candidate/abc", {
    role: "button", label: "Continue", description: "Advance",
  });

  assert.equal(state.currentCandidate().reviewed_semantics.label, "Continue");
  assert.equal(state.undo(), true);
  assert.equal(state.currentCandidate().reviewed_semantics.label, "Apply");
  assert.deepEqual(state.currentCandidate().reviewed_geometry.bbox, [10, 20, 80, 50]);
  assert.equal(state.undo(), true);
  assert.deepEqual(state.currentCandidate().reviewed_geometry.bbox, [8, 18, 82, 52]);
  assert.deepEqual(state.currentCandidate().model_proposal.bbox_original, [8, 18, 82, 52]);
  assert.equal(state.redo(), true);
  assert.deepEqual(state.currentCandidate().reviewed_geometry.bbox, [10, 20, 80, 50]);
});

test("review patch exports append-only Hybrid decisions and remains non-authorizing", () => {
  const state = createHybridReviewState(fixture());
  state.rebox("candidate/abc", [10, 20, 80, 50]);
  state.proposeHumanPoint("candidate/abc", [40, 30]);
  const patch = state.reviewPatch();

  assert.equal(patch.artifact_is_authorization, false);
  assert.equal(patch.execute_binding_enabled, false);
  assert.equal(patch.hybrid_review_decisions.length, 2);
  assert.deepEqual(patch.hybrid_review_decisions[0].bbox, [10, 20, 80, 50]);
  assert.deepEqual(patch.hybrid_review_decisions[1].human_point_proposal.xy, [40, 30]);
});
