# v5 model lifecycle fixes / v5 模型生命周期修复

2026-09-22 — **Source only; existing test.5 ZIP unchanged. / 仅源码，现有 test.5 下载包未更新。**

## Failure and invariant / 故障与通用契约

- Friend reports: releasing models failed in 912.996 ms; GPU memory dropped, but cleanup was not verified. The original observer allowed up to nine observations and required three consecutive zero observations, not a fixed 300 ms timeout. The supplied logs do not identify the failing predicate. / 朋友的释放操作失败，但原日志无法区分进程身份、Job 成员或 PID 文件条件；显存下降不能证明全部清理完成。不是固定 300 ms 截止，PID 文件权限问题也尚未证实。
- Confirmed host defect: a shutdown exception exited the command loop while retaining a non-daemon runtime owner, leaving no path to retry cleanup. / 已确认宿主缺陷：关闭失败后退出命令循环，却保留非守护运行时线程，无法再次清理。
- Required invariant: report actual cleanup evidence, retain ownership until verified, and permit cleanup-only recovery without replaying input. / 通用契约：记录实际清理证据，验证前保留所有权，允许只重试清理而不重放输入。

## Changes / 修改

- `windows_process_scope.py`: optional deadline and PID-file diagnostics; default legacy response shape and three-zero rule remain unchanged. / 可选截止时间与 PID 文件诊断，保留原默认返回结构和连续三次零观测要求。
- `model_service.py`: model cleanup uses a 10-second observation budget, exits early when verified, and atomically saves `cleanup-evidence.json`. Structured diagnostics preserve samples, identities, PID-file outcome, error type and OS error numbers; startup-plus-cleanup failures retain both diagnostic sets. The budget does not hard-interrupt synchronous OS calls. / 模型清理最多使用 10 秒轮询预算，通过即退出；同步系统调用不受硬中断。持久化清理证据，启动与清理同时失败也不丢诊断。
- Coordinator propagates typed diagnostics. Failed host shutdown reports `cleanup_pending`, retains the owner, and accepts explicit `instant_stop` cleanup retries. Report/signal I/O errors do not abandon that owner. It can remain alive while a blocker is unresolved. / 协调器透传诊断；宿主清理失败保留 owner 和待清理状态，显式 stop 只重试关闭；未解除阻塞时可能持续存活。
- `instant_start(new_session=true)` rejects unresolved sessions with `start_rejected` / `previous_session_not_resolved` and actionable guidance instead of a generic tool exception. Existing records are not deleted. / 旧会话未解决时返回结构化拒绝，不删除记录。
- Download instructions and setup script use repeated `--include` flags, compatible with the tested Hugging Face CLI 1.8.0 parser. / 下载文档与配置脚本修正为重复 `--include` 参数。

These are shared runtime fixes, not app-specific adapters. No click-policy relaxation, ownership bypass, forced pointer deletion or input replay was added. / 均为通用运行时修复，不增加应用专用旁路，不放松点击策略、不跳过所有权、不删除指针、不重放动作。

## Verification / 验证

- `python -m pytest tests -q --disable-warnings`: **923 passed in 27.70 s**. Regression covers unresolved-start wrappers, delayed exits, live-process timeout, PID-file permission errors, retained owner, explicit cleanup retries, report/signal I/O failures, and nested startup/cleanup diagnostics. / 923 项通过，覆盖上述故障分支；关键新用例修复前失败、修复后通过。
- PowerShell setup syntax passed; Hugging Face 1.8.0 CLI argument parsing checked offline, without downloading model weights. / 配置脚本语法与实际 CLI 参数解析通过，未下载权重。
- Real source MCP, one continuous connection, existing VISTA weights read-only, **no desktop input**: two prepare/release cycles, then prepare/stop, then new session/stop all passed. / 同一连接真实模型循环及停止重开通过，零键鼠输入。

| Round / 轮次 | GPU MiB before → loaded → released / 显存 | release command ms / 释放耗时 |
|---|---|---|
| 1 | 1469 → 10328 → 1469 | 323.021 |
| 2 | 1469 → 10341 → 1482 | 317.396 |

All three model cleanup records were `verified`, with four samples, three consecutive zero observations and PID file removed. Both final session stops reported verified cleanup and no live host. GPU readings are supporting observations, not the cleanup criterion. / 三次清理记录均验证通过，四次采样含连续三次零观测，PID 文件删除；两次最终停止均无活宿主。显存只作旁证。

Evidence / 证据: `20260922-v5-model-cleanup-01\` (`summary.json`, command receipts, cleanup reports, driver and per-model cleanup evidence).

## Limits / 未验证边界

Friend's exact failing cleanup predicate remains unknown. Local normal lifecycle passed on RTX 4070 SUPER; the friend's elevated-permission failure was not reproduced. Failed-shutdown recovery is covered by injected regression tests, not a reproduced friend-machine incident. Already stranded old-version sessions cannot be declared repaired by this code or by deleting their pointer. / 朋友机器具体失败条件仍未知；本机正常链路通过不等于朋友的管理员环境故障已复现。异常恢复目前由注入回归覆盖，不能把旧版本已卡死会话直接宣称修好。

No package, commit, push, or independent AionUi acceptance in this slice. A requested delivery still requires isolated bundle checks and independent acceptance after Codex's relevant checks. / 本轮未打包、提交、推送或交由 AionUi 独立验收；交付仍需包内验证与独立验收。
