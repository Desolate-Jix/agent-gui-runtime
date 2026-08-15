const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const indexSource = fs.readFileSync(
  path.join(__dirname, "../../app/web_panel/index.html"),
  "utf8",
);
const panelSource = fs.readFileSync(
  path.join(__dirname, "../../app/web_panel/panel.js"),
  "utf8",
);

function sectionEndOutsideParent(source, parentId, childId) {
  const parentStart = source.indexOf(`id="${parentId}"`);
  const childStart = source.indexOf(`id="${childId}"`);
  assert.notEqual(parentStart, -1, `${parentId} must exist`);
  assert.notEqual(childStart, -1, `${childId} must exist`);
  assert.ok(childStart > parentStart, `${childId} must remain in the learning panel`);

  const beforeChild = source.slice(parentStart, childStart);
  const tags = beforeChild.match(/<\/?section\b[^>]*>/gi) || [];
  let depth = 0;
  for (const tag of tags) {
    if (/^<section\b/i.test(tag)) depth += 1;
    else depth -= 1;
  }
  return { childStart, stillNested: depth > 0 };
}

test("operational memory controls are hidden independently from legacy review UI", () => {
  const child = indexSource.slice(
    indexSource.indexOf("id=\"learningOperationalMemoryPanel\"") - 100,
    indexSource.indexOf("id=\"learningOperationalMemoryPanel\"") + 60,
  );
  assert.match(child, /<section[^>]*\bid="learningOperationalMemoryPanel"[^>]*\bhidden\b/);
  assert.equal(
    sectionEndOutsideParent(indexSource, "learningDraftReviewPanel", "learningOperationalMemoryPanel").stillNested,
    false,
  );
});

test("memory handoff reveals and focuses only the operational memory panel", () => {
  const start = panelSource.indexOf("function openInterfaceWorkflowMemoryVerification");
  const end = panelSource.indexOf("async function loadInterfaceWorkflowReview", start);
  assert.notEqual(start, -1, "memory handoff function must exist");
  assert.notEqual(end, -1, "memory handoff function boundary must exist");
  const source = panelSource.slice(start, end);
  assert.match(source, /learningOperationalMemoryPanel/);
  assert.match(source, /\.hidden\s*=\s*false/);
  assert.match(source, /scrollIntoView\(\{ behavior: "smooth", block: "start" \}\)/);
  assert.doesNotMatch(source, /learningDraftReviewPanel[^\n]*hidden\s*=\s*false/);
});
