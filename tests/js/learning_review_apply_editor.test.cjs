const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const source = fs.readFileSync(path.join(__dirname, "../../app/web_panel/panel.js"), "utf8");
const html = fs.readFileSync(path.join(__dirname, "../../app/web_panel/index.html"), "utf8");
test("learning review render binds dynamically inserted region/action preview buttons", () => {
  const start = source.indexOf("function renderLearningDraftReview(review)");
  const end = source.indexOf("function clearLearningDraftReviewDisplay", start);
  const body = source.slice(start, end);
  assert.match(body, /bindLearningDraftPreviewButtons\(\$\("learningDraftReviewRegions"\)\)/);
  assert.match(body, /bindLearningDraftPreviewButtons\(\$\("learningDraftReviewActions"\)\)/);
});
test("image inspector uses mandatory open_apply_flow taxonomy", () => {
  assert.match(html, /value="open_apply_flow"/);
  assert.doesNotMatch(html, /value="open_flow"/);
});
