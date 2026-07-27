# Learning Review Workbench Design

## Goal

Replace the current path-and-diagnostics-first Learning Draft presentation with a review-first workspace where an operator can:

1. find a historical draft immediately;
2. understand the interface sequence and PathGraph without reading JSON;
3. inspect the boxed screenshot for each interface node;
4. correct the selected interface in place;
5. save a reviewed draft without granting Execute authorization.

The first delivery targets the existing developer panel. It does not create the separate end-user settings application yet.

## Primary Layout

The Learning Draft view becomes a three-column review workbench.

### Left: Draft Library

The left column is always visible and contains:

- search by application, page name, and source window;
- filters for review status and date;
- historical draft entries grouped by application and workflow;
- a concise status for each entry: unreviewed, edited, review-ready, invalid, or missing evidence;
- one clear `New learning run` command.

Each entry shows a human-readable name, screenshot thumbnail, capture time, interface count, and review status. Raw source paths are not primary labels.

Selecting an entry loads its review data and workflow graph. Selection must never mix evidence from the previously selected draft.

### Center: Evidence And Workflow

The center column is the main review surface.

The upper area contains a compact interface-flow graph. Each node represents one learned interface or state. Selecting a node updates every detail below it.

The evidence area provides four explicit tabs:

- `Boxed screenshot` as the default;
- `Original screenshot`;
- `Interface details`;
- `PathGraph`.

The boxed screenshot uses the selected node's best available reviewed or fused overlay. It supports fit-to-view, full-screen inspection, and a direct `Edit boxes` command.

The PathGraph view displays node and transition relationships in plain language. Clicking a PathGraph node selects the corresponding interface and boxed screenshot. Missing screenshots or graph evidence produce a visible empty state rather than stale content.

### Right: Review Inspector

The right column edits the currently selected interface node.

The first version supports:

- display name;
- surface type;
- review status;
- region/control/action summary;
- blockers and verification rules;
- outgoing transition action and target;
- `Edit boxes`;
- `Save review`.

Saving must refresh the library entry, boxed screenshot, interface details, and PathGraph without requiring the user to reopen the editor.

## Information Hierarchy

The default view exposes only:

- draft library;
- interface flow;
- screenshot evidence;
- PathGraph;
- review controls;
- save state and actionable errors.

The following move into a collapsed `Advanced diagnostics` section:

- source and artifact paths;
- raw JSON;
- model configuration;
- trace paths;
- candidate counters;
- benchmark and promotion metadata;
- internal API controls.

Trace remains available for development diagnosis, but it is not part of the normal review path.

## Data Flow

1. The panel loads the bounded learning-draft source list.
2. The operator selects a human-readable library entry.
3. The panel calls the existing learning-draft review loader.
4. The returned draft and interface-workflow review populate one shared selected-draft state.
5. Selecting a workflow node changes the active evidence layer, details, PathGraph focus, and inspector.
6. Box edits and metadata edits update a review patch only.
7. Save writes a reviewed candidate, reloads that exact saved candidate, and refreshes all visible projections.

The selected draft path and selected workflow node are the single source of truth. Template replay state, a previous draft, and current learning-run progress must not leak into the workbench.

## Error And Empty States

- No drafts: show `No learning drafts yet` and the `New learning run` command.
- Loading: show a skeleton only inside the selected draft surface; keep the library usable.
- Missing screenshot: show the node identity and missing-evidence reason.
- Missing PathGraph: show `PathGraph not generated` and the next review action.
- Invalid draft: keep the entry visible with the validation error and diagnostic link.
- Save failure: retain unsaved edits and show a retryable error.
- Draft switch with unsaved changes: require confirmation before discarding the patch.

No stale screenshot, interface details, or PathGraph may remain after selection changes or load failures.

## Responsive Behavior

Desktop is the primary target.

- Above 1280 px: three columns remain visible.
- Between 900 and 1279 px: the right inspector becomes a slide-over panel.
- Below 900 px: the library becomes a drawer and the evidence area remains primary.

The screenshot and PathGraph use stable aspect-aware canvases. Their containers expand to the available workspace instead of defaulting to a quarter-width preview.

## Safety Boundary

The workbench edits learning-review artifacts only.

- `artifact_is_authorization=false`
- `execute_binding_enabled=false`
- no live click, fill, submit, send, confirm, payment, or delete
- reviewed historical coordinates are never direct Execute coordinates
- future execution must still use a fresh screenshot, fresh grounding, Gate, and post-action verification

## Verification

The implementation must include:

1. source-list rendering and human-readable grouping tests;
2. draft switching tests proving no stale screenshot/details/PathGraph leakage;
3. workflow-node selection tests proving evidence and inspector synchronization;
4. save-and-refresh tests;
5. missing evidence and invalid draft tests;
6. unsaved-change protection tests;
7. responsive layout checks;
8. browser smoke verification on the running local panel.

The browser smoke must demonstrate:

- a historical draft is visible without entering a path;
- selecting it displays a boxed screenshot and workflow graph;
- clicking another interface node changes the screenshot and details;
- opening `Edit boxes` reaches the existing correction editor;
- saving refreshes the workbench;
- no Execute authorization or real GUI action is produced.

## Delivery Boundary

This design reorganizes existing learning assets and editors into a usable review workflow. It does not redesign recognition, model prompts, precise calibration, Execute, or PathGraph runtime promotion.
