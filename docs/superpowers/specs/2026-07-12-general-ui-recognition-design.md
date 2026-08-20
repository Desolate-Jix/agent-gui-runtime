# General UI Recognition Design

## Goal

Turn Learning Mode recognition from a flat collection of review boxes into a reviewable, reusable hierarchy that works across websites and Windows applications.

## Architecture

The recognition pipeline keeps the existing Stage1 and Stage2 responsibilities:

1. Stage1 identifies complete structural regions such as top bars, sidebars, main content, modals, and overlays.
2. Stage2 identifies sections, repeated groups, components, and content inside each accepted Stage1 region.
3. `UIHierarchyGraph` converts those outputs into explicit parent-child and ownership relationships.
4. `RecognitionOwnershipResolver` resolves mutually exclusive claims using evidence strength and component precedence.
5. Benchmarks score structure, components, relationships, duplicate ownership, containment, and invalid evidence separately.

## UIHierarchyGraph Contract

`ui_hierarchy_graph_v1` is display/review only. It never authorizes Execute or Runtime PathGraph promotion.

Node levels:

- `screen`: the screenshot coordinate space.
- `structure_region`: Stage1 bars, main content, modal, overlay, or pane.
- `section`: a coherent page section such as a hero, list panel, card row, form, or toolbar.
- `component_group`: repeated cards, list rows, field groups, or control clusters.
- `component`: card, list row, input, button, image, or other review component.
- `content`: text, icon, label, status, or metadata owned by one component.

Every node records `node_id`, `level`, `component_type`, `bbox`, `parent_id`, `children`, `member_item_ids`, `evidence`, `confidence`, `review_status`, and safety flags.

Required invariants:

- Every non-screen node has exactly one parent.
- Every child bbox is contained by its parent bbox after clipping.
- A source item has one primary semantic owner at the same hierarchy level.
- Normal visual containment is allowed; competing sibling ownership is not.
- Unsupported or ambiguous nodes remain `needs_review`.
- Empty Stage1 lanes remain represented even when they have no Stage2 children.

## Ownership Resolution

Precedence is based on evidence and structure, not application names:

1. explicit visual component boundary
2. repeated structural pattern
3. OCR row/column relationship
4. model semantic proposal
5. geometry-only inference

Mutually exclusive semantic precedence includes:

- explicit list group over inferred text-only tile
- explicit visual card over text-only inferred card
- form field group over generic text cluster
- modal/overlay surface over background page component

The resolver must preserve rejected claims in an audit record with winner, loser, reason, and evidence sources.

## Benchmark

The showcase benchmark uses 8–12 structurally different surfaces and stores the original screenshot, Stage1 overlay, final overlay, hierarchy artifact, and human-reviewed golden manifest.

Metrics remain separate:

- structure-region boundary
- component localization
- parent-child relationship
- containment violations
- duplicate ownership
- unexpected components
- missing components
- invalid/stale evidence

No aggregate number may be presented as model accuracy or runtime reliability.

## Panel

Learning Draft shows a read-only hierarchy tree beside the current screenshot/page-detail preview. Selecting a node highlights its bbox and shows evidence, parent, children, ownership decision, and review status. Manual edits update a reviewed draft only and never authorize execution.

## Showcase Acceptance

- Three protected fixtures continue to pass their existing geometry checks.
- At least 8 diverse fixtures have valid same-source evidence.
- Hierarchy validation reports zero duplicate primary owners and zero child-outside-parent violations on passing fixtures.
- At least one deliberately failing fixture exposes each major failure category.
- The panel can load a saved draft and visibly present structure, hierarchy, page details, conflicts, and limitations without starting a model.
- No live click, fill, submit, or Runtime PathGraph promotion is required.
