# MouseTester Live Execute Golden Checklist

Case: `mousetester_live_execute_unicode_goal_20260513_182111`

Use this checklist when validating that the recognition -> execute -> validation chain has not regressed.

## Golden Artifacts

- Recognition trace: `recognition_trace.json`
- Action trace: `action_trace.json`
- Execute response: `execute-response.json`
- Before screenshot: `before_full.png`
- After screenshot: `after_full.png`
- Diff screenshot: `diff.png`
- Validation summary: `validation_summary.json`

## Smoke Command

```powershell
uv run python scripts\evaluate_mousetester_traces.py --cases configs\mousetester_eval_cases.json
```

Expected current result:

- `missing_case_count == 0`
- `passed_case_count == case_count`
- `pass_rate == 1.0`
- `pre_click_pass_rate == 1.0`
- `action_execution_pass_rate == 1.0`
- `semantic_verification_pass_rate == 1.0`

## Manual Checks

- The recognition trace goal is exactly `点击此处测试`, not `??????` or mojibake.
- The top candidate label/text is `点击此处测试`.
- The top candidate has `screen_reading_score` and UIA evidence reasons:
  - `screen_reading_uia_goal_name_match`
  - `screen_reading_uia_invoke_pattern`
- `pre_click_decision.allowed == true`.
- `selected_click_point == clicked_point == {x: 1434, y: 433}` for this captured run.
- The click point is inside the target bbox `{x: 1398, y: 424, width: 73, height: 20}`.
- Generic post-click verification is true and records a changed diff near the target.
- MouseTester semantic verification is true.
- Target-area OCR changes from `点击此处测试` before the click to `超时/单击` after the click.

## What This Baseline Proves

This baseline proves the current mainline can carry a Unicode Chinese goal through `execute_recognition_plan`, run fresh internal recognition, select the UIA/OCR-supported MouseTester target, pass the existing pre-click gate, execute only the gated point, and validate the real page change with both screenshot diff and target-area OCR evidence.
