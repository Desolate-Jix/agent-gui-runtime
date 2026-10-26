# Amadeus Windows GUI Runtime Connector 0.0.5

[简体中文](https://github.com/Desolate-Jix/agent-gui-runtime/blob/amadeus-extension-v0.0.5/integrations/amadeus/agent-review-instant/README.zh-CN.md)

This author-published connector connects Pi to a **separately installed and
operator-started Windows GUI Runtime** over native Streamable HTTP MCP. It
contains a connection declaration and execution Skill, not the Runtime.
**Independent store review is pending; publication is not store approval.**

## Downloads and compatibility

- [Connector 0.0.5 release](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/amadeus-extension-v0.0.5)
- [Connector wheel: amadeus_agent_gui_runtime-0.0.5-py3-none-any.whl](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/amadeus-extension-v0.0.5/amadeus_agent_gui_runtime-0.0.5-py3-none-any.whl)
- [Connector source: extension-source-0.0.5.zip](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/amadeus-extension-v0.0.5/extension-source-0.0.5.zip)
- [Author preflight: preflight.json](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/amadeus-extension-v0.0.5/preflight.json)
- [Recommended Runtime 0.1.8 Windows installer](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.8/AgentGUIRuntimeExecution-Setup.exe)
  and [Runtime release/checksums](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.8)

Install the Runtime yourself on the Windows computer running Amadeus, then
import the connector wheel. See the [Runtime installation guide](https://github.com/Desolate-Jix/agent-gui-runtime/blob/instant-v0.1.8/README.md#quick-start).
The connector and Runtime have independent version numbers and release tags;
connector 0.0.5 does not update Runtime 0.1.8.

| Combination or capability | Supported scope and evidence |
| --- | --- |
| Runtime 0.1.8 + connector 0.0.5 | Recommended released Runtime and this connector. New installed GUI acceptance of this exact combination and independent store review remain pending. |
| Runtime 0.1.6 + connector 0.0.4 | Historical controlled installed Pi evidence covers four navigation steps, explicit TEST double refusal, Main review/continue and cleanup. It is not a new 0.0.5/0.1.8 test. |
| Minimum Runtime contract | 0.1.6 introduced the authenticated HTTP MCP entry point and pre-action review needed by this connector route; the running service must also supply the field-review/continue contract. |
| Runtime 0.1.5 or earlier | Not usable by this HTTP connector: 0.1.5 has no HTTP MCP entry point, even though field-result review existed there. |
| Runtime 0.1.7 current-Agent mode | Not qualified through Amadeus by this connector. This Skill supports the existing **external API route** only. |
| Later Runtime or Amadeus versions | Compatibility is not assumed. A maintainer must manually check the actual version, native HTTP/Skill support, required tools and command schemas, authentication and cleanup/review contracts. No automatic compatibility probe is supplied. |

The recorded Amadeus baseline is upstream `9547f39` / `0.17.1-alpha.1` with native
Pi 1.2.0. The [historical evidence and its limits](https://github.com/Desolate-Jix/agent-gui-runtime/blob/instant-v0.1.6/docs/verification/MAIN_PRE_ACTION_REVIEW_20261023.md)
are separate from the [0.0.5 author validation record](https://github.com/Desolate-Jix/agent-gui-runtime/blob/amadeus-extension-v0.0.5/docs/verification/AMADEUS_CONNECTOR_005_20261026.md)
and independent store review. Do not treat a release number or preflight success
as proof of desktop execution.

## What runs where

| Component | Responsibility |
| --- | --- |
| Amadeus / Pi | Plans the task, owns its approval UI and uses its native HTTP MCP client. |
| Connector 0.0.5 | Resource-only connection declaration and Skill; no launcher, executable selector, model weights or Runtime dependencies. |
| Local Runtime | Provides the authenticated loopback service, vision/Decision configuration, input gates, receipts and host cleanup. It is installed and started independently. |

The Host uses Python 3.12. The Runtime API setup defaults new environments to
Python 3.12, retains supported Python 3.11 environments and requires **no local
GPU or model-weight download**. Optional local-model setup has its separate
Python 3.11 contract and is outside this connector's supported route. A shared
Python minor version does not mean sharing a virtual environment; each
component keeps its locked dependencies.

## Start the local Runtime

Install the Runtime first. Install `uv` if setup requests it. Copy
`configs/vision-api-openai-luna.example.json` and
`configs/decision-profile.visual-execution.example.json` to private profile
files, then configure endpoints, models and task conditions according to the
Runtime guide. Keep Decision thresholds and ordinary-review policy explicit.
Screenshots and task information used for recognition/review are sent to the
selected model services. Those services may charge for calls; this wheel
includes no model service or API credit. Set each profile's `api_key_env` only
in the Runtime process environment. The examples use `OPENAI_API_KEY`; never
put a provider key in connector settings.

Generate and privately store a strong random URL-safe **local connection
token** of 32–256 characters (for example, using `secrets.token_urlsafe(32)` in
your trusted Python environment). It is distinct from every model-provider API
key. Prompt for secrets without echoing them, then start the service in a
dedicated console:

```powershell
$RuntimeRoot = 'C:\Path\To\Runtime'
$RuntimeData = 'C:\Path\To\GuiRuntimeData'
$VisionProfile = 'C:\Path\To\Config\vision-api.json'
$DecisionProfile = 'C:\Path\To\Config\decision.json'
$env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new('', (Read-Host 'Provider API key' -AsSecureString)).Password
$env:AGENT_GUI_MCP_TOKEN = [System.Net.NetworkCredential]::new('', (Read-Host 'Local MCP connection token' -AsSecureString)).Password
Set-Location -LiteralPath $RuntimeRoot
& '.\scripts\setup_instant.ps1' -RecognitionSource external_api -ApiProfile $VisionProfile -DataDirectory $RuntimeData
& '.\.venv-agent\Scripts\python.exe' -I -B -X utf8 scripts/start_instant_mcp_http.py `
  --data-dir $RuntimeData --port 17665 --recognition-source external_api `
  --api-profile $VisionProfile --decision-profile $DecisionProfile
```

Run setup once; it may download locked dependencies. Its generated standalone
stdio MCP configuration is not needed for this connector. Omit `-PythonVersion`
to retain an existing supported API environment. An explicit different minor
version requires a separate environment rather than an in-place replacement.
Keep this console open while Amadeus uses the service.

Input is disabled by default. For an explicitly authorized desktop task, append
the existing `--allow-local-input` option to the final startup command. **This
option also turns automatic risk interception off.** A token authenticates the
connection; it does not authorize arbitrary clicks, submissions, payments or
unrelated file changes. The service binds only `127.0.0.1`, validates Host and
rejects browser Origin headers before MCP processing. Do not expose it through
a public bind, tunnel or reverse proxy.

## Install and connect

1. Use an Amadeus build with native Streamable HTTP MCP and Skill contributions;
   check its actual installed version against the recorded baseline above.
2. Download and install the **0.0.5 wheel** in Settings → Extensions. Inspect its
   identity and disclosure; installation starts disabled.
3. Set `runtime_url` to `http://127.0.0.1:17665/mcp`, or the port you selected.
   Use only your trusted local Runtime. Set secret `connection_token` to the
   same local token supplied to the Runtime console, not a model API key.
4. Bind both MCP and Skill to Pi, explicitly enable, apply the backend restart,
   and open a new Work session. Saved configuration does not prove it is loaded.
5. Inspect the MCP initialization version and discovered tools, then read
   `instant_status` before requesting input. Required tools are `instant_start`,
   `instant_status`, `instant_run`, `instant_result`, `instant_image` and
   `instant_stop`; their schemas must support the task-plan, original-command
   status and review/continue operations described in the packaged Skill.
   Check actual returned review recipes when that state occurs. This is a
   manual check, not automatic compatibility certification.

The connector cannot start, install, upgrade or reconfigure the external
Runtime and does not receive provider API keys. `network: ["*"]` discloses
configurable HTTP access; it is not an OS sandbox or desktop authorization.

## A small reproducible task

Use a synthetic temporary fixture; do not open personal files. Install 7-Zip
yourself. Before connecting Pi, manually prepare two empty folders in a new
temporary root, for example:

```powershell
$FixtureRoot = Join-Path $env:TEMP ('amadeus-gui-demo-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path (Join-Path $FixtureRoot 'Documents\Reports'), (Join-Path $FixtureRoot 'Documents\Receipts')
$FixtureRoot
```

Manually open a fresh 7-Zip File Manager window at that exact root. Record its
actual path, and tell Pi to select that observed window. The prepared window is
operator-owned; selecting it does not make it task-owned. Authorize only this
task, with local input explicitly enabled:

> In the prepared 7-Zip window at `<actual FixtureRoot>`, use folder navigation
> only: open Documents, open Reports, go Up once, then open Receipts. Verify the
> displayed path is `<actual FixtureRoot>\Documents\Receipts`. Do not create,
> rename, delete, edit, compress or extract anything, enter credentials, open
> another location or close the operator-prepared window. Stop and report any
> uncertain input or review without a valid ticket. After the task, settle the
> original receipts and verify Runtime host cleanup.

Acceptance requires four successful original navigation steps, bound image
evidence of the final path, an unchanged fixture tree and verified host cleanup.
Report any Main review or assistance. Do not count launch acknowledgements,
pending receipts or an uninspected screenshot as success. No external data write
is authorized; the fixture is created manually beforehand. It is a
navigation example, not compression/extraction or a performance benchmark.

## Task, review and cleanup

Use the packaged [Skill](https://github.com/Desolate-Jix/agent-gui-runtime/blob/amadeus-extension-v0.0.5/integrations/amadeus/agent-review-instant/src/amadeus_agent_gui/skills/gui-execution/SKILL.md)
and [reference](https://github.com/Desolate-Jix/agent-gui-runtime/blob/amadeus-extension-v0.0.5/integrations/amadeus/agent-review-instant/src/amadeus_agent_gui/skills/gui-execution/references/runtime.md).
Keep one MCP connection and one input owner for the whole Work. Pending,
unknown or interrupted input keeps its original request/run/command IDs; never
replay it with a new ID to extend a wait.

At a genuine `pre_action_review_packet.v1`, read the original job through a new
status request, inspect that status request's bound **before** image, then copy
the returned review recipe and use its separately returned continue recipe.
Review itself does not click. Continuation retains the original job/candidate
and must pass a fresh target-region check and existing input gates before one
dispatch. At `field_review_packet.v1`, inspect the bound **after** image of the
already-entered text; continuation does not retype. A field review does not
approve a candidate or prove a later submission succeeded. Without a genuine
resumable ticket, or with stale evidence, stop and report the original state.

Historical Pi evidence used a natively resized complete bound frame, not
byte-identical original PNG delivery. The controlled, assisted 0.0.4/0.1.6
tests establish their stated recovery scope, not unattended accuracy, speed or
new-combination acceptance.

Close only task-launched windows using their returned identities, and verify
`window_closed`; retain an operator-prepared window as in the example above.
Then call `instant_stop` and poll until `host_alive=false`, `pending_ids=[]` and
`cleanup_verified=true`. Only then release the HTTP MCP owner so another Work
can connect. A disconnect is not cancellation or cleanup. Disabling/removing
the connector changes its Host-side connection configuration; backend changes
follow the Host's restart requirements. It does not stop or uninstall the external
Runtime or delete its data. Finish cleanup before disabling/removing;
stop the independent service deliberately afterward if desired.

## Troubleshooting and recovery

| Symptom | What to check and do |
| --- | --- |
| Connection refused, timeout or no tools | Confirm the Runtime console is still running, setup succeeded, and `runtime_url` uses the actual loopback port and `/mcp`. Start the service with the command above if it was never started. Do not launch a second copy while another owner/input is unresolved. |
| HTTP 401 / `authentication_required` | The two local tokens must match. Enter the local token in secret `connection_token`; a provider API key is wrong here. Do not paste secrets into logs. If the daemon token must change, first settle the old task and cleanup, then restart deliberately and reconnect. |
| HTTP 404, 421 or 403 | Use `http://127.0.0.1:<port>/mcp` directly through Amadeus's native MCP client. Check the endpoint/port; remove any proxy or browser route. The server rejects invalid Host or browser Origin headers. |
| Missing HTTP, tools, schema or review/continue recipe | Manually check the installed and MCP-reported Runtime version and actual schemas. 0.1.5 cannot serve this connector. For an unsupported contract, stop before new input; after settling any old owner, install/configure the recommended Runtime separately and recheck. Never invent a ticket or assume a later version is compatible. |
| Input disabled or model/profile error | Confirm the private API/Decision profiles and their environment-variable names in the Runtime console. Enable `--allow-local-input` only for an authorized task, remembering that it turns automatic risk interception off. Do not change thresholds/prompts to force a pass; settle the current task before restarting configuration. |
| Cancel requested, timeout or disconnect during input | Preserve original IDs and inspect original status/results. Cancellation is not terminal until confirmed. If the original live connection remains usable, follow its actual cancel/status recipe and wait for settlement, then clean up. If it is lost, preserve diagnostics and stop for operator recovery; a new Work is not the old MCP owner. Never replay unknown input. |
| `input_owner_conflict`, `runtime_cleanup_required` or old owner not released | Return to the original live Work, settle pending receipts, close its owned windows, call `instant_stop`, verify all cleanup conditions and release that native session. Inspect `cleanup_pending` diagnostics and resolve the specific blocker before retrying cleanup only. If the original owner is unavailable, retain evidence and obtain Runtime maintenance help. Do not steal ownership, delete queues/locks/session records or repeatedly reconnect/restart to bypass the gate. |

The author-side source 0.1.8 check observed that a stopped session's maintenance
registration was not immediately retired after two start/stop/release cycles in
one HTTP service, although both hosts exited. The updater separately validates
original settlement evidence and can retire settled registrations; this check
did not reproduce a blocked update. Host cleanup and maintenance readiness are
separate results. Retain original session evidence and request Runtime support
if maintenance is refused; do not delete locks or registrations. See the
[validation scope](https://github.com/Desolate-Jix/agent-gui-runtime/blob/amadeus-extension-v0.0.5/docs/verification/AMADEUS_CONNECTOR_005_20261026.md).

## Version changes and store status

0.0.5 changes documentation/disclosure and package metadata. It does not change
connection configuration, permissions, input execution or Runtime code. Existing
0.0.3/0.0.4 `runtime_url` and `connection_token` settings need no migration.
The historical 0.0.2 stdio launcher and immutable 0.0.4 artifacts remain intact.
When migrating from 0.0.2, configure Runtime paths, profiles, provider keys and
local-input settings at the independent service; explicitly fill the two
connector settings. Never reinterpret an old provider key as a connection token.

Author publication, wheel/preflight checks, protocol checks, installed GUI
execution and independent catalog approval are separate results. This
author-published 0.0.5 distribution is **pending independent store review**;
it contains no author-written approval or fictional reviewer. Read the exact
scope of each linked result; unrun layers remain pending.

The connector code is ISC. Runtime and third-party licensing remain separate.
The wheel embeds no user data, real profiles, secrets, model weights or Runtime
payload.
