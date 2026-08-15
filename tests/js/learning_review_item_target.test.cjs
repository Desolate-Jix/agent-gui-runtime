const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../../app/web_panel/panel.js"), "utf8");
const start = source.indexOf("function learningReviewItemId");
const end = source.indexOf("function learningDraftPreviewButton", start);
assert.notEqual(start, -1);
const harness = {};
vm.runInNewContext(`${source.slice(start, end)}; globalThis.learningReviewItemId = learningReviewItemId;`, harness);

test("learning review region edit target uses region_id over state_id", () => {
  assert.equal(harness.learningReviewItemId({ state_id: "structure_region_main_content", region_id: "fused_6_apply" }, 0, "region"), "fused_6_apply");
});

test("learning review action edit target uses action_template_id over state/action ids", () => {
  assert.equal(harness.learningReviewItemId({ state_id: "structure_region_main_content", action_id: "review_fused_6_apply", action_template_id: "fused_6_apply" }, 0, "action"), "fused_6_apply");
});
