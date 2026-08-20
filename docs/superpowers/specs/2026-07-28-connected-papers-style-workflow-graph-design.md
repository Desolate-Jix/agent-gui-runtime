# Connected-Papers-Style Workflow Graph Design

## Goal

Upgrade the Learn Mode interface workflow graph from a static radial diagram into a stable, explorable relationship graph while preserving the existing workflow data, review behavior, and safety boundaries.

## Interaction Contract

- The same nodes and links produce the same settled positions on every load.
- A new graph briefly animates into place, then stops moving.
- Adding or removing nodes preserves existing node positions where possible and only reheats the affected graph.
- Hovering a node highlights that node, its directly connected neighbours, and their links.
- Unrelated nodes and links are visually de-emphasized during hover.
- Hover shows a concise tooltip with interface name, surface type, control count, and outgoing path count.
- Hover never changes the selected interface, review state, workflow data, or execution authorization.
- Interface diameter varies within a bounded range using evidence volume and graph connectivity, so sparse and dense interfaces remain visually distinguishable.
- Clicking a node centres the interface and loads its evidence/review data without removing unrelated interfaces or links from the software-wide graph.
- Pan, wheel zoom, reset, and focus controls remain available.
- Reduced-motion users receive the settled layout without animation.

## Architecture

The existing Canvas renderer remains in place. `interface_workflow_graph.js` owns deterministic layout, force simulation, adjacency projection, and hit testing as pure JavaScript. `panel.js` owns animation scheduling, hover state, Canvas presentation, and DOM tooltip positioning.

The simulation uses deterministic initial positions and no uncontrolled randomness. It combines:

- a weak center force;
- link springs;
- pairwise repulsion;
- collision separation;
- a fixed entry/focused node at the visual center.

The simulation has a bounded iteration count and a settled threshold. It cannot run forever or block workflow loading.

The source manager is separate from graph navigation. It previews one saved interface before attachment, allows renaming, and requires an explicit destination workflow, source interface, transition type, transition label, and optional source-control ID. Loading that preview cannot replace the workflow already open in the graph.

## Safety Boundary

This change is presentation-only. It does not change:

- Agent decisions;
- Workflow or PathGraph semantics;
- Operation execution;
- Gate checks;
- click authorization;
- final-submit blocking;
- Trace evidence.

## Verification

- Node tests prove deterministic settled positions.
- Node tests prove adjacency highlighting contains only one-hop neighbours and matching links.
- Node tests prove hover projection does not mutate topology.
- Node tests prove focus preserves the full graph and node sizes do not collapse to one saturated value.
- Existing interface workflow graph tests remain green.
- Browser smoke verifies animation, hover highlighting, tooltip, pan, zoom, click focus, full-graph retention, and single-interface preview.
