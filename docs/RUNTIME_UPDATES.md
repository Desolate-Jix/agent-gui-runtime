# Confirmed Runtime updates

**Task-plan settlement in 0.1.8/0.1.9:** if cleanup has completed but `settle` reports
`runtime_task_ledger_session_unsettled`, use the [0.1.10 recovery procedure](RUNTIME_018_SETTLEMENT_RECOVERY.md).
Do not delete registrations or task evidence. Active tasks and unknown input
remain maintenance blockers. Old refusals without sufficient original proof may
still refuse; recovery of every session is not guaranteed.

Available in Runtime **0.1.8**. Close and verify all old Runtime entrypoints,
then install 0.1.8 manually if upgrading from 0.1.7 or earlier: those installers
have no updater. [Release and downloads](releases/EXECUTION_018_20261024.md).

[简体中文](RUNTIME_UPDATES.zh-CN.md)

## Two independent products

Runtime updates its own execution files. The Amadeus HTTP MCP + Skill extension
continues to use the Amadeus catalog and its own confirmation/version lifecycle.
A compatible Runtime patch does not require reinstalling an unchanged extension.
Neither component silently installs the other.

Runtime launchers check the fixed project's stable GitHub releases in a separate
background process, at most once per day. Checks can be disabled; they do not
download payloads, call a vision/Decision API, cancel tasks or install anything.
`instant_status` reports a short cached update summary. A failed/offline check
does not prevent execution.

## Local maintenance commands

Run these from a PowerShell terminal in the installation. The wrapper uses the
installation's prepared Python environment; it does not install dependencies.

```powershell
.\scripts\update_runtime.ps1 -Action status
.\scripts\update_runtime.ps1 -Action check
.\scripts\update_runtime.ps1 -Action stage
.\scripts\update_runtime.ps1 -Action apply
```

`stage` downloads and verifies the selected release into a sibling staging
directory. It does not change installed files. `apply` shows the exact target
SHA-256 and requires it to be entered before installing. A local automation may
instead supply `--confirm-target <exact SHA-256>` to the Python CLI after the
operator has approved that specific target. Installing is not an MCP tool.

Close all Runtime clients, HTTP servers and model workers before applying.
Installation-wide kernel leases prevent an update racing with a new task.
Unresolved original input, missing cleanup evidence and crashed registered
sessions also block maintenance: process death alone is not proof of cleanup.
The updater does not terminate a task or delete its records to become idle.
`-Action settle` rechecks original evidence and clears only already-settled
registrations; unknown or incomplete input remains blocked.

```powershell
.\scripts\update_runtime.ps1 -Action disable-checks
.\scripts\update_runtime.ps1 -Action enable-checks
```

## Failure and rollback

Before changing code, the updater verifies file ownership against the installed
uninstaller's embedded manifest and retains a complete backup and persistent
transaction journal. The new uninstaller and ownership record change with the
payload, preserving normal installer/uninstaller compatibility. For normal
installations, the registered display version participates in the transaction.

After replacement, a fixed isolated import/schema check runs without creating
an input host or calling model APIs. Failure restores the previous owned files
and registered version. This is an installation health check, not proof that
every GUI workflow will work in the new version.

```powershell
.\scripts\update_runtime.ps1 -Action rollback
.\scripts\update_runtime.ps1 -Action recover
```

Rollback requires confirmation of the exact retained previous target. An
interrupted or failed rollback keeps its backups and blocks new Runtime starts.
`status` includes a recovery command using the old updater in the external
transaction backup, so recovery does not depend on importing partially replaced
installation code. Do not delete pending markers, journals or backups to bypass
recovery. No automatic replay of interrupted tasks occurs.

User data, models, secrets and Python environments are not version payloads and
are not rolled back or cleared. Dependency-lock, Python-contract or shipped
configuration changes, or crossing the current major/minor release line,
require a manual compatibility review and installer migration in this first
implementation. Local modifications or unknown file conflicts are refused.
Backups are retained; automatic garbage collection is not enabled.

## Source and trust

The source is pinned to `Desolate-Jix/agent-gui-runtime` stable GitHub releases.
Previews/drafts, arbitrary URLs/commands, unsafe ZIP paths, modified staging
files, size/hash mismatches and a different target reusing a seen version are
rejected. Release downloads are bounded and do not receive provider or MCP keys.
These checks use GitHub HTTPS and exact hashes with operator confirmation.
**The current installer is unsigned; hashes are not an independent publisher
signature. TUF/Authenticode/release-attestation verification is not implemented.**

Release preparation must publish matching `runtime-update.json`,
`AgentGUIRuntimeExecution-update.zip` and the immutable version's installer.
`scripts/build_runtime_update.py` creates the two update assets from a verified
installer build; it does not publish them. Existing releases without these
assets cannot be applied through this updater.

The Amadeus upstream implementation and its separate verification/activation
limits are recorded in [Amadeus update implementation](development/AMADEUS_UPDATE_IMPLEMENTATION.md).
