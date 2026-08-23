const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const {
  buildInterfaceAssetLibraryRows,
} = require("../../app/web_panel/learning_workflow_review.js");

const html = fs.readFileSync(
  path.join(__dirname, "../../app/web_panel/index.html"),
  "utf8",
);

function node({
  node_id,
  review_status = "needs_human_review",
  agent_usable = false,
  agent_eligibility_reason = "human_review_required",
  source_path,
} = {}) {
  return {
    node_id,
    display_name: node_id,
    review_status,
    reviewed_by_human: agent_usable,
    agent_usable,
    agent_eligibility_reason,
    editable_review_source_path: source_path,
  };
}

test("asset library rows expose one contextual action and fail-closed review status", () => {
  const rows = buildInterfaceAssetLibraryRows({
    applications: {
      "web:example.test": {
        application_identity: { name: "Example" },
        workflow_ids: ["reviewed_flow", "pending_flow", "stop_flow", "stale_flow", "shared_a", "shared_b"],
      },
    },
    workflows: {
      reviewed_flow: {
        goal: "Reviewed",
        review_groups: { reviewed: [node({
          node_id: "reviewed",
          review_status: "human_approved",
          agent_usable: true,
          agent_eligibility_reason: "human_reviewed_current_revision",
          source_path: "artifacts/reviews/reviewed.json",
        })], unreviewed: [] },
      },
      pending_flow: {
        goal: "Pending",
        review_groups: { reviewed: [], unreviewed: [node({
          node_id: "pending",
          source_path: "artifacts/reviews/pending.json",
        })] },
      },
      stop_flow: {
        goal: "Stop",
        review_groups: { reviewed: [], unreviewed: [node({
          node_id: "stop",
          review_status: "needs_learning",
          source_path: "artifacts/reviews/stop.json",
        })] },
      },
      stale_flow: {
        goal: "Stale",
        review_groups: { reviewed: [], unreviewed: [node({
          node_id: "stale",
          review_status: "human_approved",
          agent_eligibility_reason: "human_review_revision_mismatch",
          source_path: "artifacts/reviews/stale.json",
        })] },
      },
      shared_a: {
        goal: "Shared A",
        review_groups: { reviewed: [], unreviewed: [node({
          node_id: "shared",
          source_path: "artifacts/reviews/shared.json",
        })] },
      },
      shared_b: {
        goal: "Shared B",
        review_groups: { reviewed: [], unreviewed: [node({
          node_id: "shared",
          source_path: "artifacts/reviews/shared.json",
        })] },
      },
    },
  }, [{
    source_path: "artifacts/learning-runs/run/standalone.json",
    screen_summary: "Standalone",
  }]);

  const byId = Object.fromEntries(rows.map((row) => [row.node_id || row.source_path, row]));
  assert.deepEqual(
    [byId.reviewed.status_kind, byId.reviewed.primary_action],
    ["reviewed_current", "open_workflow"],
  );
  assert.deepEqual(
    [byId.pending.status_kind, byId.pending.primary_action],
    ["needs_human_review", "open_workflow"],
  );
  assert.deepEqual(
    [byId.stop.status_kind, byId.stop.primary_action],
    ["needs_learning", "open_workflow"],
  );
  assert.deepEqual(
    [byId.stale.status_kind, byId.stale.primary_action],
    ["review_stale", "open_workflow"],
  );
  assert.deepEqual(
    [byId.shared.status_kind, byId.shared.primary_action],
    ["needs_human_review", "choose_workflow"],
  );
  assert.deepEqual(
    [byId["artifacts/learning-runs/run/standalone.json"].status_kind,
      byId["artifacts/learning-runs/run/standalone.json"].primary_action],
    ["needs_human_review", "attach_workflow"],
  );
});

test("panel exposes one interface asset library rather than reviewed and unreviewed pages", () => {
  assert.match(html, /id="interfaceAssetLibraryPage"/);
  assert.match(html, /id="interfaceWorkflowAssetList"/);
  assert.match(html, />界面资产</);
  assert.match(html, /审核状态决定知识能否复用，但不授予执行权/);
  assert.doesNotMatch(html, /id="interfaceAssetUnreviewedPage"/);
  assert.doesNotMatch(html, /id="interfaceAssetReviewedPage"/);
  assert.doesNotMatch(html, /id="interfaceAssetUnreviewedTab"/);
  assert.doesNotMatch(html, /id="interfaceAssetReviewedTab"/);
});
