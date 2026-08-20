# Learning Draft Overlap Consolidation Design

## Goal

Make dense learning-draft overlays easy to review when several OCR, icon, text,
region, and action boxes cover the same visible control.

This change affects editor presentation and selection only. It must not delete
source evidence, change reviewed artifact semantics, authorize Execute, or
weaken Gate.

## User Experience

The full-image box editor opens in a compact display mode:

- a complete control or parent region is preferred over contained fragments;
- hidden members are represented by a small `+N` overlap count;
- selecting the overlap count exposes the members for explicit selection;
- a toolbar toggle switches between `精简框` and `显示全部框`;
- manually added or manually changed boxes are always visible;
- the selected box remains visible even when compact mode would otherwise hide
  it.

The current add, move, resize, delete, undo, redo, metadata, destination, and
save behavior remains unchanged.

## Consolidation Rules

The editor derives display groups without mutating the editor state.

A smaller box may become a hidden member only when:

- most of its area is contained by a larger box;
- both boxes belong to the same local visual target;
- the larger box is a credible control parent or semantic parent;
- hiding it does not remove a distinct action, destination, input semantic, or
  safety meaning.

Display priority is:

1. manually added or manually changed item;
2. selected item;
3. action/control parent;
4. semantic region parent;
5. OCR, text, or icon fragment.

The following items are never automatically consolidated away:

- items with different destinations;
- items with different actionable semantics;
- final-submit, send, confirm, payment, delete, or other dangerous actions;
- independently editable siblings that only partially overlap;
- boxes whose containment or parent relationship is ambiguous.

## Data Flow

`LearningDraftEditorState.listItems()` remains the complete source of truth.
A pure display-projection helper receives the items, selected item, and compact
mode and returns:

- visible items;
- hidden member IDs grouped under each visible item;
- overlap counts;
- an explanation for each consolidation decision.

Rendering consumes the projection. Saving continues to export operations from
the complete editor state, so compact mode cannot change persisted evidence by
itself.

## Interaction

- `精简框` is the default.
- `显示全部框` restores the current one-box-per-item rendering.
- A visible parent with hidden members shows `+N`.
- Clicking `+N` opens a small candidate selector at that location.
- Choosing a member selects and temporarily reveals that member for editing.
- Add mode continues to make existing boxes pointer-transparent.

## Failure Handling

If an item has invalid geometry or consolidation cannot determine a safe
relationship, the item remains visible. The editor fails open for review
visibility, not closed by hiding uncertain evidence.

## Verification

Unit tests must cover:

- contained OCR/text/icon fragments collapse under a credible parent;
- unrelated overlapping boxes stay separate;
- different actions or destinations stay separate;
- dangerous actions stay visible;
- manual and selected items stay visible;
- compact/all toggle does not change exported review operations;
- overlap-member selection reveals the requested item.

The browser smoke must verify that a dense reviewed SEEK interface shows fewer
simultaneous boxes, can switch back to all boxes, can select a hidden member,
and saves without changing the workflow graph or safety state.

## Safety

This feature is display-only. It does not change current-capture requirements,
fresh grounding, Gate, Trace, final-submit blocking, or target-window actions.
