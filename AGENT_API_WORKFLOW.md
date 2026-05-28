# Agent API Workflow

This document defines the API-first workflow an upper-layer agent must follow when using this runtime.

For a Chinese field-by-field explanation of every endpoint, see `API_FIELD_REFERENCE.zh-CN.md`.

The core rule is:

> The agent must not click from raw visual-model coordinates. It must call the runtime APIs, let the runtime attach OCR anchors, inspect the recognition plan, and only execute a click through the gated action endpoint.

The desktop test panel also exposes `POST /action/execute_confirmed_point` for an operator who has visibly reviewed a candidate bbox and deliberately presses its coordinate-click button. This diagnostic path is not an autonomous agent execution path and does not replace `pre_click_decision_v1`.

## Model-Facing Language Rule

The upper-layer agent should keep the user's original instruction for audit, but send normalized English task fields to vision-model routes whenever possible.

Recommended request shape:

```json
{
  "goal": "Click the first organic Google search result title.",
  "state_hint": "main organic search results list below Google navigation tabs",
  "metadata": {
    "goal_original": "点击 Google 搜索结果页的第一个自然搜索结果链接",
    "goal_model": "Click the first organic Google search result title.",
    "state_hint_model": "main organic search results list below Google navigation tabs",
    "negative_constraints": [
      "exclude search box",
      "exclude top navigation tabs",
      "exclude AI Overview",
      "exclude ads",
      "exclude side panels"
    ]
  }
}
```

Reasoning:

- The runtime trace must preserve `goal_original` for review.
- The local vision model generally follows concise English grounding constraints more reliably.
- English also avoids upstream shell/client encoding damage in model-facing `goal` and `state_hint`.
- Put excluded English phrases such as `AI Overview` in `metadata.negative_constraints`, not as the clearest phrase in the main `goal`.

## Response Envelope

All endpoints return the same envelope:

```json
{
  "success": true,
  "message": "...",
  "data": {},
  "error": null
}
```

On failure:

```json
{
  "success": false,
  "message": "...",
  "data": {},
  "error": {
    "code": "machine_readable_error_code",
    "details": "human readable detail or structured JSON"
  }
}
```

Many agent-facing routes also return a `timings` object in `data` or `data.result`, and write the same object into their trace:

```json
{
  "contract_version": "runtime_timing_v1",
  "total_ms": 1234.56,
  "steps": [
    {
      "name": "recognition_plan",
      "elapsed_ms": 1180.25
    }
  ]
}
```

Agent decision:

- Use `timings.total_ms` for end-to-end latency.
- Use `timings.steps[*].name` and `elapsed_ms` to identify slow stages such as model startup, screenshot capture, OCR anchor preparation, vision inference, candidate ranking, pre-click gate, real click dispatch, and post-click verification.
- Treat `timings` as diagnostic evidence only. It does not prove a target is safe to click; click safety still comes from `pre_click_decision_v1`.

## Required Live Agent Flow

Use this flow when the agent is controlling a real visible application window.

### 0. Prepare Runtime Dependencies

Before opening apps or asking vision to reason about a screen, the agent should ensure the local model services it plans to use are reachable. If the FastAPI runtime itself is not running, start it outside the API first; once `/health` is reachable, call:

```http
POST /runtime/prepare
Content-Type: application/json
```

Request:

```json
{
  "start_models": true,
  "stages": ["observe", "locate"],
  "wait_until_ready": false,
  "wait_seconds": 0
}
```

Agent decision:

- If a model returns `status: "running"`, continue.
- If a model returns `status: "loading"`, wait or call again with `wait_until_ready: true`.
- If startup fails, do not continue into vision recognition; report the model service blocker.

### 1. Discover Available Apps And Windows

```http
GET /apps
```

Expected response:

```json
{
  "success": true,
  "message": "Apps listed",
  "data": {
    "contract_version": "app_discovery_v1",
    "catalog": {
      "contract_version": "app_catalog_v1",
      "apps": [
        {
          "app_id": "edge",
          "name": "Microsoft Edge",
          "description": "Web browser for website and web-app tasks.",
          "launch_command": ["msedge.exe"],
          "executable_candidates": ["C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"],
          "process_name": "msedge.exe",
          "title_hint": "Microsoft Edge",
          "capabilities": ["open_url", "web_navigation", "web_forms", "browser_ui"]
        }
      ]
    },
    "running_windows": [],
    "bound_window": null,
    "agent_next_steps": []
  },
  "error": null
}
```

Agent decision:

- Use `catalog.apps[*].capabilities` to decide which software can satisfy the user task.
- If the needed app is not running, call `POST /apps/open`.
- If the needed app is already visible, bind it with `POST /session/bind_window`.
- The editable app catalog lives at `configs/app_catalog.json`.

### 2. Open An App When Needed

```http
POST /apps/open
Content-Type: application/json
```

Request:

```json
{
  "app_id": "edge",
  "url": "https://www.google.com/search?q=ai%E7%9A%84%E6%9C%80%E6%96%B0%E8%BF%9B%E5%B1%95",
  "bind_after_open": true,
  "wait_seconds": 1.5
}
```

Expected response:

```json
{
  "success": true,
  "message": "App open requested",
  "data": {
    "contract_version": "app_open_result_v1",
    "app": {
      "app_id": "edge",
      "name": "Microsoft Edge"
    },
    "command": ["C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe", "https://www.google.com/search?q=..."],
    "process_id": 1234,
    "bound_window": {
      "bound": true,
      "window_title": "Microsoft Edge",
      "process_name": "msedge.exe"
    },
    "running_windows": []
  },
  "error": null
}
```

Agent decision:

- Continue when `success == true`.
- If `bound_window == null`, inspect `running_windows` and bind manually with `POST /session/bind_window`.
- Prefer `url` for browser navigation during app launch instead of launching the browser and then typing a URL by hand.

### 3. List Candidate Windows

```http
GET /session/windows
```

Expected response:

```json
{
  "success": true,
  "message": "Visible windows listed",
  "data": {
    "candidates": [
      {
        "handle": 123456,
        "title": "Jobs on SEEK - Microsoft Edge",
        "process_id": 1111,
        "process_name": "msedge.exe",
        "rect": {
          "left": 0,
          "top": 0,
          "right": 1280,
          "bottom": 900
        }
      }
    ]
  },
  "error": null
}
```

Agent decision:

- Choose the intended target window by `title` and/or `process_name`.
- If no candidate is clearly correct, ask the user instead of guessing.

### 4. Bind The Target Window

```http
POST /session/bind_window
Content-Type: application/json
```

Request:

```json
{
  "title": "SEEK",
  "process_name": "msedge.exe"
}
```

Expected response:

```json
{
  "success": true,
  "message": "Window bound",
  "data": {
    "bound": true,
    "handle": 123456,
    "window_title": "Jobs on SEEK - Microsoft Edge",
    "process_id": 1111,
    "process_name": "msedge.exe",
    "rect": {
      "left": 0,
      "top": 0,
      "right": 1280,
      "bottom": 900
    },
    "is_active": true
  },
  "error": null
}
```

Agent decision:

- Continue only when `success == true` and `data.bound == true`.
- Keep the returned window identity for trace review.

### 4.5 Type Text Into A Focused Control When Needed

Use this only after the target window is bound. If the input box is not already focused, provide a reviewed window-relative point and set `click_before_typing`.

```http
POST /action/type_text
Content-Type: application/json
```

Request:

```json
{
  "text": "ai latest progress",
  "x": 320,
  "y": 84,
  "click_before_typing": true,
  "clear_existing": true,
  "submit": true
}
```

Agent decision:

- This route sends real input through `SendInput+clipboard`; it is not a vision locator.
- Use `dry_run: true` when checking payload shape without typing.
- For browser searches, prefer `/apps/open` with `url` when the target URL is already known.

### 5. Read Runtime State

```http
GET /state
```

Expected response:

```json
{
  "success": true,
  "message": "State retrieved",
  "data": {
    "bound": true,
    "window_title": "Jobs on SEEK - Microsoft Edge",
    "process_name": "msedge.exe",
    "is_active": true
  },
  "error": null
}
```

Agent decision:

- If `bound == false`, return to window binding.
- If the active window is not the intended target, rebind or ask the user.

### 6. Understand The Current Screen

Before selecting a precise target, the agent should ask the runtime to read the whole current screen and report visible controls, icon candidates, text elements, and likely actions.

```http
POST /vision/observe_screen
Content-Type: application/json
```

Request:

```json
{
  "task": "observe_screen",
  "app_name": "seek",
  "state_hint": "browser page",
  "provider_mode": "local_understanding",
  "capture_live": true,
  "metadata": {
    "ocr_anchors": {
      "enabled": true,
      "max_anchors": "all"
    }
  }
}
```

Expected response:

```json
{
  "success": true,
  "message": "Screen observation completed",
  "data": {
    "result": {
      "contract_version": "screen_observation_v1",
      "screen_reading": {
        "texts": [],
        "ui": {
          "elements": [],
          "icon_candidates": []
        }
      },
      "execution_path": {
        "vision_model_used": true,
        "page_structure_used": true,
        "screen_reading_used": true
      },
      "suggested_state_hint": "top navigation bar",
      "agent_next_steps": [
        "Read screen_reading.ui.elements and ui.icon_candidates to decide what the user likely wants.",
        "Use suggested_state_hint as the default state_hint for POST /vision/locate_target unless the user overrides it.",
        "When a concrete target is chosen, call POST /vision/locate_target with that goal.",
        "Execute only through POST /action/execute_recognition_plan after pre_click_decision allows it."
      ],
      "trace_path": "logs/traces/vision/..."
    }
  },
  "error": null
}
```

Agent decision:

- Use this response to understand what the interface contains and what controls can probably do.
- Prefer `provider_mode: local_understanding` here. It is intended for the smaller local model that summarizes the whole screen for agent planning.
- Use `suggested_state_hint` as the next precise-localization `state_hint` default. It comes from the observation model's concise `state_guess`.
- Do not click from this response.
- Pick a concrete goal such as `点击 SEEK 导航栏的首页图标`, then call `POST /vision/locate_target`.

### 7. Precisely Locate The Chosen Target Without Clicking

```http
POST /vision/locate_target
Content-Type: application/json
```

Request:

```json
{
  "goal": "点击 SEEK 导航栏的首页图标",
  "task": "click_target",
  "app_name": "seek",
  "state_hint": "browser navbar",
  "provider_mode": "local_grounding",
  "capture_live": true,
  "top_k": 5,
  "metadata": {
    "ocr_anchors": {
      "enabled": true,
      "max_anchors": "all"
    }
  }
}
```

Expected response:

```json
{
  "success": true,
  "message": "Target located",
  "data": {
    "result": {
      "contract_version": "target_location_v1",
      "goal": "点击 SEEK 导航栏的首页图标",
      "recognition_plan": {},
      "pre_click_decision": {
        "allowed": true,
        "selected_click_point": {
          "x": 221,
          "y": 119
        }
      },
      "selected_click_point": {
        "x": 221,
        "y": 119
      },
      "located_bbox": {
        "x": 211,
        "y": 109,
        "w": 20,
        "h": 20
      },
      "located_point": {
        "x": 221,
        "y": 119
      },
      "location_status": "pre_click_verified",
      "execution_path": {
        "action_executed": false,
        "coordinate_source": "pre_click_decision_v1.selected_click_point",
        "located_coordinate_source": "recommended_target.element.click_point",
        "agent_must_call_for_click": "POST /action/execute_recognition_plan"
      }
    }
  },
  "error": null
}
```

Agent decision:

- Treat this as precise no-click localization.
- Prefer `provider_mode: local_grounding` here. It is intended for the larger local model that performs precise OCR-assisted target localization.
- Use `pre_click_decision.allowed` as the quality gate.
- Read `located_bbox` and `located_point` as the large model's no-click target proposal. For a visual-only icon it may be present while `selected_click_point` is null and `location_status` is `requires_pre_click_confirmation`.
- For a text-bearing clickable card, a target-matched review candidate may be retained only with explicit destination and OCR text evidence. In that case `located_bbox` / `located_point` are derived from matching OCR text inside the card, and the card remains confirmation-required.
- For list-like text targets, inspect `recommended_target.element.evidence.above_exclusion_boundary`. If `semantic_bbox_crosses_boundary == true`, the visual container intruded into the preceding item; the runtime keeps only the OCR-grounded review candidate and blocks autonomous execution.
- Treat only `selected_click_point` as executable. An icon proposal must not silently fall back to nearby OCR text merely because that text is easier to ground.
- Still do not click directly. To click, call `POST /action/execute_recognition_plan`, which re-captures and rechecks before dispatching input.
- If a visual model emits out-of-bounds values consistent with `0..1000` normalized coordinates, the provider restores them before pixel clamping and records `coordinate_space_recovered=normalized_1000`; that restored bbox is still a no-click proposal.

### 8. Build A No-Click Live Recognition Plan

For real operation, the safest first pass is a dry run through the action endpoint. This captures the live bound window, runs the full recognition pipeline, renders review evidence, and does not click.

```http
POST /action/execute_recognition_plan
Content-Type: application/json
```

Request:

```json
{
  "goal": "点击 SEEK 导航栏的首页图标",
  "task": "click_target",
  "app_name": "seek",
  "state_hint": "browser navbar",
  "provider_mode": "local_grounding",
  "capture_live": true,
  "dry_run": true,
  "top_k": 5,
  "metadata": {
    "ocr_anchors": {
      "enabled": true,
      "max_anchors": "all",
      "min_score": 0.0
    },
    "prompt_overrides": {
      "additional_rules": "Prefer the leftmost home/logo target in the navigation bar and exclude adjacent nav labels."
    }
  }
}
```

Internal runtime steps:

1. Capture the currently bound live window.
2. Call `POST /vision/recognition_plan` internally with the captured `image_path`.
3. Run OCR over the same screenshot.
4. Build and retain `ocr_anchors_v1` from all OCR text boxes by default.
5. For `click_target`, attach a bounded `relation_matrix_compact` prompt projection: every selected row keeps OCR text and bbox coordinates, plus compact inclusion/exclusion policy rows.
6. Normalize model regions into `vision_regions_v1`.
7. Fuse vision and OCR into `page_structure_v1`.
8. Build `screen_reading_v1`.
9. Rank candidates through `candidate_rank_v1`.
10. Run local narrow search on candidate crops.
11. Build `pre_click_decision_v1`.
12. Render a recognition-plan overlay when a trace is available.
13. Save an `approved_recognition_plan_v1` record when the pre-click gate allows the selected point.
14. Return the selected point and `approved_plan_id` without clicking because `dry_run == true`.

Expected response shape:

```json
{
  "success": true,
  "message": "Recognition plan accepted; dry run did not click",
  "data": {
    "action": "execute_recognition_plan",
    "result": {
      "contract_version": "execute_recognition_plan_v1",
      "goal": "点击 SEEK 导航栏的首页图标",
      "image_path": "artifacts/screenshots/...",
      "recognition_plan": {
        "contract_version": "recognition_plan_v1",
        "parse_result": {
          "vision_regions": {},
          "ocr_result": {},
          "ocr_anchors": {},
          "page_structure": {},
          "screen_reading": {}
        },
        "candidate_result": {},
        "narrow_search_result": {},
        "pre_click_decision": {
          "allowed": true,
          "selected_click_point": {
            "x": 221,
            "y": 119
          },
          "reasons": []
        },
        "recommended_target": {},
        "execution_path": {
          "vision_model_used": true,
          "ocr_anchor_grounding_used": true,
          "ocr_anchor_grounding_fallback_used": false,
          "ocr_anchor_count": 77,
          "candidate_rank_used": true,
          "narrow_search_used": true,
          "pre_click_decision_used": true,
          "action_executed": false
        },
        "trace_path": "logs/traces/vision/..."
      },
      "recognition_plan_overlay": {
        "overlay_path": "artifacts/review-overlays/..."
      },
      "pre_click_decision": {
        "allowed": true,
        "selected_click_point": {
          "x": 221,
          "y": 119
        }
      },
      "selected_click_point": {
        "x": 221,
        "y": 119
      },
      "approved_plan_id": "86a4a4f0e6f24e70b3f58f26f285c943",
      "approved_plan_path": "logs/approved-plans/86a4a4f0e6f24e70b3f58f26f285c943.json",
      "execution_path": {
        "dry_run": true,
        "coordinate_source": "pre_click_decision_v1.selected_click_point",
        "action_executed": false
      }
    }
  },
  "error": null
}
```

Agent decision:

- Use `data.result.pre_click_decision.allowed` as the click gate.
- Use `data.result.selected_click_point` as the only executable coordinate.
- Do not use raw `vision_regions.regions[*].bbox` as a click coordinate.
- If `ocr_anchor_grounding_used == false`, treat the plan as lower confidence and inspect `ocr_anchor_grounding_fallback_used`.
- The default 48-row prompt budget is not guaranteed to fit every dense page. A saved Seek/Serato test exhausted the anchored context and safely retried without prompt anchors; retained OCR then grounded the reviewed text-card point.
- If `pre_click_decision.allowed == false`, do not click. Re-observe, narrow the ROI, improve the goal text, or ask the user.

### Operator-Reviewed Coordinate Test Path

The desktop panel copies the first returned localization candidate into bbox-review fields and its coordinate click gate. Once the operator visibly checks that box, the panel can validate or explicitly dispatch its bound-window-relative center:

```http
POST /action/execute_confirmed_point
Content-Type: application/json
```

```json
{
  "x": 800,
  "y": 26,
  "bbox": {"x": 792, "y": 13, "width": 16, "height": 26},
  "label": "close window button",
  "source_trace_path": "logs/traces/vision/...",
  "dry_run": true
}
```

With `dry_run: false`, this route dispatches that exact point through the real input controller and writes an action trace. It rejects a point outside its reviewed bbox or the currently bound window. Upper-layer agents must not use this operator-only route to bypass recognition gating.

### 9. Execute The Click Only After The Plan Is Accepted

If the dry run is accepted and the user/agent wants to execute, reuse the `approved_plan_id` returned by the dry run. The runtime validates that the same bound window is still active, the goal matches, the approval has not expired, and the approved click point is still inside the window. It then dispatches the click and runs post-click verification without running the large vision model again.

```http
POST /action/execute_recognition_plan
Content-Type: application/json
```

Request:

```json
{
  "goal": "点击 SEEK 导航栏的首页图标",
  "task": "click_target",
  "app_name": "seek",
  "state_hint": "browser navbar",
  "provider_mode": "local_grounding",
  "capture_live": true,
  "dry_run": false,
  "enable_post_click_verification": true,
  "max_execution_attempts": 2,
  "top_k": 5,
  "metadata": {
    "ocr_anchors": {
      "enabled": true,
      "max_anchors": "all",
      "min_score": 0.0
    }
  }
}
```

Preferred fast execution request after a successful dry-run:

```json
{
  "goal": "Click the first organic Google search result title.",
  "approved_plan_id": "86a4a4f0e6f24e70b3f58f26f285c943",
  "app_name": "browser",
  "dry_run": false,
  "enable_post_click_verification": true,
  "max_execution_attempts": 2
}
```

Expected response:

```json
{
  "success": true,
  "message": "Recognition-plan click executed and verified",
  "data": {
    "action": "execute_recognition_plan",
    "result": {
      "selected_click_point": {
        "x": 221,
        "y": 119
      },
      "execution_path": {
        "action_executed": true,
        "approved_plan_reused": true,
        "recognition_plan_reused": true,
        "vision_model_used": false,
        "post_click_verification_used": true,
        "coordinate_source": "approved_plan_v1.selected_click_point"
      },
      "approved_plan_id": "86a4a4f0e6f24e70b3f58f26f285c943",
      "approved_plan_reuse_validation": {
        "valid": true
      },
      "recognition_plan_trace_path": "logs/traces/vision/...",
      "trace_path": "logs/traces/actions/..."
    }
  },
  "error": null
}
```

Agent decision:

- Prefer `approved_plan_id` reuse for the real click. Calling `dry_run: false` without an approved plan is still supported, but it re-runs recognition and is slower.
- Treat the action as successful only when `success == true` and post-click verification did not reject the result.
- Save or report both the recognition trace and action trace.

## Saved Screenshot Review Flow

Use this flow for offline testing, model evaluation, screenshots, and overlay review. It should not be used for real clicking unless explicitly allowed.

### 1. Capture A Screenshot

```http
POST /state/capture_window
Content-Type: application/json
```

Request:

```json
{
  "save_image": true,
  "roi": null
}
```

Expected response:

```json
{
  "success": true,
  "message": "Window captured",
  "data": {
    "image_path": "artifacts/screenshots/...",
    "image_width": 1280,
    "image_height": 900,
    "roi": null,
    "roi_adjusted": false
  },
  "error": null
}
```

### 2. Build A No-Click Recognition Plan On The Saved Image

```http
POST /vision/recognition_plan
Content-Type: application/json
```

Request:

```json
{
  "image_path": "artifacts/screenshots/seek-navbar.png",
  "goal": "识别 SEEK 首页导航栏的主页图标",
  "task": "click_target",
  "app_name": "seek",
  "state_hint": "browser navbar",
  "provider_mode": "local_grounding",
  "top_k": 5,
  "metadata": {
    "ocr_anchors": {
      "enabled": true,
      "max_anchors": "all",
      "min_score": 0.0
    }
  }
}
```

Expected response key fields:

```json
{
  "success": true,
  "data": {
    "result": {
      "contract_version": "recognition_plan_v1",
      "parse_result": {
        "ocr_result": {
          "matches": []
        },
        "ocr_anchors": {
          "contract_version": "ocr_anchors_v1",
          "anchor_count": 77,
          "anchors": []
        },
        "vision_regions": {
          "contract_version": "vision_regions_v1",
          "regions": []
        },
        "page_structure": {},
        "screen_reading": {}
      },
      "candidate_result": {},
      "narrow_search_result": {},
      "pre_click_decision": {},
      "recommended_target": {},
      "execution_path": {
        "vision_model_used": true,
        "ocr_anchor_grounding_used": true,
        "ocr_anchor_count": 77,
        "action_executed": false
      },
      "trace_path": "logs/traces/vision/..."
    }
  }
}
```

Agent decision:

- Use this for review and planning.
- Do not execute a real click from a saved screenshot unless the caller explicitly uses `/action/execute_recognition_plan` with `allow_saved_image_execution: true`.

### 3. Render A Recognition Overlay

```http
POST /vision/render_recognition_plan_overlay
Content-Type: application/json
```

Request:

```json
{
  "trace_path": "logs/traces/vision/20260523-...__recognition-plan__seek.json",
  "include_rejected": true,
  "include_points": true,
  "label_candidates": true,
  "label_reasons": true
}
```

Expected response:

```json
{
  "success": true,
  "message": "Recognition plan overlay rendered",
  "data": {
    "result": {
      "overlay_path": "artifacts/review-overlays/..."
    }
  },
  "error": null
}
```

Agent decision:

- Use the overlay for human review or debugging.
- Overlay evidence does not replace `pre_click_decision_v1`.

## What The Runtime Sends To The Vision Model

The agent does not handwrite the final visual-model prompt. The agent sends `goal`, `task`, `state_hint`, `image_path`, and `metadata`. The runtime builds the final prompt in `app/vision/prompting.py`.

For a recognition-plan call with OCR anchors enabled, the runtime retains complete OCR evidence, while the visual model receives:

1. The screenshot image.
2. A system instruction requiring JSON only.
3. A region-analysis prompt containing:
   - image width and height
   - task, app name, goal, and state hint
   - required `vision_regions_v1` JSON schema
   - bbox coordinate rules
   - OCR anchor grounding rules
   - a bounded OCR text-coordinate relation matrix for `click_target` (`relation_matrix_compact` by default)
   - optional `metadata.prompt_overrides.additional_rules` from the settings panel or agent request

Prompt skeleton:

```text
You are analyzing a GUI screenshot for a local desktop agent runtime.

Screenshot coordinate system:
- origin is the top-left corner
- image width = <width>
- image height = <height>
- all pixel coordinates must be based on this exact resolution

Task:
- app_name: <app_name>
- goal: <goal>
- state_hint: <state_hint>

Return JSON only. Do not return markdown.

Required JSON shape:
- top-level keys: provider, contract_version, image_size, screen_summary, state_guess, regions, targets, observers, notes
- contract_version must be "vision_regions_v1"
- each region must include region_id, label, role, diagonal, description, ocr_text, text_lines, possible_destinations, anchor_relations, grounding_constraints, confidence

OCR text-coordinate relation matrix:
- OCR has already detected text boxes; a prompt budget selects rows, but each selected row keeps visible OCR text and coordinates
- OCR anchors use the same coordinate system as the image
- columns are `i,t,x,y,w,h,m`: `i=N` identifies output anchor id `ocr_anchor_N`; `t` is visible text; `m=1` indicates a strong goal-text match
- when `m=1` rows exist, up to `prompt_focus_neighbor_limit` nearby text rows are selected before global sampling and encoded as `focus_relation_rows=[focus_id,neighbor_id,L|R|A|B,gap_px]`
- relation policy rows define whether referenced text is excluded from, or included in, the target bbox
- use anchors as spatial evidence, not as the object itself
- for icons without internal text, retain nearby text evidence and set text_inclusion_policy="exclude_text"
- for controls whose visible target includes text, set text_inclusion_policy="include_referenced_text"
- when a spatially relevant matrix row exists, cite at least one row in `anchor_relations` and populate `text_anchor_frame`
- OCR text-coordinate matrix: <compact JSON>
```

Precision-prompt OCR projection example:

```json
{
  "contract_version": "ocr_prompt_matrix_v1",
  "profile": "relation_matrix_compact",
  "coordinate_space": "current_image",
  "source_anchor_count": 77,
  "anchor_count": 48,
  "text_anchor_count": 48,
  "goal_match_count": 1,
  "columns": ["i", "t", "x", "y", "w", "h", "m"],
  "rows": [
    [1, "seek", 176, 100, 50, 25, 1],
    [2, "filter", 236, 101, 42, 24, 0],
    [4, "maximize", 1190, 10, 18, 18, 0]
  ],
  "focus_relation_columns": ["f", "n", "r", "g"],
  "focus_relation_rows": [
    [1, 2, "R", 10]
  ],
  "relation_policy_columns": ["target_kind", "text_bbox_policy", "allowed_anchor_relation"],
  "relation_policy_rows": [
    ["visual_icon", "exclude_text", "boundary|alignment|exclusion"],
    ["text_control", "include_referenced_text", "inside|contains|edge"]
  ]
}
```

For visual-only goals such as `关闭窗口`, selected surrounding text remains present in matrix rows as boundary/alignment/exclusion evidence; `exclude_text` controls the returned target bbox rather than deleting OCR context.

`prompt_max_anchors` defaults to `48`. `prompt_focus_neighbor_limit` defaults to `12` and is bounded by that total because focus neighbors consume rows from the same prompt budget. Set it higher when an OCR-matched label has several nearby text landmarks; set it to `0` to disable focus expansion for comparisons.

## What The Vision Model Must Return

The model should return JSON in `vision_regions_v1` shape:

```json
{
  "provider": "Qwen-Qwen3.6-35B-A3B-IQ4_XS.gguf",
  "contract_version": "vision_regions_v1",
  "image_size": {
    "width": 1280,
    "height": 900
  },
  "screen_summary": "Browser page with top navigation",
  "state_guess": "seek home page",
  "regions": [
    {
      "region_id": "region_1",
      "label": "SEEK home logo",
      "role": "nav",
      "diagonal": {
        "x1": 166,
        "y1": 97,
        "x2": 273,
        "y2": 134
      },
      "description": "Home logo in the top navigation bar.",
      "ocr_text": "seek",
      "text_lines": ["seek"],
      "possible_destinations": ["home"],
      "anchor_relations": [
        {
          "anchor_id": "ocr_anchor_1",
          "text": "seek",
          "relation": "inside",
          "axis": "x_y",
          "confidence": 0.82,
          "evidence": "The logo wordmark belongs to the home navigation target."
        }
      ],
      "grounding_constraints": {
        "reference_frame": "top navigation bar",
        "text_inclusion_policy": "include_referenced_text",
        "text_anchor_frame": {
          "left_anchor_id": "ocr_anchor_1",
          "frame_bbox": {
            "x": 160,
            "y": 90,
            "w": 130,
            "h": 50
          }
        },
        "negative_constraints": [
          "Do not include the Job search nav text."
        ],
        "final_bbox_reason": "The target includes the blue icon and seek wordmark, excluding adjacent navigation labels."
      },
      "confidence": 0.78
    }
  ],
  "targets": [],
  "observers": [],
  "notes": []
}
```

Runtime handling:

- Normalize and clamp coordinates.
- Detect and scale Qwen-style `0-1000` coordinates when needed.
- Evaluate OCR anchor policy.
- Fuse visual regions with OCR into page structure.
- Rank candidates and select a click point only after local grounding and pre-click checks.

## Agent Click Decision Rules

The agent may click only when all of these are true:

1. The response came from `/action/execute_recognition_plan` or from a `/vision/recognition_plan` that will be executed through `/action/execute_recognition_plan`.
2. `pre_click_decision.allowed == true`.
3. `selected_click_point` exists.
4. `execution_path.pre_click_decision_used == true`.
5. The target is consistent with the user goal.
6. For visual/icon targets, OCR anchors were used or another strong local evidence source explains the target.

The agent must not click when:

- the coordinate only appears in `vision_regions_v1`
- `pre_click_decision.allowed == false`
- `ocr_anchor_grounding_fallback_used == true` and no other strong evidence exists
- the selected target is ad-like, blocked, ambiguous, or outside the candidate bbox
- the live window changed after planning

If blocked, the agent should:

1. Capture again.
2. Narrow the ROI.
3. Re-run recognition with OCR anchors.
4. Inspect overlay and traces.
5. Ask the user before any risky action.

## Minimal API Sequence For Agents

For live execution:

```text
POST /runtime/prepare            check/start local vision models
GET  /apps
POST /apps/open                  optional, when the software is not running
GET  /session/windows
POST /session/bind_window
GET  /state
POST /action/type_text           optional, for text entry after binding/focusing
POST /vision/observe_screen
POST /vision/locate_target
POST /action/execute_recognition_plan  dry_run=true
POST /action/execute_recognition_plan  dry_run=false, only if the dry run is accepted
```

For offline/model testing:

```text
POST /state/capture_window
POST /vision/recognition_plan
POST /vision/render_recognition_plan_overlay
```

For OCR-only debugging:

```text
POST /vision/ocr_region
```

## Current Limitation

`POST /vision/recognition_plan` is the OCR-anchor-safe recognition endpoint today. Agents should prefer it, or call `/action/execute_recognition_plan`, which uses it internally.

`POST /vision/analyze` is lower-level visual analysis and should not be used by agents as the click-selection path unless the caller explicitly knows how to attach OCR anchors and run the downstream gates.
