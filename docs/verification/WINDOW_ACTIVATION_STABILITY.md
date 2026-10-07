# Window activation stability / 窗口激活稳定性

2026-10-02（Pacific/Auckland）。用户要求收益暂后置，先核验稳定性并排查激活失败。 / Benefit work is deferred while activation and continuous execution are validated.

## Conclusion / 结论

已确认原失败链：连接当前 Shell 前台线程被拒绝，随后目标未成为前台；还不能确定 Windows 拒绝该连接和激活的更深层原因，也不能从进程名推断用户打开了菜单。源码已修正错误码归因并保留前置线程失败；没有绕过 Windows 前台限制。 / Original logs establish denied attachment to the Shell foreground thread followed by unverified target focus. The deeper OS cause is unresolved, and the process name does not establish an open menu. The source repair improves diagnosis without bypassing foreground restrictions.

## Failure / 可见失败

P4 `live-01`、`live-02` 均在原 MCP `select` 失败，尚未执行工作流输入。两份 session 同级 `.log` 均先记录 `AttachThreadInput` 向 TID 47200 返回 error 5，约 1 ms 后记录 `SetForegroundWindow` error 5；第二次选窗前后均为 HWND 265082 / PID 23960。 / Both attempts fail during original selection before business input. The sibling host logs retain the earlier attachment failure and unchanged foreground.

用户明确没有打开菜单。事后只读测量：同一 HWND/PID/TID 对应 `ShellExperienceHost`，低完整性、DWM `cloaked=2`、`menu_mode=false`，读取其 thread desktop 也返回 error 5。这不是故障瞬间采样，不能据此确定当时隐藏状态或完整性差异就是根因。 / The user reports no open menu. Later measurements of the same identity show a cloaked, low-integrity Shell window with no menu flag; they do not reconstruct the failed instant or establish causality.

## Root invariant violated / 违反的共同契约

错误诊断不能把一个 API 未保证有效的 LastError 当成目标权限证据，也不能只保留最后失败而丢弃前置失败来源。Microsoft 明确 [AttachThreadInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-attachthreadinput) 失败可读取 GetLastError；[SetForegroundWindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow) 只保证 BOOL 成败，其前台限制即使满足部分条件也可能拒绝调用。原 error 5 可能继承更早失败，但没有原始清零观测，不能断言必然如此。 / Preserve API-specific error provenance. The foreground API does not promise an extended error code; the original code may be stale, but this was not measured at the failed instant.

前台不匹配时拒绝执行的契约原本有效，保持不变。 / The existing refusal on unverified foreground remains intact.

## Fix location / 修复位置

- `app/core/window_manager.py`：记录 current/foreground/target TID、attachment 原异常与失败阶段；同一次 SetForegroundWindow 前清零 LastError。 / Preserve thread/stage evidence and clear prior thread error before the same foreground call.
- `app/core/window_preparation.py`：保留原错误与 cause；SetForegroundWindow 返回 `winerror_reliable=false`，不再据其5推断 `access_denied` 或 `privilege_mismatch_possible`。其他原 Win32 错误归因不变。 / Preserve raw facts while distinguishing unguaranteed foreground error codes.

这是诊断行为修复，不是已证明的 Windows 激活权限修复。字段消费者应同时查看原 `winerror` 和 `winerror_reliable`，不能把 false 读成已证明没有权限限制。 / This fixes error attribution, not the underlying OS restriction. A false classification means the code does not establish that cause, rather than proving permission restrictions absent.

## Why not app-only / 为什么修在共同层

选窗、截图准备和不同 Windows 应用使用相同 WindowManager；故障来源属于当前前台与目标线程关系，与 Record Desk 的业务字段无关。未修改测试应用去迁就运行时，也未新增执行器。 / The same preparation path serves other native applications; this is unrelated to fixture business fields.

## Regression and live scope / 回归与实机范围

| 验证 / Check | 结果与边界 / Result and scope |
| --- | --- |
| 原缺陷 RED | 2 failed / 2 passed；原记录保留 / Original failures retained |
| Main 窄回归 | 44 passed：诊断、原生异常属性及 JSON、前台不匹配拒绝、前置警告后真实成功、弹窗归属、owner 线程和客户区几何 / Focused contract coverage |
| v9 原源码单窗 | 原选窗加连续3次截图、正常清理通过；选窗前目标已经在前台，不证明后台切换 / Already-foreground success only |
| v10 同会话双窗口 | 原 MCP 连续7次选窗与截图，7次均实际跨窗口切换；逐次核对 HWND/PID/create_time、原PNG SHA，最终清理通过 / Seven actual transitions and verified cleanup |
| 旧 Shell 条件 | 未复现；不强制激活隐藏系统窗口，也不把普通窗口通过当作该条件已修复 / Original condition remains unverified |
| 完整业务与恢复 | 本次未跑；选窗检查不抵扣完整学习任务、宿主中断接管或独立验收 / Full workflow and recovery acceptance remain open |

v10 冻结 853 个 app/scripts/tests 源文件，实机前后无变化。此前 v9 Agent continue 关联修复的 Main 96 项和原165文件只读重放属于另一已验证范围，不能与44项相加当成新实机通过数。 / Keep candidate hashes and source versus live validation scopes distinct.

## Safety impact / 安全影响

没有新增自动重试、提权、Alt/Alt-Tab或业务键鼠输入；原身份、前台、截图和动作门控不变。前台未核验仍停止，不会因诊断变化放行提交、发送或付款。 / No new retry, elevation, synthetic key fallback or business input is introduced; failure remains closed.

## Next / 下一步

沿当前候选验证同窗口连续任务、活动弹窗、一次所属宿主中断、原终态结算、明确接管、余下步骤及完整清理；不重做已完成 P1，不扩建通用恢复。若原系统前台拒绝再次出现，消费本次保留的线程与阶段证据定位，不猜菜单、不自动重放原输入。收益采样继续后置。 / Complete bounded recovery and cleanup next; investigate any recurrence from fresh evidence without replaying input or expanding recovery architecture.

证据根 / Evidence root: `D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261002-learning-mainline-01/activation-diagnosis-01`。`source-fix/` 保存原件、RED/GREEN；`main-final.xml`、`main-source-receipt.json`、`source-freeze-v10.json`、`original-live-01/`、`fixed-live-01/` 保存 Main 检查与原 MCP 记录。历史 P4 两次失败保持在 `p4/live-01`、`p4/live-02` 及相应原 session 日志。 / Evidence is retained separately by attempt and candidate.
