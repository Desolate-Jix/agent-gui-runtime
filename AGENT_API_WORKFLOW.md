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

### 4.6 Scroll When Visible Information Is Incomplete

Use this only when the target window is bound and the agent needs to reveal more content before retrying the same goal. The main trigger is `fallback_plan.steps[].name == "request_scroll"` from Execute Mode.

```http
POST /action/scroll
Content-Type: application/json
```

Request:

```json
{
  "direction": "down",
  "wheel_clicks": 4,
  "dry_run": false,
  "enable_verification": true
}
```

Agent decision:

- Treat scroll as a reveal/navigation action, not a click permission.
- Use the suggested request from `fallback_plan` when present; otherwise choose `direction: "down"` for more lower-page content or `direction: "up"` to return to earlier content.
- The scroll point defaults to the center of the bound window. Provide `x` and `y` only when a specific scrollable pane has been visually reviewed.
- After a real scroll, inspect `post_scroll_verification` and trace evidence, then rerun the same `POST /action/execute_recognition_plan` goal on the new screenshot.
- The retry must still pass `pre_click_decision_v1`; never use scroll as a shortcut to dispatch a click.

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
  "agent_mode": "learn",
  "learn_depth": "fast",
  "write_policy": {
    "path_graph": true,
    "element_memory": false,
    "trace": true
  },
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
      "screen_map": {
        "contract_version": "screen_map_v1",
        "state_id": "state_...",
        "state_hint": "top navigation bar",
        "sections": [
          {
            "contract_version": "screen_map_section_v1",
            "section_id": "page_header",
            "label": "Top navigation",
            "role": "navigation",
            "bbox": {"x": 0, "y": 80, "w": 1280, "h": 120}
          },
          {
            "contract_version": "screen_map_section_v1",
            "section_id": "main_content",
            "label": "Main content",
            "role": "content",
            "bbox": {"x": 0, "y": 260, "w": 1280, "h": 520}
          }
        ],
        "summary": {
          "screen_summary": "Browser page with top navigation",
          "candidate_count": 4,
          "section_count": 2,
          "safe_candidate_count": 2,
          "blocked_candidate_count": 0
        },
        "candidates": [
          {
            "contract_version": "screen_map_candidate_v1",
            "candidate_id": "element_home",
            "label": "Home",
            "role": "button",
            "goal_hint": "button: Home",
            "expected_effect": "click may change the current interface",
            "risk_class": "safe_click_allowed",
            "section_id": "page_header",
            "bbox": {"x": 10, "y": 20, "w": 80, "h": 32},
            "click_point": {"x": 50, "y": 36}
          }
        ]
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
- Use `agent_mode="learn"` with `learn_depth="fast"` for quick map drafting. Use `learn_depth="deep"` when the same observe call should produce `path_graph_deep_review_v1`, `path_graph_delta_v1`, and an `element_memory_init_plan_v1`; the current deep pass is deterministic review/delta planning, while full second-model semantic refinement remains a later expansion.
- Respect `write_policy`: PathGraph writes are allowed in Learn by default, while Execute defaults to reading PathGraph without mutating it. Use `trace=false` only for preview/smoke paths where you intentionally do not want a trace artifact.
- Use `screen_map_v1` as the semantic page/action map for the existing path graph. It may include bbox and click-point hints, but those are observation evidence, not executable coordinates.
- Read `screen_map.sections[]` first to understand coarse layout such as top navigation, promotion strip, main content, lower content, and floating overlays; each candidate may carry `section_id`.
- `ocr_text_actions` candidates are OCR-backed discovery hints for page-body cards/buttons that the broad vision pass did not promote into `ui.elements`; treat them as Locate targets, not executable coordinates.
- `ocr_card_groups` candidates are card-level discovery hints. Their bbox intentionally covers a whole card/module so the map can reason about entries before Locate chooses an exact click target.
- `nav_text_action` candidates are intentionally generated from valid OCR text in the top navigation section so missed navigation labels still appear in the map.
- The observe trace preserves `screen_map_v1`; `/panel/inspect_trace` renders it as a `Path Map` stage so trace review can inspect the same path candidates, bbox hints, and click-point evidence.
- Execute/RecognitionPlan requests should carry the latest matching `observe_trace_path` when available. The runtime will reuse OCR anchors and emit `path_graph_recall_v1` before full candidate ranking, then merge eligible recalled map candidates into `candidate_result` so local OCR grounding and `pre_click_decision_v1` can verify them.
- Prefer `provider_mode: local_understanding` here. It is intended for the smaller local model that summarizes the whole screen for agent planning.
- Use `suggested_state_hint` as the next precise-localization `state_hint` default. It comes from the observation model's concise `state_guess`.
- When a concrete candidate is chosen, pass its label/goal hint plus the current `screen_map.state_id` context into the precise localization step.
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
  "observe_trace_path": "logs/traces/vision/20260608-...__observe-screen__seek.json",
  "agent_mode": "execute",
  "learn_depth": null,
  "write_policy": {
    "path_graph": false,
    "element_memory": true,
    "trace": true
  },
  "top_k": 5,
  "metadata": {
    "ocr_anchors": {
      "enabled": true,
      "max_anchors": "all"
    }
  }
}
```

When Locate, RecognitionPlan, or Execute follows an Observe on the same screenshot/window state, pass the Observe `trace_path` as `observe_trace_path`. The runtime reuses matching `ocr_anchors` from that trace instead of running the recognition-plan full-image OCR step again, and records the reuse status in `observe_trace_reuse`.
When the Observe trace also contains `screen_map_v1`, Locate returns `path_map_review_v1`. The review compares the current Locate AI/candidate evidence with the previous path map, proposes `additions` for missing precise candidates, and proposes scoped `removals` only for same-label or high-overlap path candidates that Locate has replaced.
RecognitionPlan/Execute also return `path_graph_recall_v1` when `screen_map_v1` is available. This is the Execute-mode state-match and PathGraph recall stage: it ranks map candidates against the current goal, provides `local_ocr_roi` hints, and promotes safe recalled controls into the same candidate list used by local grounding and the pre-click gate.

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
      "path_map_review": {
        "contract_version": "path_map_review_v1",
        "status": "ready",
        "scope": "same_label_or_high_overlap_only",
        "summary": {
          "addition_count": 1,
          "removal_count": 1,
          "kept_count": 0
        },
        "additions": [],
        "removals": [],
        "kept": []
      },
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
- In Execute Mode, keep `write_policy.path_graph=false` unless this request is intentionally reviewing or correcting the map. Successful execution should write ElementMemory, not rewrite structural PathGraph by default.
- Verified real Execute Mode clicks write `execute_transition_memory_v1` when `write_policy.element_memory=true`. Dry-runs, pre-click blocks, failed recognition, and failed post-click verification do not write execution memory.
- In VISTA Direct Execute Mode, read `recognition_plan.screen_inventory` / `parse_result.execute_fast_inventory` as the fast "what can be operated" inventory for the upper agent. When no Observe inventory exists, the runtime may build this from the bound window's UIA snapshot and filter browser chrome before VISTA grounding. This inventory is planning evidence only; it does not grant click permission.
- When execution cannot safely complete, read `fallback_plan`. It is an `execute_fallback_plan_v1` decision record that lists local rescan / PathGraph review / scroll-to-reveal / full OCR refresh / gated model regrounding steps. It never grants permission to click; the next attempt must still pass `pre_click_decision_v1`.
- If `fallback_plan.steps[]` contains `request_scroll`, call `POST /action/scroll` first, verify the scroll evidence, then rerun the same goal through `POST /action/execute_recognition_plan`.
- Prefer `provider_mode: local_grounding` here. It is intended for the larger local model that performs precise OCR-assisted target localization.
- Use `pre_click_decision.allowed` as the quality gate.
- Read `located_bbox` and `located_point` as the large model's no-click target proposal. For a visual-only icon it may be present while `selected_click_point` is null and `location_status` is `requires_pre_click_confirmation`.
- For a text-bearing clickable target, inspect the OCR-derived `located_bbox` / `located_point`. If the visual semantic bbox contains unreferenced OCR text outside the selected target text cluster, the fusion layer records `unreferenced_text_contamination` and keeps the target as a confirmation-required `precise_text_target`.
- For list-like text targets, the runtime no longer applies an `above_exclusion_boundary` from the nearest upper OCR row. Neighboring text above the target is not a special hard boundary, but any unreferenced OCR text inside the larger semantic bbox can still mark the candidate as review-only.
- `locate_target` may surface the best review candidate from `candidate_result.rejected[0]` so the desktop panel can auto-fill the candidate-box review fields. This still does not create an executable click point.
- Read `path_map_review` when present. The browser panel applies it to the current path graph by adding missing Locate-backed candidates and deleting only unclicked same-label/high-overlap stale controls. It is a map correction record, not click permission.
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
2. Call `POST /vision/recognition_plan` internally with the captured `image_path` and latest `observe_trace_path` when present.
3. If the Observe trace matches, reuse `ocr_anchors_v1` and build `path_graph_recall_v1`; otherwise run full-image OCR and build anchors.
4. Convert safe recalled PathGraph controls into `RecognitionCandidate` objects, dedupe them with visual/page-structure candidates, and send the merged top-k through local OCR grounding.
5. Retain `ocr_anchors_v1` from the reused or freshly scanned OCR evidence.
6. For `click_target`, attach a bounded `relation_matrix_compact` prompt projection: every selected row keeps OCR text and bbox coordinates, plus compact inclusion/exclusion policy rows.
7. Normalize model regions into `vision_regions_v1`.
8. Fuse vision and OCR into `page_structure_v1`.
9. Build `screen_reading_v1`.
10. Rank candidates through `candidate_rank_v1`.
11. Run local narrow search on candidate crops.
12. Build `pre_click_decision_v1`.
13. Render a recognition-plan overlay when a trace is available.
14. Save an `approved_recognition_plan_v1` record when the pre-click gate allows the selected point.
15. Return the selected point and `approved_plan_id` without clicking because `dry_run == true`.

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
      },
      "agent_step_result": {
        "contract_version": "agent_step_result_v1",
        "status": "dry_run_ready",
        "dry_run": true,
        "action_executed": false,
        "approved_plan_id": "86a4a4f0e6f24e70b3f58f26f285c943",
        "selected_click_point": {"x": 221, "y": 119},
        "evidence": {
          "input_image_path": "artifacts/screenshots/...",
          "recognition_plan_trace_path": "logs/traces/vision/...",
          "coordinate_overlay_path": "artifacts/review-overlays/...",
          "action_trace_path": "logs/traces/actions/..."
        },
        "post_click": {
          "enabled": false,
          "verified": null
        },
        "next_agent_action": "execute_approved_plan"
      }
    }
  },
  "error": null
}
```

Agent decision:

- Use `data.result.pre_click_decision.allowed` as the click gate.
- Use `data.result.selected_click_point` as the only executable coordinate.
- Use `data.result.agent_step_result` as the compact single-step result for the upper agent. Execute Mode does not run the next step internally; the agent reads this result and decides whether to call Execute again.
- Do not use raw `vision_regions.regions[*].bbox` as a click coordinate.
- If `ocr_anchor_grounding_used == false`, treat the plan as lower confidence and inspect `ocr_anchor_grounding_fallback_used`.
- The default 48-row prompt budget is not guaranteed to fit every dense page. A saved Seek/Serato test exhausted the anchored context and safely retried without prompt anchors; retained OCR then grounded the reviewed text-card point.
- If `pre_click_decision.allowed == false`, do not click. Read `fallback_plan`; when it asks for `request_scroll`, scroll the bound window and rerun the same goal before widening to heavier recovery.

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

If the dry run is accepted and the user/agent wants to execute, reuse the `approved_plan_id` returned by the dry run. The runtime validates that the same bound window handle is still active, the goal matches, the approval has not expired, and the approved click point is still inside the click-coordinate window. The approved record stores `coordinate_window_size` from the live capture (`live_capture.window_size` / image size) before falling back to the bound-window rectangle, because Windows can report minimized placeholder rectangles such as `-32000, -32000, 160x28` even when the screenshot and click coordinate space are valid. It then dispatches the click and runs post-click verification without running the large vision model again.

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
      "post_click_verification": {
        "verified": true,
        "before": {"image_path": "artifacts/screenshots/...before.png"},
        "after": {"image_path": "artifacts/screenshots/...after.png"},
        "diff": {"diff_image_path": "artifacts/screenshots/...diff.png"}
      },
      "agent_step_result": {
        "contract_version": "agent_step_result_v1",
        "status": "executed_verified",
        "action_executed": true,
        "selected_click_point": {"x": 221, "y": 119},
        "post_click": {
          "enabled": true,
          "verified": true,
          "before_image_path": "artifacts/screenshots/...before.png",
          "after_image_path": "artifacts/screenshots/...after.png",
          "diff_image_path": "artifacts/screenshots/...diff.png"
        },
        "next_agent_action": "done"
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

External single-step smoke:

```powershell
python scripts\smoke_execute_single_step.py --goal "click Learn more" --app-name edge
```

This command first captures the currently bound window through `/state/capture_window`, then runs a dry-run Execute call and prints `agent_step_result_v1` evidence. It does not click unless `--execute` is supplied.

### Optional Instruction Learning

For stable low-risk pages such as MouseTester, an agent can record a verified instruction path:

```json
{
  "goal": "点击此处测试",
  "app_name": "mousetesterweb",
  "learning_mode": "instruction",
  "dry_run": false,
  "enable_post_click_verification": true
}
```

After a successful real click, the response may include:

```json
{
  "learned_instruction_id": "9b53...",
  "learned_instruction_path": "artifacts/local-learning/instructions/9b53.../learned_instruction.json",
  "learned_instruction_bundle_dir": "artifacts/local-learning/instructions/9b53...",
  "learned_instruction_artifacts": {
    "bundle_dir": "artifacts/local-learning/instructions/9b53...",
    "source_image_path": "artifacts/local-learning/instructions/9b53.../source_window.png",
    "pre_action_image_path": "artifacts/local-learning/instructions/9b53.../pre_action.png",
    "post_action_image_path": "artifacts/local-learning/instructions/9b53.../post_action.png",
    "diff_image_path": "artifacts/local-learning/instructions/9b53.../post_action_diff.png",
    "target_crop_path": "artifacts/local-learning/instructions/9b53.../target_crop.png"
  },
  "learning_mode": "instruction"
}
```

A later repeat can reuse that instruction:

```json
{
  "goal": "点击此处测试",
  "app_name": "mousetesterweb",
  "learning_mode": "instruction",
  "learned_instruction_id": "9b53...",
  "dry_run": false,
  "enable_post_click_verification": true
}
```

Instruction-learning reuse is intentionally conservative in v1. It validates the same goal, app name, bound-window handle, window size, and click-point bounds before dispatching. It skips the vision model but still performs real click dispatch and post-click verification. If validation fails, the upper-layer agent should fall back to the normal recognition path.
The learning bundle is permanent local evidence, not part of the rolling screenshot cache. The desktop response path graph shows the bundle as a learning-asset artifact node so a test operator can inspect which saved screenshots/crops back the reused point.
Successful reuse does not write a new learned instruction record; refresh learning by running the normal recognition path again.

Instruction-learning flow:

```text
First successful run

User instruction
  |
  v
POST /action/execute_recognition_plan
goal = "点击此处测试"
learning_mode = "instruction"
  |
  v
Live capture of the bound window
  |
  v
recognition_plan_v1
OCR / UIA / Vision / Candidate rank / Narrow search
  |
  v
pre_click_decision_v1
  |
  +-- rejected --> no click, no learning record
  |
  v
selected_click_point
  |
  v
real click
  |
  v
post-click verification
  |
  +-- failed --> return failure, no learning record
  |
  v
write learned_instruction_v1
artifacts/local-learning/instructions/{id}/
  learned_instruction.json
  source_window.png
  pre_action.png
  post_action.png
  post_action_diff.png
  target_crop.png
  |
  v
return learned_instruction_id
```

```text
Repeat run

User repeats the same instruction
  |
  v
POST /action/execute_recognition_plan
goal = "点击此处测试"
learning_mode = "instruction"
learned_instruction_id = "..."
  |
  v
load learned_instruction_v1
  |
  v
validate reuse
goal / app_name / window handle / window size / point bounds
  |
  +-- failed --> return learned_instruction_reuse_failed;
  |              upper-layer agent falls back to normal recognition
  |
  v
reuse selected_click_point
  |
  v
real click
  |
  v
post-click verification
  |
  +-- failed --> return failure;
  |              upper-layer agent falls back to normal recognition
  |
  v
return success
```

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
