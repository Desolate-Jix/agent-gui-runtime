# GoalBinding model acquisition

This experimental CLI downloads pinned model files only. A successful download
does **not** certify runtime compatibility, create a runnable provider profile,
start inference, or establish model accuracy.

```powershell
uv run python scripts/fetch_goal_binding_model.py --inventory-only
uv run python scripts/fetch_goal_binding_model.py --provider-id ui_venus_1_5_2b_f16 --repo-id inclusionAI/UI-Venus-1.5-2B --full-checkpoint
```

- Model acquisition is restricted to `E:\模型测试`; its entire contents must stay
  within 50 GB (50,000,000,000 bytes), including staging and caches. Inventory is read-only.
- Canonical provider/repository selectors resolve a unique checked-in profile
  and its exact upstream commit. Unacquired or unresolved revisions do not fall
  back to `main`.
- `--profile PATH` remains supported. Canonical Transformers profiles fetch all
  files in the pinned checkpoint, including configs, processors, tokenizers and
  weight shards. GGUF profiles normally select only their declared model/mmproj.
- LFS files are checked against upstream SHA-256. Non-LFS files are checked for
  size and Git blob identity where supplied; every downloaded file receives a
  local SHA-256 and is rechecked before existing storage registration.
- Runtime/dependency installation and source/runtime identity registration are
  separate steps. This command never marks a model as tested or selected.
- UI-Venus Windows SDPA runtime materialization pins `pywin32==311`; its
  `ui_venus_runtime.pth` must expose the root, `win32`, `win32/lib`, `Pythonwin`,
  and `pywin32_system32` paths, then run `import pywin32_bootstrap`. The sealed
  no-model smoke imports all five
  `win32*` modules through the runtime’s ordinary startup path and verifies
  `WindowsProcessScope` before the profile can be used.
- Existing D-drive incumbent weights/runtime are not migration or deletion
  targets. This acquisition workflow does not access unique holdout.

## Existing read-only Qwen incumbent

```powershell
uv run --no-sync python scripts/prepare_goal_binding_incumbent.py --root "E:\模型测试"
```

This explicitly generates small identity documents and an outer-v1 profile under
`reports/managed-incumbent-<unique-id>/`; it does not copy/download weights, change
the checked-in profile, start a model, or write to the incumbent asset tree.
Reports count toward the same guarded 50 GB storage cap; publication holds the
existing acquisition quota reservation through writing, inventory and verification.
Only the exact
`qwen3_vl_8b_q4_k_m` incumbent can use the internal
`goal_binding_managed_incumbent_artifact_manifest_v1` variant. Challenger download
manifests and their path restrictions are unchanged.

The manifest binds the existing managed configuration to resolved D-drive model,
Q8_0 mmproj, server and every adjacent DLL; model/mmproj hashes must match pinned
`Qwen/Qwen3-VL-8B-Instruct-GGUF@f982a07559d4a2f6c8744d840bf6fccab30eea96`.
Known worktree junctions are resolved and bound, not copied or generally trusted.
Source/preprocessing records retain expected current-repository code hashes,
Git base revision plus modified tracked-code paths, and interpreter/dependency
versions and RECORD identities where available. Parent and worker verify these
expected identities before loading; cleanup rechecks them. Changing source,
runtime, environment, selected paths or DLL inventory invalidates the profile.
This is reproducible local identity binding, not protection against an omnipotent
administrator rewriting both data and verifier.

The script prints the generated profile path. After materialization, the operator
must review it and deliberately copy its public relative-path/SHA metadata into
the checked-in incumbent profile for the thin runner CLI; generation never does
that automatically. Absolute local identities remain in E-drive reports. Seal
only after code/environment changes are complete, then run without changing the
sealed inputs. The checked-in template remains non-runnable until this explicit
materialization/review step. No actual model or quality result is implied.

The integration checks also reproduced a mailbox polling race: an atomic
`responses/*.json.tmp` rename could occur between its existence and size checks.
Only that temporary-file disappearance is ignored for the current scan. Existing
oversized temporary files, missing final outputs, timeouts, hashes and exact
identities still fail closed.

Managed incumbent acquisition now uses a server-only nested Windows Job rather
than sharing the worker's outer Job. Existing managed release can therefore
terminate its server scope without killing the worker before its cleanup receipt
is written; the outer Job still owns the worker and descendants. Acquisition
restores the prior scope environment even on failure and closes its child Job.
A no-model Windows subprocess regression reproduced exit 197 before this fix
and verifies server absence, receipt publication and continued outer ownership
after it. The failed attempt is not repaired or scored retroactively. Re-seal
the incumbent code identity before a new real run; this regression alone is not
a successful model benchmark.
