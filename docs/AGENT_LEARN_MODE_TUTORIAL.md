# Agent Learn Mode Tutorial

Learn Mode creates reusable interface knowledge. It should produce artifacts that Execute Mode can consume later.

## Learn Fast

Goal: quickly draft a PathGraph for the current page.

Flow:

```text
screenshot
-> coarse structure recognition
-> OCR / UI evidence
-> region and control fusion
-> PathGraph draft
-> trace
```

Expected output:

- page type
- major regions
- visible controls
- likely actions
- scroll containers
- first draft PathGraph
- draft visual assets for stable buttons/icons, including tight/context crops and source capture metadata
- screenshots and trace paths

Use Learn Fast when entering a new page or app state.

## Learn Deep

Goal: refine and verify the PathGraph.

Flow:

```text
PathGraph draft
-> all important child nodes
-> coordinate calibration
-> missing node detection
-> duplicate / overlap cleanup
-> semantic rename / role review
-> PathGraph delta
-> optional ElementMemory initialization
-> trace
```

Expected output:

- corrected bbox and click point for each important node
- renamed nodes where model/OCR labels were poor
- removed duplicates
- added missing controls
- verified scroll container ownership
- overlay / coordinate evidence
- stable visual assets with match policy, allowed scope, negative examples, and `can_authorize_click=false`

Use Learn Deep when the operator needs a reusable map, not just one action.

## Visual Asset Learning

Learn Mode should treat fixed buttons and icons as reusable visual assets. Examples include `Quick apply`, `Apply`, `Continue`, `Next`, `Save`, menu icons, and other stable controls. A visual asset is useful for fast Execute Mode candidate recall, but it never authorizes a click by itself.

The rule is:

```text
Learn Mode saves the asset. Execute Mode matches it in the current screenshot. Gate still decides.
```

This prevents old screenshot coordinates from being reused as live click points. Source bboxes and source click points may define a search ROI, but Execute Mode must produce a fresh `visual_asset_match_v1` bound to the current capture id before creating a `seeded_candidate_v1`.

Detailed design: `docs/VISUAL_ASSET_LEARNING_MODE.zh-CN.md`.

## What A Good PathGraph Records

A useful learned artifact should include:

- page type
- app/window identity rules
- regions such as top search area, results list, detail pane, header, body, footer
- entities such as card, row, input, button, dropdown, tab, detail section
- scroll containers and their bboxes
- action templates
- state transitions
- verification rules
- safety policy
- visual assets or icon hints when useful
- trace and screenshot provenance

## From Manual Learning To Artifact

If a human-guided run succeeds, export it into a learned artifact:

```text
manual run report
-> traversal trace
-> learned_app_profile_v1
-> path_graph_seed_v1
-> runtime_path_graph_v1
-> learned_skill_v1
-> visual_asset_v1
```

SEEK is the reference sample for this pattern. Do not hard-code SEEK layout as a universal browser rule; abstract only the reusable parts, such as split list/detail, card opening, detail reading, scroll scoping, and final-submit blocking.

## When Learn Mode Is Complete

Learn Mode is ready when:

- the PathGraph can be loaded in the panel
- safe actions can be listed
- dry-run execution highlights the expected node/edge
- at least one real safe action succeeds through Execute Mode
- the artifact is non-authorizing and final-submit-safe
- traces prove where the coordinates and rules came from
