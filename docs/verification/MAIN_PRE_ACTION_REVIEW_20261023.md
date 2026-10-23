# Main review before a rejected click — installed acceptance

**Release follow-up:** Runtime 0.1.6 and extension 0.0.4 use the accepted core below. Final distribution hashes and packaging-only changes are recorded in the [0.1.6 delivery note](../releases/EXECUTION_016_20261023.md). The candidate identities and publication status below describe the original acceptance snapshot; they are not rewritten as final installer hashes.

Date: 2026-10-23. Development candidates: Runtime **0.1.6 candidate05** and
Amadeus extension **0.0.4**. Neither candidate is published or approved by the
plugin catalog. The published 0.1.5 installer and 0.0.2 extension are unchanged.

本体与 Amadeus 均完成了“点击前双拒 → 原 Main 看绑定截图 → 审核 → 单独继续原任务”的安装态验收。
两条流程分别完成五步和四步，阈值未改。这是显式 TEST 双拒后的恢复能力测试，不是准确率或速度基准。

Both direct Runtime and Amadeus completed installed acceptance of pre-action
double refusal → original Main image review → separate continuation of the
original task. The workflows completed five and four steps, respectively, with
unchanged thresholds. Explicit TEST refusals qualify recovery, not natural
accuracy or speed.

## Frozen artifacts

| Artifact | Identity |
| --- | --- |
| Runtime installer | `AgentGUIRuntimeExecution-Setup.exe`, SHA256 `90c506f5666345379924faf1e335d6c5dd626f215fcebe2a92ddb2b01deb2042` |
| Extension | `amadeus_agent_gui_runtime-0.0.4-py3-none-any.whl`, 13,822 bytes, SHA256 `9acc7f5d1d667d1d44e3750cdf0f351abefeb5e5136b7fad91d50d77a6d29b31` |
| Extension source ZIP | 16,069 bytes, SHA256 `4b6ef25b280cdfd4b8e3567ef8321e9a9137019cfd9738add3453dfb2c9ddd8d` |
| Runtime source freeze | 22 source/test files; 19 production files in the payload; freeze SHA256 `adc59b0f2f0d774bdedaa27d1c78f7d4af026df9823109356db41623772e7b63` |
| Amadeus | `9547f39ad518134ce4594f5a52a92c8a61629f45`, 0.17.1-alpha.1; native Pi 1.2.0 |
| Live environments | Separate Runtime Python 3.12.10 and Amadeus Python 3.12.14 environments |

Both installers were exercised in native check-install mode under new owned
temporary roots. Candidate05 had **674/674 payload files** verified by size and
SHA before and after testing. Check mode did not replace the daily installation,
write its registry integration or replace its shortcut.

## What changed

The original live AgentCommandJobs job can wait at
`pre_action_review_packet.v1` after both authenticated candidate checks complete
without accepting the target. Its first local receipt proves no input was
dispatched. The serial native owner is released while Main reviews the evidence.

Main reads the original execution through a new `agent_command_status`, obtains
that status request's bound `instant_image(view="before")`, and submits the
actual returned review recipe. Review alone performs no input. A separate
continue resumes the same run, step, job, attempt and candidate. The original
model nonpasses remain recorded; a Main adoption is a separate fact. A fresh
capture, identity, geometry, visibility, cancellation and input gates still
precede native input. No new candidate, planning attempt or model retry is
created to obtain a pass.

The queue fix covers controls waiting to be picked up, controls whose outer
receipt has not yet been published, and temporary lock contention. A real
continue-admission lock reproduced a failure within 0.25 seconds: exact
`CommandQueueBusy`, a `ValueError` subclass, had been collapsed into permanent
plan-binding failure. Only that exact temporary exception now waits with the
job condition released, then repeats all checks. `TaskPlanCancelPending` and
other failures still reject. Neither the original deadline nor the two-second
post-capture dispatch lease is extended by contention.

## Installed workflows

| Route | Original workflow and result | Main assistance |
| --- | --- | --- |
| Direct public HTTP MCP | `direct-live-03`: Catalog → 2026 → October → Up → Up. All **5/5** original steps succeeded; final screenshot showed Catalog with the 2026 folder. The 73-byte marker retained its SHA. | One explicit TEST primary/ordinary candidate refusal pair; Root Main read the bound image, reviewed and separately continued the same original job. Year/month also used ordinary model review. |
| Installed Amadeus extension → native Pi → HTTP MCP → Runtime | `p5-live-prep/runs/normal`: Documents → Reports → Up → Receipts. All **4/4** original steps succeeded; final screenshot showed Receipts and `receipt-marker.txt`. | The original Pi read the actual pre-action image, supplied its own bound review, then separately continued the original wait. The harness supplied no Main verdict. |

The direct first step has two local invocations: the original verified
`not_dispatched` receipt and its resumed invocation. It retains **one logical
dispatch attempt**. A double click has two physical button presses; it is not
two submissions. The direct five-step plan contained three double clicks and
two single clicks: five actions, eight physical clicks.

All real observation and input used maintained Runtime interfaces. Codex native
Computer Use was not used. Test files were synthetic; browser profiles, caches
and existing tabs were not touched. The test harness required explicit
one-time Host tool grants. That caller approval time is not measured model
inference, user waiting or a product speed result.

### Image evidence across Pi

The packet binds the original 2560×1377 PNG. Amadeus/Pi's native image adapter
delivered a full-frame 2000×1076 derivative with original dimensions and a 1.28
coordinate mapping note. An offline replay through the actual Pi 1.2.0 Photon
Lanczos3 resize code reproduced the transmitted PNG **byte for byte**. There
was no crop or substituted frame. The review remained bound to the original
frame/hash and candidate. The image Pi received must therefore be described as
the same frame's scaled derivative, **not identical original PNG bytes**.

### Reported usage, not a cost or speed comparison

| P5 telemetry scope | Reported tokens |
| --- | ---: |
| Runtime Decision, seven real forwarded requests | 17,372 input; 0 output |
| Runtime visual grounding, four unique requests | 11,823 input + 1,761 output = 13,584 |
| Pi whole Work, 17 usage records | 80,895 input + 7,525 output + 653,696 cache-read = 742,116 total |

The forced TEST primary/ordinary pair reports zero usage and is excluded from
natural judgment claims. Pi's whole Work includes setup, status, review,
continuation and cleanup; its total is not one review request and is not all
uncached input. The full receipts were verbose. Reducing Pi context/token use
remains follow-up work; this acceptance does not establish token savings,
latency improvement or a combined dollar cost across different providers.

## Earlier failures remain failures

| Earlier candidate04 run | Result |
| --- | --- |
| `direct-live`, Notepad four-step edit/save | Main review/continue reached the native focus click. Typing then stopped at `ClipboardTransactionError: unsupported_format:not_started`, preserving the user's unsupported clipboard format. The full task failed; no clipboard clearing or successful save is claimed. |
| `direct-live-02`, four-step sibling-folder navigation | No click dispatched. Continuation stopped with `pre_action_review_no_longer_active`. The old log lacks the specific failing subcondition, so the later controlled lock-contention reproduction does not retrospectively prove this historical run's precise cause. |

Each new workflow used new task evidence; neither failure was replayed or
rewritten as a pass. [Candidate03's earlier field-result acceptance](AMADEUS_MARKETPLACE_HTTP_20261023.md#installed-desktop-acceptance)
is a separate historical result and did not qualify pre-action continuation.

## Checks and cleanup

- The latest affected regression passed **188 tests on Python 3.11** and
  **188 on Python 3.12**. The ten new contention tests are included in each 188,
  not additional unique checks. Independent review also ran the ten new cases
  and a 19-case existing subset; these overlap the implementation regression.
- Negative cases cover cancellation, closing, foreign queued input, changed
  bindings and expired evidence. A real 2.15-second post-capture contention test
  still rejects with zero clicks. Live capture-start timing was not separately
  serialized, so no live two-second measurement is inferred from wall times.
- Six frozen model/profile/prompt source files stayed byte-identical. Decision
  and ordinary Luna thresholds, prompts and provider selection did not change.
  TEST profiles only add the task conditions and route the explicit refusal
  pair through a test proxy; other provider requests remain real.
- Both successful runs closed their owned windows and verified
  `host_alive=false`, `pending_ids=[]`, `cleanup_verified=true`. The direct
  original native SDK session recorded DELETE 200. A new Pi-route client then
  initialized, read clean status and recorded its own DELETE 200. That new
  client's response must not be attributed to the old Pi session.
- Actual native ExtensionInstaller removal passed for the isolated 0.0.4
  installation. Runtime candidate04/05 check installations were uninstalled;
  only verified test markers and empty generated directories needed explicit
  follow-up cleanup. Both temporary check roots are absent. Installers, source
  artifacts and evidence remain preserved.
- Five owned service ports are closed. Both daily Amadeus configuration files
  retained their pre-test hashes. Parent-owned HTTP/proxy processes were
  explicitly terminated after cleanup; their exit code 1 is not described as
  a graceful daemon shutdown. Speech and wallpaper were not tested this round.

Local evidence is in the separate `amadeus-marketplace-20261023-02` evidence
round: the immutable candidate05 build/freeze, independent offline and live
audits, original receipts, native removal, post-live payload verification and
cleanup records. Raw screenshots, logs, sessions, credentials and private
configuration are excluded from public store materials.

Independent live audit identities: `candidate05-bare-direct03-live-audit.json`
SHA256 `0540845421f9621cf7448796447e7b3d91363780c51d42d3e03814853a48d8f1`
(13 bounded checks), and `candidate05-p5-native-pi-live-audit.json` SHA256
`779cef0e701a2524669e8be67fc7d359caa46240ad863b87cb4b2b9a35d3648e`
(11 bounded checks). The Pi Work's `execution=succeeded`,
`state=review_ready`, `completion=partial` is distinct from the original task
plan's four successful business steps. No typing or save-to-disk is claimed for
these navigation workflows.

## Delivery boundary

The fixed author checker at `1840c8e4f646992ddaebea3139c8895f29743a8f`
and the current Host's static wheel checks passed. These engineering results do
not constitute independent catalog approval. Store materials retain pending
reviewer/approval fields and unpublished download URLs. No Git push, release,
catalog submission or public upload was performed for this acceptance task.
