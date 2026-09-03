# GoalBinding model acquisition

This experimental CLI downloads pinned model files only. A successful download
does **not** certify runtime compatibility, create a runnable provider profile,
start inference, or establish model accuracy.

```powershell
uv run python scripts/fetch_goal_binding_model.py --inventory-only
uv run python scripts/fetch_goal_binding_model.py --provider-id ui_venus_1_5_2b_f16 --repo-id inclusionAI/UI-Venus-1.5-2B --full-checkpoint
```

- Model acquisition is restricted to `E:\模型测试`; its entire contents must stay
  within 30 GiB, including staging and caches. Inventory is read-only.
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
- Existing D-drive incumbent weights/runtime are not migration or deletion
  targets. This acquisition workflow does not access unique holdout.
