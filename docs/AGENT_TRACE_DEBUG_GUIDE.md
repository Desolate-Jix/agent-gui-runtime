# Agent Trace Debug Guide

Use this guide when an action fails or looks suspicious.

## Rule

Fix the primary failing layer before adding fallback behavior.

Fallback is acceptable only after the root cause is understood and the response clearly reports that fallback was used.

## What To Inspect First

For every failed or risky action, collect:

- API response
- `trace_path`
- screenshot path
- overlay path if present
- OCR result
- model input/output if a model was used
- candidate list
- selected bbox
- selected click point
- gate decision
- post-action verification

## Common Failure Layers

### Window / Screenshot

Symptoms:

- wrong app visible
- screenshot captured during page load
- old tab/window active
- window resized after coordinates were generated

Fix:

- re-bind target window
- wait for stable screenshot
- recapture
- do not reuse stale coordinates

### PathGraph / Inventory

Symptoms:

- missing button/card
- wrong region assignment
- duplicate nodes
- overlapping nodes that are not parent/child containment

Fix:

- rerun Learn Fast / Learn Deep
- add missing node or remove duplicate
- verify region ownership and scroll container

### OCR / Text Evidence

Symptoms:

- Chinese garbled in trace
- text missing or low confidence
- OCR disagrees with model label

Fix:

- verify file contents with UTF-8 / UTF-8-SIG
- inspect OCR bbox
- reuse previous OCR anchors where valid
- do not match mojibake literals

### Model Output

Symptoms:

- invalid JSON
- malformed bbox
- missing required fields
- very slow response

Fix:

- inspect raw model text in trace
- fix model prompt/contract first
- retry only after the expected JSON contract is clear
- do not hide protocol errors with silent fallback

### Candidate / Gate

Symptoms:

- selected target is wrong
- score gap is too small
- click point outside bbox
- local OCR mismatch

Fix:

- improve candidate rules
- add negative constraints
- rerun preview
- execute only after `pre_click_decision_v1` allows it

### Scroll

Symptoms:

- wrong pane scrolls
- content repeats
- scroll reaches footer but loop continues
- nested container scroll bleeds into list

Fix:

- specify `scroll_scope=container`
- provide target container id and bbox
- compare before/after content fingerprints
- stop after repeated no-progress observations

## Trace Size Guard

`write_trace` now truncates oversized strings, history lists, and binary/base64-like fields. If a trace contains `trace_truncated=true`, inspect the summary plus referenced screenshot/model paths instead of expecting the full payload inline.

New GB-scale trace files are a regression. Check `app/core/runtime_artifacts.py` and the action route that wrote the payload.

## Agent Trace Digest

Do not paste a full trace JSON into ChatGPT or another upper-layer agent. Long traces contain repeated candidates, OCR blocks, model I/O, screenshots, and scroll history; they usually exceed the useful context window and make the next agent miss the actual failure.

Use the digest script first:

```powershell
uv run python scripts\agent_trace_digest.py "logs\traces\vision\TRACE.json" --format text
uv run python scripts\agent_trace_digest.py "logs\traces\vision\TRACE.json" --format json
```

The digest emits `agent_trace_digest_v1` and keeps the fields an agent needs for the next decision:

- request goal, app, state hint, dry-run flag, approved plan id
- timings and model I/O status with short prompt/raw-output previews
- screen summary, PathGraph count, top candidates, and selected candidate
- VISTA ROI policy/source/fallback tier, processed size, crop bounds, and mapped point when present
- `pre_click_decision_v1` allow/block reason and candidate decisions
- action execution and post-click verification result
- screenshot, overlay, crop, and diff image paths

If the file is above the safety limit, the script returns `status=skipped_large_trace` instead of reading it into memory. Re-run with `--allow-large` only when you have a concrete reason and enough local resources.
