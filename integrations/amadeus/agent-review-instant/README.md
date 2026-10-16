# Windows GUI Runtime for Amadeus 0.0.2

[简体中文](README.zh-CN.md)

This wheel contributes one stdio MCP connection and one native Pi Skill. A stdlib-only launcher uses the explicitly configured **external execution Runtime installation and its Python 3.11**. The Runtime and this integration use the same maintained Runtime source; the adapter does not implement MCP messages, another executor, a plan parser or learning mode. It contains no Runtime payload, models, real profiles or credentials. The adapter itself runs in Amadeus's Python 3.12 environment.

**Compatibility:** execution Runtime **0.1.4 or 0.1.5** only, Windows, Amadeus Host Python **3.12**, and a prepared Runtime Python **3.11** environment. Use 0.1.5 for resumable Main review; accepting a 0.1.4 version marker does not add that feature to 0.1.4. The package is delivered as a local wheel, not through a marketplace.

**Frozen wheel:** [amadeus_agent_gui_runtime-0.0.2-py3-none-any.whl](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.5/amadeus_agent_gui_runtime-0.0.2-py3-none-any.whl), SHA256 `32d27ed81eab33db05ae2780b98a808205da5057ee98bd71bdad8382e35a6588`. This exact wheel has been built, installed, configured for Pi, enabled and loaded after backend restart. It includes the MCP launcher, Skill, reference and ISC license; no Runtime payload, user data, real profiles or key is included. This companion README is the current delivery guide; the frozen wheel's embedded description retains its earlier build-time notes. Runtime **0.1.5** and wheel **0.0.2** retain their versions and exact bytes throughout this review follow-up; neither was repackaged.

**Normal installed use:** two fresh synthetic Notepad edit → File → Save tasks completed through Chat → Pi → installed extension 0.0.2 → installed Runtime 0.1.5 in the same Amadeus product/Chat, with separate Pi Work and Runtime sessions. All **6 Runtime steps**, both exact disk results, owned-window closes and Runtime cleanups passed; text was dispatched once per task. The first task used one ordinary Luna review; neither task needed Main semantic override. Host's per-call permission approvals remain distinct. The second Pi Work corrected a policy-denied shell attempt and a missing-request_id SDK error before Runtime dispatch: this is not a zero-error first-attempt claim. Actual disable/restart, remove/restart and default data retention also passed.

**Recovery and limits:** an earlier unreleased payload passed the live04 **explicit TEST dual-refusal** path: original Pi saw the bound PNG, reviewed and continued the original command without retyping, completed the three-step save and cleanup; 8 acceptance checks and a 19-check read-only audit passed. That audit was not another desktop run, and this is not a natural model-error, accuracy or performance result or a new 0.1.5 Main-override run. Host `succeeded/partial/review_ready` is its user-review policy, separate from Runtime completion. The earlier cancelled normal05 and excluded interfered samples remain historical failures, not new successes. Wallpaper, acoustic/ASR, general compatibility, forced termination and complete cancellation/reconnect coverage are not established here. See the [acceptance record and limits](https://github.com/Desolate-Jix/agent-gui-runtime/blob/main/docs/verification/AMADEUS_PI_MAIN_REVIEW_20261015.md).

## Install the local package

1. Use a compatible Amadeus build with Pi, native MCP/Skill contributions and the local plugin manager. Earlier installed checks used Host base [a9a488ae](https://github.com/Code-Amadeus/Amadeus/commit/a9a488ae) with earlier revisions of [PR #225](https://github.com/Code-Amadeus/Amadeus/pull/225) and [PR #226](https://github.com/Code-Amadeus/Amadeus/pull/226) applied. The current review checkpoint below records the updated #225 head and #226's upstream merge; the earlier ready/unmerged notes are historical. Compatibility with every published Amadeus version is not claimed. The [Host profile](https://github.com/Code-Amadeus/Amadeus/blob/main/docs/extension_host_profile_v0.1.md) remains an experimental subset; no marketplace installation is required or available from this package.
2. Install the **execution Runtime** from [Runtime releases](https://github.com/Desolate-Jix/agent-gui-runtime/releases). For resumable Main review use **0.1.5**. Select the actual installation root containing `execution-installation.json` (`schema=execution_installation.v1`, `component=execution`, `version=0.1.5`) and `scripts/start_instant_mcp.py`; do not point to the installer EXE, a shortcut or the learning workbench.
3. Copy `configs/vision-api-openai-luna.example.json` and `configs/decision-profile.visual-execution.example.json` from that Runtime root into your own configuration directory. Keep them free of keys. Prepare Runtime dependencies using its maintained setup; replace the example paths below with your own existing installation and chosen configuration/data paths:

```powershell
$RuntimeRoot = 'C:\Path\To\Runtime'
$VisionProfile = 'C:\Path\To\Config\vision-api.json'
$SetupData = 'C:\Path\To\GuiSetupData'
Set-Location -LiteralPath $RuntimeRoot
.\scripts\setup_instant.ps1 -RecognitionSource external_api -ApiProfile $VisionProfile -DataDirectory $SetupData
$RuntimePython = Join-Path $RuntimeRoot '.venv-agent\Scripts\python.exe'
Test-Path -LiteralPath $RuntimePython -PathType Leaf
& $RuntimePython -I -B -c "import sys; print(sys.executable); print(sys.version); assert sys.version_info[:2] == (3, 11)"
```

The path is derived from `setup_instant.ps1`: external API setup creates `<RuntimeRoot>/.venv-agent/Scripts/python.exe`. Continue only after setup succeeds and the actual path/version check passes. The installer does **not** bundle this environment. Live acceptance reused an already prepared Python 3.11 environment; first-time dependency setup on a clean machine is not verified. Setup requires existing [uv](https://docs.astral.sh/uv/getting-started/installation/) and network access. For this extension route, **do not merge the separate manual MCP configuration generated by setup**; the installed extension supplies the connection. See the [Runtime setup guide](https://github.com/Desolate-Jix/agent-gui-runtime/blob/main/docs/EXECUTION_GUIDE.md) for setup details.
4. Download `amadeus_agent_gui_runtime-0.0.2-py3-none-any.whl` and verify the SHA256 above. In **Settings → General → Manage plugins**, choose the local wheel and review its identity, license, command and OS-access disclosure. It installs disabled. Enter the six settings below, bind both MCP and Skill to **Pi**, explicitly enable it and apply the backend restart. Verify the applied version/revision, then start a new Work; a saved setting alone is not a loaded receipt. No pip command, separate manual MCP entry or copied global Skill is needed for extension installation.

## Configuration and authority

The native manager owns installation, secret storage and activation. Review its full disclosure before confirmation. Installation starts disabled; saving configuration is not evidence that the backend has reloaded it. This package never runs Setup, pip, uv, model downloads or an installer on MCP startup. Removing the extension does not uninstall the external Runtime; the Host retains extension data by default unless the user explicitly chooses deletion.

| Setting | Required value |
|---|---|
| `runtime_root` | Absolute existing execution 0.1.4 or 0.1.5 installation root, containing `execution-installation.json` and the original `scripts/start_instant_mcp.py`. |
| `runtime_python` | Absolute existing Runtime Python **3.11** executable; no PATH fallback. It may be outside the installation root. |
| `api_profile` | Absolute approved non-secret vision JSON profile path. |
| `decision_profile` | Absolute approved non-secret Decision JSON profile path. |
| `api_key` | Amadeus **secret** configuration, passed only as `OPENAI_API_KEY` in the child environment. Never put it in commands, profiles, package files or notes. |
| `allow_local_input` | Boolean, default **false**. Set true only with explicit operator authorization for the current task. |

This package binds one shared key: vision `api_key_env`, Decision's effective `api_key_env`, and ordinary review's effective `ordinary_review_api_key_env` must all be `OPENAI_API_KEY`. Decision's omitted primary field defaults to that name; its omitted/null ordinary field inherits the primary name under the existing Runtime contract. An explicit different environment name fails clearly before starting Runtime; it is never rewritten and no unrelated provider key is inherited. Runtime itself still supports separate provider keys; this is only a package limitation. Endpoints, models, budgets, thresholds and review policy remain in the operator's existing profiles. The original Runtime validates their full schemas.

`allow_local_input=true` adds the original `--allow-local-input` flag. Its meaning in both supported Runtime versions includes **automatic risk interception OFF**; enabling the extension or Skill does not grant permission to act on arbitrary windows, submit/send, confirm, pay or modify unrelated data. Execute only the current explicitly authorized task, one input owner at a time, preserving Runtime/Amadeus gates and action-specific approvals.

The manifest truthfully discloses `network:["*"]`, `process:["*"]` and filesystem `* / read_write`: external profiles choose approved service endpoints, and Runtime can operate approved applications and files. These are **capability disclosures, not extra authorization or an OS sandbox**. `permissions.host` is empty. Do not infer that traffic is restricted to one vendor or that the launcher isolates desktop access. The operator must trust the selected Runtime installation, Python executable and profiles. The version marker check is compatibility metadata, not independent file authentication.

## Process and session behavior

The adapter checks absolute paths, execution marker schema/component and the explicit 0.1.4/0.1.5 version set, common key binding, exact boolean input setting, and the actual interpreter's Python version. Invalid configuration exits 2 with fixed diagnostic codes and no configuration values. Process launch errors exit 3. The original script receives `-I -B -X utf8`, `--data-dir <extension data>/runtime`, `--recognition-source external_api` and the two profile paths, plus the input flag only for explicit true. Keys are not argv. The child receives the shared key, UTF-8 settings and a small set of Windows OS environment entries; unrelated provider variables and `PYTHONPATH` are not forwarded.

The original Runtime inherits stdin/stdout/stderr directly. The adapter reads no MCP bytes, adds no stdout banner, creates no proxy protocol or retries, and propagates the child's normal exit code. Fixture tests prove live byte exchange, EOF delivery and child exit propagation. The normal installed tasks above verified cleanup after explicit owned close and Runtime stop. They do not prove automatic Runtime cleanup from a Pi disconnect, forced process termination or every cancellation point. Do not use disconnecting as a substitute for the Runtime lifecycle.

Use the packaged [Skill](https://github.com/Desolate-Jix/agent-gui-runtime/blob/main/integrations/amadeus/agent-review-instant/src/amadeus_agent_gui/skills/gui-execution/SKILL.md) and [reference](https://github.com/Desolate-Jix/agent-gui-runtime/blob/main/integrations/amadeus/agent-review-instant/src/amadeus_agent_gui/skills/gui-execution/references/runtime.md); the Host exposes their actual installed paths to Pi, without a global copy. Keep one MCP connection for one complete Work task; a saved Pi conversation does not keep MCP alive across Work runs. Discover actual tool names instead of guessing Pi hashes. Preserve original request/run/command IDs and bound images. Pending or unknown input is inspected, never replayed under a new ID.

Runtime 0.1.5 can keep the original live input job at `field_review_packet.v1` after an authenticated dual-model rejection. The original Agent reads the bound after image, copies the exact `caller_controls.review.request`, adds its actual verdict/reason, and then uses the separately returned `caller_controls.continue.request`. Review only records the outcome; explicit continue resumes the original thread without retyping. This confirms the already-entered text only: a requested submit suffix still goes through the existing fresh-target/input gates and result verification. The package does not implement that Runtime repair.

Visual Main review requires an **image-capable Pi execution model** and an adapter that preserves MCP image content. A text receipt alone does not prove the reviewer saw the bound after image. At the 2026-10-16 review checkpoint, PR #225 head `5b3a434ab8617e4eb2d7472f49fa8171ac445004` passed **24 native SDK + 21 Provider checks = 45 passed**, plus TypeScript typecheck; Root also verified **5 remote workflows and 15 check runs successful on this head**. The session-scoped public-hook repair preserves Provider/configuration ownership; if optional metadata repair cannot be applied safely, it retains Pi's native selection and gives one sanitized warning instead of a fatal extension error.

The earlier **17 SDK checks**, five-workflow green results and ready/unmerged notes belong to older revisions. The separate cancellation-cleanup PR #226 retains its **28 related checks** and was **merged upstream on 2026-10-16** as `5dd0b2f2355f0177b89b903b8bc34cd6939fa77e`. Other Host builds must provide equivalent behavior rather than being assumed compatible. The earlier live04 Pi received the original PNG before its bound review; this does not establish capture of provider raw HTTP payloads or general visual accuracy.

While the original execution is not terminal, retrieve its image by submitting a **new outer request** containing `agent_command_status` with `command_id=packet.execution_request_id`, then call `instant_image` on that status request ID. Do not call image directly on the unfinished original execution. Released **0.1.4 baseline limitation** remains: some `field_review` failures have no resumable ticket. If the active host supplies no actual review/continue recipe, stop and report; never guess tickets, restart input or relabel a failure. A version marker alone does not establish the new capability.

After settled input, close only windows owned by this task, check `window_closed`, then `instant_stop` and poll until `host_alive=false`, `pending_ids=[]`, `cleanup_verified=true`. Resolve a save dialog only when that exact choice is authorized. `capture` is just `{"kind":"capture"}`; it must not include a handle/process_id. `close_launched_window` uses `kind/handle/process_id` from the launch receipt and needs no invented `request.ownership`. Report task outcome separately from cleanup. Preserve browser data and isolated test profiles.

## Offline development

Prerequisites are existing Python 3.12 with setuptools >=77, existing Python 3.11, the installed `uv` build tool, and the Amadeus source tree. These commands install nothing and invoke only synthetic children/static Host checks:

```powershell
$env:AGENT_GUI_TEST_PYTHON311 = 'C:/explicit/python311/python.exe'
$env:AGENT_GUI_TEST_HOST_ROOT = 'C:/explicit/amadeus'
& 'C:/explicit/python312/python.exe' -I -B -X utf8 -m unittest discover -s tests -v
```

The tests cover transparent standard streams/EOF and nonzero child exit, Chinese/space paths, explicit flags, required/malformed config, wrong Python/version marker, common secret binding, and canonical Host manifest/Skill loading/native MCP projection. Synthetic credentials are fixtures, not live keys. Tests skip the relevant boundary if its explicit prerequisite is absent; a skipped run is not acceptance.

Build and inspect the selected compatible candidate without downloading dependencies:

```powershell
uv build --wheel --python 'C:/explicit/python312/python.exe' --no-build-isolation --no-index --offline --no-python-downloads --no-sources --no-config --no-create-gitignore --out-dir 'C:/explicit/evidence/dist' .
& 'C:/explicit/python312/python.exe' -I -B 'C:/explicit/amadeus/tools/extension_package.py' inspect-wheel 'C:/explicit/evidence/dist/amadeus_agent_gui_runtime-0.0.2-py3-none-any.whl'
Get-FileHash -Algorithm SHA256 -LiteralPath 'C:/explicit/evidence/dist/amadeus_agent_gui_runtime-0.0.2-py3-none-any.whl'
```

`uv build` builds the wheel without installing project dependencies; this package declares none. The explicit flags prevent index access, network/Python downloads and creation of an isolated dependency environment. No pip installation is required. Inspect actual wheel resources and its entry point before native installation. Offline tests, a wheel inspection and an MCP handshake are distinct from real input and lifecycle acceptance. No commit, installation, desktop/model calls or release publication is performed by these tests.

Keep development checks, historical fault-proxy tests, live task results and read-only audits separate; their counts are not additive and a skipped prerequisite is not acceptance. See the [verification document](https://github.com/Desolate-Jix/agent-gui-runtime/blob/main/docs/verification/AMADEUS_PI_MAIN_REVIEW_20261015.md) for the retained first failures, historical injection scope and current installed-use boundaries.

Wallpaper follow-up (2026-10-16): the null-display-name reporting defect in Lively 2.2.1.0 was confirmed by an earlier real original/fixed-copy comparison, and two Amadeus lifecycle cycles passed with that fixed copy. The machine's installed DLL was subsequently backed up and locally patched; this is a third-party local repair, not an official update and not part of this wheel or the Runtime installer. Those historical runs do not establish acceptance of the current Amadeus review candidate.

[PR #228](https://github.com/Code-Amadeus/Amadeus/pull/228) remains **DRAFT** at pushed head `6dfb187cad6535631048f11e3703b7d57b6147b3`, narrowed to `Preparing` / `Pending` / `Settled` phase rollback, primary/cleanup error preservation and process-identity cleanup ownership. **35 offline contracts passed**; the stock Lively false-empty report plus successful no-op Close remains an **unresolved counterexample, outside that passing count**. CI on this new head is running and its final result is unconfirmed; older five-workflow green/ready records are historical.

Root's real Close probe case03 observed normal nonempty reporting from the original Lively 2.2.1.0 DLL in an isolated copy, then the owned player's exit after exact-project Close. A nonexistent project also returned success, so an acknowledgement alone does not prove closure. False-empty reporting did not naturally recur in this run; the faulty-protocol case remains open. Other users must resolve an affected Lively installation separately; package installation alone does not establish wallpaper compatibility. Historical normal-path results remain in the Runtime release notes.
