# Amadeus Windows GUI Runtime extension 0.0.4

[简体中文](README.zh-CN.md)

Connect Pi to an operator-started Windows GUI Runtime using **native Streamable
HTTP MCP** and a packaged execution Skill. Install Runtime **0.1.6** and extension
**0.0.4** from the same versioned `instant-v0.1.6` release. Manual distribution and
independent catalog approval are separate; no store approval is claimed.

## Downloads

- [Runtime 0.1.6 Windows installer](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.6/AgentGUIRuntimeExecution-Setup.exe)
- [Amadeus extension 0.0.4 wheel](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.6/amadeus_agent_gui_runtime-0.0.4-py3-none-any.whl)
- [Extension source archive](https://github.com/Desolate-Jix/agent-gui-runtime/releases/download/instant-v0.1.6/extension-source-0.0.4.zip)

Install the Runtime separately, then import the wheel in Amadeus; the wheel is
not the Runtime installer. See the [Runtime installation instructions](../../../README.md).
The earlier 0.0.2 stdio launcher remains a separate historical release.

## What runs where

| Component | Responsibility |
| --- | --- |
| Amadeus / Pi | Plans work, owns its approval UI, and uses the native HTTP MCP client. |
| Extension 0.0.4 | Resource-only HTTP connection declaration and Skill; no launcher, executable selector, model weights or dependencies. |
| Local Runtime | Owns the authenticated loopback MCP service, vision/Decision configuration, input authorization, receipts and cleanup. |

The Host uses Python 3.12. The Runtime 0.1.6 API route defaults new environments to
Python 3.12, requires **no local GPU or model-weight download**, and retains
supported Python 3.11 environments. Optional local-model setup remains
on its existing Python 3.11 contract. A shared Python minor version does **not**
mean sharing a virtual environment. Each component retains its locked dependencies.
The frozen 0.1.5 installer has no HTTP MCP entry point: use Runtime 0.1.6 and
confirm the version actually running.

## Start the local Runtime

Install the Runtime first. Install `uv` if setup requests it, then use the API
setup below. Copy `configs/vision-api-openai-luna.example.json` and
`configs/decision-profile.visual-execution.example.json` to private profile files;
configure their endpoints, model and task conditions as documented by the Runtime.
Keep the Decision thresholds and ordinary-review policy explicit. Provider calls
use the selected remote service and may incur charges. Set each profile's
`api_key_env` variable only in the Runtime process environment. The supplied
examples use `OPENAI_API_KEY`; never put a provider key in the extension.

Create a strong random **local connection token** of at least 32 characters and
store it privately. This is distinct from every model-provider API key. Prompt
for it without echoing it, then start the service in a dedicated console:

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

Run setup once; it may download the locked dependencies. Its generated standalone
stdio MCP configuration is not needed for this extension. Omit `-PythonVersion`
to retain an existing supported API environment; an explicit different minor
version requires a separate environment rather than an in-place replacement.

Input is disabled by default. Add the existing `--allow-local-input` option only
for an explicitly authorized desktop task; its existing meaning includes turning
automatic risk interception off. A token authenticates the connection; it does
not authorize arbitrary clicks, submissions, payments or unrelated file changes.
The service binds only `127.0.0.1` and checks Host/Origin before MCP processing.
Do not expose it through a public bind, tunnel or reverse proxy.

## Install and connect

1. Use a qualified Amadeus build with native HTTP MCP and Skill contributions.
   Current development checks target upstream `9547f39` / `0.17.1-alpha.1`.
2. Download and install the **0.0.4 wheel** in Settings → Extensions. Inspect the
   package identity and disclosure; installation starts disabled.
3. Set `runtime_url` to `http://127.0.0.1:17665/mcp` (or the port you selected).
   Use only the trusted local Runtime endpoint. Set secret `connection_token` to
   the token supplied to the Runtime console.
4. Bind both MCP and Skill to Pi, explicitly enable, apply the backend restart,
   and open a new Work session. Saved configuration is not proof it is loaded.
5. Discover tools and inspect `instant_status` before requesting input. Check the
   reported Runtime version and original receipts; do not assume a service has
   loaded the source you most recently edited.

The extension cannot start, install or upgrade the external Runtime. It does not
receive provider API keys. The `network: ["*"]` declaration discloses configurable
HTTP access; it is not an OS sandbox or permission to operate the desktop.

## Task and connection lifecycle

Use the packaged [Skill](src/amadeus_agent_gui/skills/gui-execution/SKILL.md) and
[reference](src/amadeus_agent_gui/skills/gui-execution/references/runtime.md).
Keep one MCP connection and one input owner throughout a task. Pending/unknown
input retains its original request/run IDs; never replay it under a new ID.

The 0.0.4 Skill describes both field-result review and the new pre-action Main
review contract. At a genuine `pre_action_review_packet.v1`, read the original
job under a new status request, view its bound **before** image, then use the
returned review and separate continue recipes. Review alone does not click.
Continuation retains the original job and candidate, with a fresh target-region
and input-gate check before one native dispatch. The older
`field_review_packet.v1` reviews already-entered text using its **after** image.
These are different scopes; never substitute a field ticket for a candidate.
Installed candidate05 acceptance passed a five-step direct Runtime workflow and
a four-step native Pi workflow after explicit TEST double refusal, with unchanged
thresholds. See [results and limits](../../../docs/verification/MAIN_PRE_ACTION_REVIEW_20261023.md).
Pi may natively resize the complete bound frame before showing it to its model;
this is not byte-identical delivery of the original PNG. These controlled,
assisted tests are not an unattended benchmark or a general accuracy/speed claim.
A release or version number does not establish catalog approval or the active
service's capability.

Close only task-owned windows, then call `instant_stop` and poll until
`host_alive=false`, `pending_ids=[]`, and `cleanup_verified=true`. A transport
disconnect is not cancellation or cleanup. A new Work may connect only after
the previous owner has completed the service's explicit release conditions.
Disabling/removing the extension does not shut down the independently started
Runtime daemon or delete its data; stop the service deliberately after cleanup.

## Migration and store review

0.0.3 changes configuration: `runtime_root`, `runtime_python`, profiles,
`api_key`, and `allow_local_input` no longer belong to the extension. Configure
these at the Runtime service; enter the two new connection settings explicitly.
Do not reinterpret an old provider API key as a connection token. Historical
0.0.2 bytes and acceptance evidence are not replaced by this candidate.

The immutable 0.0.4 wheel/source archive retains its build-time documentation,
including earlier pending labels. The current installation and verification
documentation records later acceptance without replacing those artifact bytes.

Curated admission excludes configuration selecting executables/modules. HTTP
uses the existing native contract rather than bypassing review through another
launcher. Wheel checks, pinned author preflight, native protocol calls,
desktop execution and independent catalog review are separate results. Check
the preparation report for what actually ran; unrun layers remain unqualified.
No author-written approval or fictional reviewer is included.

The package code is ISC. Runtime licensing and third-party components remain
separate. No user data, real profiles, tokens, model weights or Runtime payload
are embedded in this wheel.
