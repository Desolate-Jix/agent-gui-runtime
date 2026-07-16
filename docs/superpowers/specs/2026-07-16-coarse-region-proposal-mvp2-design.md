# Coarse Region Proposal MVP-2 Design

## Scope correction

The first hierarchical-region MVP tested an element-only baseline. Its candidates were cleaned OCR, UIA, parser, or vision element boxes after exact-bbox deduplication and a 96-item cap. It did not test a true coarse-region proposal layer.

The supported conclusion is therefore limited to:

> Qwen3-VL 8B did not reliably recover major regions, subregions, and parent-child hierarchy directly from many atomic element boxes.

MVP-2 tests the still-open hypothesis that deterministic code can first propose a small set of coarse anonymous rectangles and the model can then select, merge, and organize those proposals.

## Isolation

- Experiment branch only; disabled by default.
- Three saved screenshots only: WhatsApp, Notepad, and Python.org.
- No changes to Execute, PathGraph, production Stage1, `bar_detection_v1`, or safety gates.
- Existing coordinate conversion, bbox union, crop generation, validators, overlays, and reports remain unchanged.

## Proposal generator

Input:

- original screenshot dimensions;
- cleaned parser element boxes;
- reusable OCR/UIA source evidence already attached to those boxes.

Output:

- two to eight Level-1 proposals;
- a small number of Level-2 proposals only when a large parent has a clear internal split;
- original-image coordinates only;
- anonymous proposal IDs and geometric evidence, without application or semantic region names.

The deterministic generator uses:

1. X/Y element occupancy projections and stable low-occupancy valleys;
2. long horizontal or vertical whitespace bands;
3. geometric clustering of nearby element boxes and cluster envelopes;
4. large remainder rectangles left after confirmed control bands or columns;
5. the root-window envelope as a possible parent, without forcing the model to select it.

The Notepad editor is the critical remainder case: a large region may be proposed even when it contains few or no OCR/UIA elements.

Each proposal records its bbox, level hint, generation sources, contained element IDs, touched edges, area ratio, separator strength, whitespace-boundary strength, and element density.

## Model contract

The same Qwen3-VL 8B model and generation settings are used for both experiments. Each side receives one call and no repair prompt.

The model may only:

- select supplied proposals;
- merge adjacent supplied proposals;
- organize selected proposals into Level-1 and Level-2 regions;
- assign parent-child relationships;
- provide a content summary and optional role;
- report missing proposals.

It may not generate bbox coordinates, reference missing proposal IDs, treat element IDs as final regions, use application-specific rules, or repair its result after validation.

## Strict A/B comparison

For every saved screenshot:

- Experiment A: element-only candidates -> one-shot 8B -> existing validator.
- Experiment B: coarse proposals -> one-shot 8B -> the same validator.

Both sides share the screenshot, model, temperature, token limit, prompt organization rules, parser, compiler, and validator. Raw responses, parsed outputs, overlays, crops, and validation reports are stored independently.

## Attribution

- Correct proposals plus incorrect model organization means model adjudication is the bottleneck.
- Missing or malformed proposals means proposal generation is the bottleneck.
- Similar A/B outcomes mean the current hybrid direction is not yet justified.

The direction is worth continuing only if B is visibly better on at least two samples, recovers the Notepad editor, increases validator passes, introduces no coordinate drift, and uses no application-specific rule.
