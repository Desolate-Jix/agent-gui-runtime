# v0.1.0-test.5 发布范围 / Release scope

本候选是 Windows 受监督执行模式测试版，标签为 `instant-v0.1.0-test.5`。
This candidate is a supervised Windows execution-mode test release, tagged `instant-v0.1.0-test.5`.

## Included / 包含

- MCP stdio runtime with seven tools, including `instant_run` and bounded `input_sequence`.
- Fresh visible-image OCR, compact original-image receipts, 23 editing keys, window/session lifecycle and explicit cleanup verification.
- Conditional observation for a known UIA text/control marker; default waits and confirmation boundaries are unchanged.
- Bilingual setup and agent guidance, plus verification reports under `docs/verification/`.

## Evidence and limits / 证据与边界

- Current source regression: 841 passing checks. Final bounded AionUi acceptance passed; earlier aborted client attempts and receipt-only follow-up remain recorded as historical evidence.
- This does not claim cross-site accuracy, whole-page completion, unattended automation, long-term stability, universal hardware support, or support for payment, sending, deletion or final submission.
- Models, dependencies and user data are not shipped. Use [FRIEND_SETUP.md](FRIEND_SETUP.md), then run no-input smoke before explicitly authorizing supervised low-risk input.

The package builder is `scripts/build_instant_bundle.py`. The bundle is expected to contain the maintained source, `README.md`, `AGENT_GUIDE.md`, `FRIEND_SETUP.md`, `RELEASE_SCOPE.md`, `CHANGELOG.md`, `docs/verification/` and scripts; package validation must precede any publication claim.
