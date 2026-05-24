# Agent API Workflow

This document defines the API-first workflow an upper-layer agent must follow when using this runtime.

The core rule is:

> The agent must not click from raw visual-model coordinates. It must call the runtime APIs, let the runtime attach OCR anchors, inspect the recognition plan, and only execute a click through the gated action endpoint.

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

## Required Live Agent Flow

Use this flow when the agent is controlling a real visible application window.

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
    "command": ["msedge.exe"],
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
      "agent_next_steps": [
        "Read screen_reading.ui.elements and ui.icon_candidates to decide what the user likely wants.",
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
      "execution_path": {
        "action_executed": false,
        "coordinate_source": "pre_click_decision_v1.selected_click_point",
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
- Still do not click directly. To click, call `POST /action/execute_recognition_plan`, which re-captures and rechecks before dispatching input.

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
4. Build `ocr_anchors_v1` from all OCR text boxes by default.
5. Attach OCR anchors to the visual-model prompt.
6. Normalize model regions into `vision_regions_v1`.
7. Fuse vision and OCR into `page_structure_v1`.
8. Build `screen_reading_v1`.
9. Rank candidates through `candidate_rank_v1`.
10. Run local narrow search on candidate crops.
11. Build `pre_click_decision_v1`.
12. Render a recognition-plan overlay when a trace is available.
13. Return the selected point without clicking because `dry_run == true`.

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
- If `pre_click_decision.allowed == false`, do not click. Re-observe, narrow the ROI, improve the goal text, or ask the user.

### 9. Execute The Click Only After The Plan Is Accepted

If the dry run is accepted and the user/agent wants to execute, call the same endpoint with `dry_run: false`. The runtime captures the live window again and re-runs the recognition gate before clicking.

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
        "post_click_verification_used": true,
        "coordinate_source": "pre_click_decision_v1.selected_click_point"
      },
      "recognition_plan_trace_path": "logs/traces/vision/...",
      "trace_path": "logs/traces/actions/..."
    }
  },
  "error": null
}
```

Agent decision:

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

For a recognition-plan call with OCR anchors enabled, the visual model receives:

1. The screenshot image.
2. A system instruction requiring JSON only.
3. A region-analysis prompt containing:
   - image width and height
   - task, app name, goal, and state hint
   - required `vision_regions_v1` JSON schema
   - bbox coordinate rules
   - OCR anchor grounding rules
   - compact OCR anchor payload
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

OCR anchor hints:
- OCR has already detected high-confidence text boxes
- OCR anchors use the same coordinate system as the image
- use anchors as spatial evidence, not as the object itself
- for icons without internal text, set text_inclusion_policy="exclude_text"
- for controls whose visible target includes text, set text_inclusion_policy="include_referenced_text"
- OCR anchor payload: <compact JSON>
```

Compact OCR anchor payload example:

```json
{
  "contract_version": "ocr_anchors_v1",
  "coordinate_space": "current_image",
  "image_size": {
    "width": 1280,
    "height": 900
  },
  "total_detected_count": 77,
  "anchor_count": 77,
  "anchor_fields": {
    "id": "anchor_id",
    "t": "text",
    "b": "[x,y,w,h]",
    "c": "[center_x,center_y]",
    "s": "confidence",
    "g": "goal_similarity"
  },
  "anchors": [
    {
      "id": "ocr_anchor_1",
      "t": "seek",
      "b": [176, 100, 50, 25],
      "c": [201, 112],
      "s": 0.96,
      "g": 0.72
    }
  ]
}
```

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
GET  /apps
POST /apps/open                  optional, when the software is not running
GET  /session/windows
POST /session/bind_window
GET  /state
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
