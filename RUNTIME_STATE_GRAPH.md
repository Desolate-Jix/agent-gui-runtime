# RUNTIME_STATE_GRAPH

Chinese version: `RUNTIME_STATE_GRAPH.zh-CN.md`

These two files should be kept in sync.

---

## Quick Mental Model

If you only remember one thing, remember this:

The runtime is building a reusable software map, not doing one-off screenshot guessing.

The map has three core parts:

- `state`: what screen we are on
- `target`: what can be clicked on that screen
- `transition`: where we go after clicking

The runtime loop is:

`see current screen -> identify state -> find target -> click -> verify -> save result -> reuse later`

## Layered View

Think of the system as five layers.

### Layer 1: Perception Layer

Goal:

- see the current screen
- extract text, controls, and positions

Main steps:

1. capture the bound window
2. run OCR
3. optionally run AI vision parsing
4. build one normalized observation object

Inputs:

- bound window
- screenshot

Outputs:

- `ObservationFrame`
- candidate state information
- raw targets from OCR/vision

### Layer 2: State Layer

Goal:

- decide what screen this is
- create a new state if the screen is unknown

Main steps:

1. try to match current observation to known states
2. if matched, return known `AppState`
3. if not matched, register a new `AppState`

Inputs:

- `ObservationFrame`
- known `AppState` records

Outputs:

- one `AppState`
- state confidence

### Layer 3: Target Layer

Goal:

- determine what can be clicked in the current state
- keep a reusable local asset for each target

Main steps:

1. read targets from the current state
2. if state is new, register new `ActionTarget`
3. crop and save:
   - target patch
   - context patch
4. create or update `TargetAsset`

Inputs:

- `AppState`
- OCR/vision targets
- screenshot

Outputs:

- `ActionTarget`
- `TargetAsset`

### Layer 4: Execution Layer

Goal:

- click the target reliably

Main steps:

1. load target asset
2. try local match first:
   - target patch
   - context patch
   - OCR
   - AI fallback
3. resolve final click point
4. click

Inputs:

- `ActionTarget`
- `TargetAsset`
- current screenshot

Outputs:

- click result
- actual click point

### Layer 5: Verification And Memory Layer

Goal:

- decide whether the click really worked
- write the result back into the state graph

Main steps:

1. capture after screenshot
2. verify by:
   - text anchors
   - target anchors
   - ROI diff
   - value/counter change
3. determine next state
4. write:
   - `ReplayCase`
   - `TransitionRecord`
5. update target confidence and preferred points

Inputs:

- before screenshot
- after screenshot
- validator rules

Outputs:

- success or failure
- next state
- updated memory

## How The Layers Call Each Other

The call order is:

`Layer 1 -> Layer 2 -> Layer 3 -> Layer 4 -> Layer 5`

More concretely:

1. Perception creates `ObservationFrame`
2. State layer uses it to find or create `AppState`
3. Target layer uses the state plus screenshot to load or create `ActionTarget` and `TargetAsset`
4. Execution layer uses those target records to click
5. Verification layer decides whether the action worked and writes the result back as `TransitionRecord` and `ReplayCase`

This means each layer has a clear responsibility:

- Layer 1 answers: what is visible now
- Layer 2 answers: what state is this
- Layer 3 answers: what can be used here
- Layer 4 answers: where should we click
- Layer 5 answers: did it work and what changed

## One Complete Example

Example:

Current screen is `home_page`, and the user wants to open settings.

### Step 1: Perception

- capture screenshot
- OCR sees `Start`, `Settings`, `Exit`
- AI or local parser returns a target called `settings_button`

### Step 2: State Recognition

- runtime compares observation against known states
- runtime recognizes `home_page`

### Step 3: Target Resolution

- runtime loads `settings_button`
- runtime loads `settings_button_asset`
- runtime finds:
  - saved patch
  - saved context patch
  - stored hit point

### Step 4: Execute

- runtime matches the target locally in the current screenshot
- runtime resolves the click point
- runtime clicks

### Step 5: Verify

- runtime captures after screenshot
- runtime checks whether `General` and `Advanced` appeared
- runtime decides that the new state is `settings_page`

### Step 6: Register Memory

- write `ReplayCase`
- write `TransitionRecord`
- raise confidence for this target and transition

## Why Save Target Patch

The reason is simple:

The first run can use AI to discover the button.
The second run should not need AI if the button is already known.

So for each known target, save:

- `target patch`: exact target crop
- `context patch`: surrounding area crop

Then next time:

1. match patch locally
2. click locally
3. use OCR or AI only as fallback

## How To Read The Rest Of This Document

Read this document in this order:

1. `Quick Mental Model`
2. `Layered View`
3. `How The Layers Call Each Other`
4. `One Complete Example`
5. then the entity and field sections below

The sections below are the detailed field dictionary.
The sections above are the runtime flow explanation.

## Goal

This document defines the runtime logic for turning a GUI application into a reusable state graph.

The system should not treat each screenshot as a fresh one-off perception task.
Instead, it should continuously accumulate reusable software structure:

- what the current screen state is
- which targets exist in that state
- where each target is located
- what is expected to happen after clicking a target
- how to verify that the transition really happened
- which target patch can be reused next time without asking AI again

The long-term execution loop is:

`Observe -> Recognize State -> Select Target -> Execute -> Verify -> Register -> Reuse`

## Core Principle

The persisted knowledge model is a state graph, not a flat page list.

- node = `AppState`
- edge = `TransitionRecord`
- actionable object on a node = `ActionTarget`
- local visual asset for reliable reuse = `TargetAsset`
- evidence of a concrete run = `ReplayCase`

This allows the runtime to move from:

- `AI sees screenshot -> AI guesses next click`

to:

- `runtime recognizes known state -> loads known target -> clicks -> verifies -> updates graph`

## Runtime Phases

### Phase 1: Observe

Input:

- bound window handle
- current screenshot or ROI screenshot

Output:

- `ObservationFrame`
- candidate `AppState` match or `unknown`

Responsibilities:

- capture screenshot
- collect OCR and vision output
- create a normalized observation object for downstream matching

### Phase 2: Register State

If the current screen does not confidently match an existing state, create a new `AppState`.

Responsibilities:

- assign a stable `state_id`
- save state signature fields
- save the screenshot used to define the state
- register visible targets returned by vision parsing

### Phase 3: Register Targets

For each actionable target on the screen, create or update an `ActionTarget` and its `TargetAsset`.

Responsibilities:

- save target bbox and hit point
- save visible text and control type
- save target patch and context patch
- define how the target should be matched next time

### Phase 4: Execute

When a target is selected:

- prefer existing local target assets
- fall back to OCR or AI parsing if local match is weak
- click using the resolved hit point

### Phase 5: Verify

After the click:

- capture an after screenshot
- check verification anchors
- decide whether the action caused:
  - navigation
  - dialog open
  - tab switch
  - toggle
  - unknown result

### Phase 6: Register Transition

If the action is meaningful, persist the transition:

`from_state + action_target -> to_state`

This is the graph edge that makes later reuse possible.

### Phase 7: Reuse

Next time the same state is encountered:

- load known targets and stored patches
- do local match first
- only call AI again if matching or verification fails

## Folder Strategy

Recommended runtime persistence layout:

```text
logs/
  app-states/
  app-actions/
    validators/
  app-transitions/
  replay-cases/
  target-patches/
    {app_name}/
      {state_id}/
        {target_id}/
          target-*.png
          context-*.png
          meta-*.json
  captures/
  verify/
```

Current repo already persists under `logs/`.
This document formalizes `target-patches/` as a first-class runtime store.

## Entity Model

## 1. ObservationFrame

Purpose:

- normalized representation of one screenshot at one moment
- input to state recognition and target registration

Suggested fields:

```json
{
  "frame_id": "string",
  "app_name": "string",
  "window_handle": 0,
  "captured_at": "iso_datetime",
  "image_path": "string",
  "image_width": 0,
  "image_height": 0,
  "window_rect": {
    "left": 0,
    "top": 0,
    "right": 0,
    "bottom": 0
  },
  "ocr_texts": ["string"],
  "vision_state_hint": "string|null",
  "layout_hash": "string|null"
}
```

Field usage:

- `frame_id`
  - producer: screenshot pipeline
  - consumer: replay cases, debug logs
- `app_name`
  - producer: runtime binding layer or request context
  - consumer: state storage partitioning
- `window_handle`
  - producer: window manager
  - consumer: evidence only, not long-term identity
- `image_path`
  - producer: screenshot service
  - consumer: OCR, verification, replay case
- `ocr_texts`
  - producer: OCR runtime
  - consumer: state recognition, verification anchors
- `layout_hash`
  - producer: future thumbnail/layout fingerprint step
  - consumer: fast state candidate filtering

## 2. AppState

Purpose:

- represent one recognizable UI state
- act as a graph node

Suggested fields:

```json
{
  "state_id": "home_page",
  "app_name": "demo_app",
  "state_name": "Home Page",
  "window_size_bucket": "1366x768",
  "summary": "main landing page with Start and Settings buttons",
  "signature": {
    "primary_texts": ["Start", "Settings", "Exit"],
    "secondary_texts": ["Version", "Status"],
    "layout_hash": "string|null",
    "anchor_patches": [
      {
        "name": "home_title",
        "path": "logs/app-states/.../anchor-001.png"
      }
    ]
  },
  "target_ids": ["start_button", "settings_button"],
  "entry_image_path": "string",
  "tags": ["main", "stable"],
  "version": 1
}
```

Field usage:

- `state_id`
  - producer: state registration logic
  - consumer: transition graph, action lookup, patch path partitioning
- `window_size_bucket`
  - producer: runtime geometry layer
  - consumer: fast state narrowing before detailed match
- `signature.primary_texts`
  - producer: OCR + AI parse
  - consumer: recognition and verification
- `signature.layout_hash`
  - producer: future fingerprint step
  - consumer: coarse state match
- `target_ids`
  - producer: target registration
  - consumer: known action loading
- `entry_image_path`
  - producer: screenshot service
  - consumer: audit/debug only

## 3. ActionTarget

Purpose:

- represent one actionable target within one state
- contain enough geometry and semantics to execute the action

Suggested fields:

```json
{
  "target_id": "settings_button",
  "state_id": "home_page",
  "action_name": "Open Settings",
  "label": "Settings",
  "control_type": "button",
  "action_type": "click",
  "bbox": {
    "x": 100,
    "y": 200,
    "width": 120,
    "height": 40
  },
  "bbox_norm": {
    "x": 0.10,
    "y": 0.26,
    "width": 0.12,
    "height": 0.05
  },
  "hit_point": {
    "x": 160,
    "y": 220
  },
  "text": "Settings",
  "text_candidates": ["Settings"],
  "match_strategy": "patch_then_ocr_then_ai",
  "target_asset_id": "settings_button_asset",
  "validator_profile_id": "validator_settings_open",
  "expected_transition_ids": ["home_to_settings"],
  "successful_points": [],
  "forbidden_points": [],
  "notes": "top-right main action",
  "version": 1
}
```

Field usage:

- `target_id`
  - producer: target registration
  - consumer: action execution, transition linking, patch asset lookup
- `bbox`
  - producer: AI parser or OCR parser
  - consumer: patch cropping and click coordinate generation
- `bbox_norm`
  - producer: registration logic
  - consumer: cross-resolution relocation
- `hit_point`
  - producer: parser or local point strategy
  - consumer: direct click execution
- `text`
  - producer: OCR/vision parse
  - consumer: fallback OCR match and verification
- `match_strategy`
  - producer: target registration defaults
  - consumer: runtime executor
- `target_asset_id`
  - producer: target asset creation
  - consumer: patch store lookup
- `successful_points`
  - producer: execution feedback
  - consumer: future point preference ordering
- `forbidden_points`
  - producer: execution feedback
  - consumer: avoid known bad points

## 4. TargetAsset

Purpose:

- persist local visual material for a known target
- make second and later executions less dependent on AI

Suggested fields:

```json
{
  "target_asset_id": "settings_button_asset",
  "target_id": "settings_button",
  "state_id": "home_page",
  "app_name": "demo_app",
  "patch_path": "logs/target-patches/demo_app/home_page/settings_button/target-001.png",
  "context_patch_path": "logs/target-patches/demo_app/home_page/settings_button/context-001.png",
  "source_image_path": "logs/captures/capture-001.png",
  "bbox": {
    "x": 100,
    "y": 200,
    "width": 120,
    "height": 40
  },
  "hit_point": {
    "x": 160,
    "y": 220
  },
  "match_method": "template",
  "confidence": 0.94,
  "created_at": "iso_datetime",
  "updated_at": "iso_datetime"
}
```

Field usage:

- `patch_path`
  - producer: crop-and-save pipeline during registration or successful click
  - consumer: template match stage
- `context_patch_path`
  - producer: crop-and-save pipeline
  - consumer: stable context-assisted matching when target patch alone is ambiguous
- `source_image_path`
  - producer: screenshot service
  - consumer: audit/debug only
- `match_method`
  - producer: asset registration policy
  - consumer: matcher selection
- `confidence`
  - producer: asset creation/update logic
  - consumer: whether local reuse is trusted before fallback

## 5. ValidatorProfile

Purpose:

- define how to decide whether a target action actually worked

Suggested fields:

```json
{
  "validator_profile_id": "validator_settings_open",
  "target_name": "Settings Open Validator",
  "target_roi": {
    "x": 0,
    "y": 0,
    "width": 0,
    "height": 0
  },
  "ocr_roi": {
    "x": 0,
    "y": 0,
    "width": 0,
    "height": 0
  },
  "appear_texts": ["General", "Advanced"],
  "disappear_texts": ["Start", "Exit"],
  "appear_target_ids": ["settings_back_button"],
  "strict_rule": {
    "type": "text_and_diff"
  },
  "weak_rule": {
    "type": "diff_only"
  },
  "version": 1
}
```

Field usage:

- `target_roi`
  - producer: target registration or later tuning
  - consumer: local diff validation
- `ocr_roi`
  - producer: validator setup
  - consumer: OCR-only verification after click
- `appear_texts`
  - producer: AI prediction or manual correction
  - consumer: after-state verification
- `disappear_texts`
  - producer: AI prediction or manual correction
  - consumer: transition confirmation
- `appear_target_ids`
  - producer: known next-state target registration
  - consumer: strong evidence of state change

## 6. TransitionRecord

Purpose:

- represent one graph edge from one state to another through one target action

Suggested fields:

```json
{
  "transition_id": "home_to_settings",
  "from_state_id": "home_page",
  "action_id": "settings_button",
  "to_state_id": "settings_page",
  "success_type": "strict",
  "confidence": 0.95,
  "effect_type": "navigate",
  "verification": {
    "appear_texts": ["General", "Advanced"],
    "disappear_texts": ["Start", "Exit"],
    "matched_targets": ["settings_back_button"]
  },
  "case_path": "logs/replay-cases/replay-001.json",
  "timestamp": "iso_datetime"
}
```

Field usage:

- `from_state_id`
  - producer: runtime state recognition
  - consumer: graph traversal and replay
- `action_id`
  - producer: executor
  - consumer: action lookup and policy tuning
- `to_state_id`
  - producer: after-state recognition
  - consumer: navigation planning and memory graph
- `effect_type`
  - producer: AI prediction then runtime confirmation
  - consumer: planner and executor expectations
- `verification`
  - producer: verification step
  - consumer: future trust calibration

## 7. ReplayCase

Purpose:

- store the concrete evidence of one execution attempt

Suggested fields:

```json
{
  "case_id": "replay-001",
  "app_name": "demo_app",
  "state_before_id": "home_page",
  "action_id": "settings_button",
  "state_after_id": "settings_page",
  "before_image_path": "logs/captures/before-001.png",
  "after_image_path": "logs/captures/after-001.png",
  "target_patch_path": "logs/target-patches/.../target-001.png",
  "context_patch_path": "logs/target-patches/.../context-001.png",
  "click_point": {
    "x": 160,
    "y": 220
  },
  "verification_result": {
    "strict_success": true,
    "weak_success": true,
    "diff_changed": true,
    "matched_appear_texts": ["General"]
  },
  "success": true,
  "timestamp": "iso_datetime"
}
```

Field usage:

- `before_image_path`, `after_image_path`
  - producer: screenshot service
  - consumer: replay analysis and debugging
- `target_patch_path`, `context_patch_path`
  - producer: patch store
  - consumer: failure analysis and asset refresh
- `verification_result`
  - producer: verifier
  - consumer: update target confidence and transition confidence

## Vision Output Contract

The AI parser should return a structure that can directly seed `AppState`, `ActionTarget`, and transition expectations.

Suggested vision response shape:

```json
{
  "image": {
    "width": 0,
    "height": 0
  },
  "screen_state": {
    "state_id": "home_page",
    "state_name": "Home Page",
    "summary": "main landing page"
  },
  "targets": [
    {
      "target_id": "settings_button",
      "label": "Settings",
      "control_type": "button",
      "action_type": "click",
      "bbox": {
        "x": 100,
        "y": 200,
        "width": 120,
        "height": 40
      },
      "bbox_norm": {
        "x": 0.10,
        "y": 0.26,
        "width": 0.12,
        "height": 0.05
      },
      "hit_point": {
        "x": 160,
        "y": 220
      },
      "text": "Settings",
      "text_candidates": ["Settings"],
      "confidence": 0.94,
      "clickable_confidence": 0.97,
      "expected_after": [
        {
          "effect_type": "navigate",
          "next_state_id": "settings_page",
          "next_state_name": "Settings Page",
          "confidence": 0.83,
          "reason": "settings menu likely opens the settings page",
          "verification_anchors": {
            "appear_texts": ["General", "Advanced"],
            "disappear_texts": ["Start", "Exit"],
            "appear_controls": ["settings_back_button"]
          }
        }
      ]
    }
  ],
  "text_nodes": []
}
```

How this is used:

- `screen_state.*`
  - seeds or updates `AppState`
- `targets[*]`
  - seeds or updates `ActionTarget`
- `targets[*].expected_after[*]`
  - seeds `TransitionRecord` expectation and `ValidatorProfile`
- `verification_anchors`
  - used directly by post-click verification

## Registration Flow For A New State

When the runtime enters an unknown screen:

1. capture full screenshot
2. call OCR and optionally AI vision parser
3. build `ObservationFrame`
4. determine that no known state matches confidently
5. create `AppState`
6. create `ActionTarget` for each returned target
7. crop and save `TargetAsset` for each target
8. persist all records

Result:

- the screen becomes reusable next time
- future runs can skip full AI parsing if local matching works

## Execution Flow For A Known State

When the runtime recognizes a known state:

1. load `AppState`
2. load all `ActionTarget` entries for that state
3. for the chosen target, load `TargetAsset`
4. try local match in this order:
   1. target patch
   2. context patch
   3. OCR text match
   4. AI reparse fallback
5. resolve final `hit_point`
6. click
7. capture after screenshot
8. verify using `ValidatorProfile`
9. update `ReplayCase`
10. update `TransitionRecord`
11. if needed, refresh the patch asset

## Patch Saving Logic

Patch saving should happen at two moments.

### A. State registration time

If a target is first discovered, save:

- `target patch`
- `context patch`
- metadata JSON

### B. Successful click time

If a click is verified as successful, optionally refresh:

- best target patch
- best context patch
- successful click point list

This means the system continuously improves the local target asset store.

## Patch Crop Definitions

### target patch

- exact target bbox crop
- used for precise template match

### context patch

- expanded crop around target bbox
- suggested margin: 20 to 60 px depending on UI density
- used when the exact target shape is too generic

## Verification Logic

Verification should not depend on only one signal.

Recommended order:

1. text anchors
   - did expected text appear
   - did expected text disappear
2. target anchors
   - did a known next-state target become visible
3. local diff
   - did the target ROI or a state ROI change
4. counter/value change
   - for UIs like MouseTester
5. fallback visual diff
   - weak signal only

## Confidence Update Rules

Suggested policy:

- successful strict verification:
  - raise `TransitionRecord.confidence`
  - raise `TargetAsset.confidence`
- repeated weak-only success:
  - keep moderate confidence
- repeated failure after local patch match:
  - reduce `TargetAsset.confidence`
  - prefer OCR or AI fallback next time
- repeated failure for same click point:
  - append to `ActionTarget.forbidden_points`

## ID Conventions

Recommended naming:

- `state_id`
  - `home_page`, `settings_page`, `settings_dialog_open`
- `target_id`
  - `settings_button`, `confirm_button`, `back_tab`
- `transition_id`
  - `home_to_settings`, `settings_to_home`
- `validator_profile_id`
  - `validator_settings_open`
- `target_asset_id`
  - `settings_button_asset`

IDs should be machine-stable, not natural-language sentences.

## Immediate Integration Plan For This Repo

### Existing parts that already fit this model

- `AppState`
- `ActionTarget`
- `ValidatorProfile`
- `TransitionRecord`
- `ReplayCase`
- `action_registry`
- `transition_memory`
- `replay_case_store`
- screenshot capture
- OCR service
- click execution
- verification

### Next parts to add

1. a first-class `TargetAsset` schema and store
2. `logs/target-patches/` persistence
3. patch crop helper in screenshot or asset module
4. local target match stage before OCR/AI fallback
5. AI parser contract that directly returns target geometry and expected transitions

## Practical Outcome

Once this model is in place, the system will behave like this:

### First time on a screen

- AI helps parse the screen
- runtime registers the state
- runtime saves targets and patches

### Second time on the same screen

- runtime recognizes the state
- runtime loads known targets and patches
- runtime clicks locally
- AI is only used as fallback

That is the key architectural shift from one-off perception to reusable software memory.
