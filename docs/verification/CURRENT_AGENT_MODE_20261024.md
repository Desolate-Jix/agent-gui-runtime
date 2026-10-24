# Current Agent mode — source integration and offline verification

**Follow-up:** the changes below are included in execution 0.1.7. The
[live and installed acceptance](CURRENT_AGENT_LIVE_20261024.md) and
[release note](../releases/EXECUTION_017_20261024.md) record later delivery.
The original source checkpoint below is retained with its original scope.

Date: 2026-10-24. Published execution release remains **0.1.6**.
This report covers uncommitted source changes on
`codex/feat-amadeus-marketplace-http`, based on
`d49e946ba00fac474996b9edc0d4805b64b60fa3`.

已将“使用当前 Agent”加入源码入口。主 Agent 读取原图、定位并判断结果，Runtime 管理绑定、门禁、动作和回执。本轮只完成源码及离线验证，没有新模式实机验收、真实 API 调用、EXE 构建、安装、版本号修改或发布。

## Delivered behavior

- `scripts/execution_client.py --current-agent` selects the new
  `CurrentAgentClient`, with explicit client name and image capability
  declarations. Missing capability stays unknown; declarations do not grant
  input permission.
- A persistent connection and one serial state object track the original
  command, control requests, grounding capture and verification evidence.
  Managed input is limited to basic recognition clicks in this first adapter.
- The caller reads each original PNG, submits `grounding.v1`, resolves it and
  explicitly continues the original command under a new outer request ID.
  The adapter rechecks image hashes and binding. It does not run a model or
  send images to a separate service.
- A dispatched action requires the caller's judgment to bind the terminal
  after image before the next input is admitted. `uncertain` keeps input
  blocked; a failed/rejected input cannot be relabeled successful.
  Evidence binding is not proof that the caller understood the image.
- Pending and unknown outcomes are read through their original receipt;
  they are not replayed. Cancel waits for the actual worker terminal state.
  `agent_complete` marks business completion locally; `finish` or EOF closes
  owned resources and reports actual cleanup independently.
- `configure_instant_mcp.py --current-agent` generates checkout-local JSON and
  TOML for the existing MCP server route. It does not install global settings,
  reload clients, declare visual ability or enable input automatically.
- Both new entries isolate an inherited `AGENT_GUI_DECISION_PROFILE`.
  Conflicting API/model settings and administrator mode are rejected before
  connecting or writing configuration. Administrator environment propagation
  is outside the new adapter's support; legacy routes remain available.
- The adapter and bilingual usage pages are included in the source payload
  collector. The tree-external component preflight imports the adapter without
  constructing it or executing its main entry.

Current-Agent mode still uses the hosting client's model service and quota.
No separate Runtime API is required for this click loop; this is not a claim
of zero model cost or offline reasoning.

## Cancellation defect and initial test failure

The original `LearningBenchmarkClient.run` classified status and continue as
worker-control commands but omitted cancel. It compared a cancel receipt's
original worker ID against the outer cancellation request ID and could raise
`benchmark_agent_command_identity_mismatch`.

The fix adds cancel to that existing identity classification. Regression uses
real command validation, dispatch, `AgentCommandJobs`, persisted responses and
`InstantSession.result`, replacing desktop execution and MCP transport.
Wrong worker/control identities remain rejected, and cancelled work cannot
continue or replay input.

The first integrated run recorded **348 passed / 1 failed**. The failure was
in the new test fixture: it reported a live host via `status()` while
`_host_alive()` still reported no process. That sent an active worker through
the dead-host snapshot reader and occasionally hit a Windows file-sharing
error. The fixture now reports consistent liveness through both interfaces;
production recovery code was not changed. The nine cancel tests passed in
**30 independent pytest processes / 270 repeated checks**. Those repeated
checks are not additional unique coverage.

## Final integrated result

Python **3.12**, existing prepared Runtime environment:

```powershell
python -m pytest -p no:faulthandler -q tests/test_current_agent_cli.py tests/test_current_agent_client.py tests/test_current_agent_setup.py tests/test_agent_command_cancel_client.py tests/test_learning_benchmark_client.py tests/test_execution_client.py tests/test_execution_client_transport.py tests/test_execution_client_unbounded_plan.py tests/test_agent_command_jobs.py tests/test_instant_agent_command_image.py tests/test_grounding_handoff.py tests/test_vision_grounding_contract.py tests/test_recognition_source.py tests/test_api_cli_configuration.py tests/test_decision_configuration.py tests/test_agent_setup_scripts.py tests/test_execution_component.py
```

**368 passed in 102.35 seconds**, 17 test files. This is the final integrated
run, not a sum of overlapping agent test runs.

The four new test files contribute 85 cases within that total:

| Area | Cases | Evidence scope |
| --- | ---: | --- |
| Current-Agent CLI | 21 | Route selection, capability/auth separation, pre-connection conflicts, actual adapter ready/status/complete/finish through JSONL |
| Managed adapter | 40 | Fresh-image 20-step protocol loop, serial dispatch, identities, absent targets, pending/unknown readback, cancellation, altered/missing evidence, completion and environment isolation |
| MCP configuration | 15 | JSON/TOML output, effective Decision-off loading despite inherited profile, explicit route conflicts, legacy configuration preservation |
| Cancel regression | 9 | Real worker/receipt identity, original-ticket reads, cancelled terminal, no replay and original action gate |

The 20-step test uses synthetic PNGs, the actual grounding store/validator and
a simulated transport/dispatch. It is **not 20 real GUI actions**. The payload
tests exercise temporary source collection and isolated import preflight;
they are **not installer or EXE acceptance**.

Additional checks passed: CLI `--help`, `git diff --check`, current-document
local links, balanced Markdown fences and six parsed JSONL examples. The link
check scopes `AGENT_GUIDE.md` to its new dated section; five pre-existing links
to retired learning documents in historical sections remain outside this
change.

Local machine evidence is retained separately from the distributable:

- `D:/AgentGUI-Projects/evidence/current-agent-mode-20261024/offline-junit.xml`
  preserves the initial integrated failure.
- `D:/AgentGUI-Projects/evidence/current-agent-mode-20261024/offline-final-junit.xml`
  records the final 368-pass run.

Exploratory extended checks also encountered three pre-existing failures:
two retired learning-workflow takeover expectations and one vision dispatch
status expectation (`started` versus `unknown`). These were reproduced with
the original HEAD client; this work does not restore learning or count that
extended suite as fully passing. The final affected suite above is green.

## Remaining acceptance

1. Use the new adapter in a non-emulator application and MuMu, including at
   least one fresh-evidence sequence over 20 steps, with independently
   inspectable results and owned-resource cleanup.
2. Validate actual original-image delivery in the selected client. A declared
   capability is not live proof of that client's image-reading behavior.
3. Measure matched current-Agent/API tasks over repeated runs before claiming
   latency or cost savings. Caller gaps must not be reported as pure model
   inference; hosting-agent token usage remains unknown unless observed.
4. Freeze and validate a release candidate before distributing a new installer.

Keyboard input, scrolling, text replacement, batches and linear plans retain
their existing explicit-source contracts. They are not new managed-adapter
coverage; no-API v3/default visual input and automatic cross-window/restart
recovery are not claimed here. See the bilingual
[mode guide](../development/CURRENT_AGENT_MODE.md) /
[中文指南](../development/CURRENT_AGENT_MODE.zh-CN.md) for the capability matrix.
