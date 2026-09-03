# GoalBinding incumbent baseline — 2026-09-04

**Status: baseline measured; replacement A/B matrix incomplete; no winner.**

This is real model inference on five fixed public regression screenshots and
25 targets, not live desktop automation, a held-out generalization result, or
production readiness. The frozen pipeline is OmniParser discovery, Qwen3-VL-8B
Instruct Q4_K_M per-goal binding, then VISTA-4B ROI refinement. No GUI action was
authorized and no unique holdout was used.

## Frozen scorer results

| Measurement | Result |
|---|---:|
| Correct / wrong / abstained binding | 5 / 19 / 1 |
| Native contract accepted | 24 / 25 |
| VISTA dispatch / validated / out-of-bounds | 24 / 21 / 3 |
| End-to-end correct | 5 / 25 |
| Binder latency p50 / p95 | 1201.136 / 26293.659 ms |
| Binder raw output bytes | 1828 |

The hard gate failed: wrong_bind_nonzero, native_parse_incomplete and
correct_bind_below_ten. No promotion is justified. Latency includes cold-start
cost; reliable peak VRAM was unavailable.

All 25 raw responses were valid JSON. The rejected Compose binding selected
inactive candidate 0: the 24/25 contract result is **not JSON truncation**.
Of 21 validated VISTA outputs, five hit acceptable target regions. Derived
end-to-end counts are therefore **5 correct / 16 wrong / 4 abstained**. A valid
point inside an incorrect ROI is not a correct semantic action.

## Post-hoc diagnostic, not a new scorer

Reusing the frozen scorer's active-candidate and acceptable-ID/center-region
predicates, candidate-center availability was 4/5 targets on case-001 and 5/5
on each of case-002 through case-005: 24/25 in total. Of 19 wrong bindings,
18 had an acceptable candidate available.

This points mainly to binder selection failures in this run. It is **not an
official detector recall metric**, a general model ranking, or a guarantee that
another provider can reach this availability ceiling. Neither the scorer nor
Gold, corpus, threshold, prompt or Fusion was changed to improve the score.

## Lifecycle and unfinished work

The completed run used a server-only nested Windows Job so managed release did
not terminate its own worker. A no-model Windows subprocess test reproduced the
prior exit-197 failure and verified the repair. Earlier failed attempts were
preserved, not given fabricated receipts or retroactive scores. An abandoned
global lease was retired through existing canonical cleanup APIs.

The completed run's binder/pipeline cleanup was verified; current known model
PIDs and active Qwen leases were also zero. This does not make model quality pass.

UI-Venus-1.5-2B checkpoint acquisition completed, but its runtime/dependency
packaging remains unfinished. Native-Windows attention compatibility and the
checkpoint-only versus runnable-bundle packaging seam still require resolution.
Do not describe an acquired checkpoint or an offline adapter test as a tested
replacement. Other challenger arms have not run.

## Evidence identifiers

Run: goal-binding-ab-20260904-baseline-03, code baseline bf37c075.
Raw local traces are not shipped in the public repository.

| Artifact | SHA-256 |
|---|---|
| provider-diagnostic.json | 3e73be805eaf3fde388491b3e3163b7afe3bf0c3b822d6605758a008011916c6 |
| binder-report.json | 02f9190b67aa05c81806d9348883e0babeeee374592d909d853378bf63bdd99e |
| matrix-report.json (incumbent only) | f8e379805412921b10e1d6b67c3e83de3b622bdeba28e596b4d0b5de44970445 |
| cleanup-receipt.json | 02e11106be4be48b6d708a7105fb50dfd01adce0385d749e1498e9cb1172055c |
| aggregate Omni snapshot | 8cb1e4b4c0deaa14baca7fae72f18166fa8715af42cb8a985080d84bac61caf7 |

The matrix contains only the incumbent and has a null winner. See the
[acquisition boundary](GOAL_BINDING_MODEL_ACQUISITION.md) for the difference
between downloading assets and preparing a runnable provider.
