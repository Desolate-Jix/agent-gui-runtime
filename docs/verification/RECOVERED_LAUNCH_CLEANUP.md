# Recovered launch cleanup / 跨宿主启动窗口收尾

2026-10-03 源码候选限定验收：**PASS_BOUNDED_SAME_WINDOW_LAUNCH_CLEANUP**。正式 v0.1.1、UI v14 不变，无构建、安装或发布。 / Bounded source-candidate acceptance; no stable-release/UI/version change or publication.

## Failure / 故障

T13 原宿主停止后，新的协调器没有旧 launch 的内存归属；select 只选择已有窗口，不能获得关闭权限。旧响应又未保存完整归属事实，因此原测试窗口仍打开。原 T13 能力错误与 ticket 丢失的失败保留，不补写旧响应或账本。 / After the T13 owner stops, a new coordinator lacks its in-memory launch ownership. Selection grants none, and the legacy response lacks full persisted ownership facts. Retain that unclosed window and original capability/ticket failures.

## Root invariant / 根契约

本次新启动窗口的原始归属必须随成功响应保存，并且恢复后仍只允许显式正常关闭同一个原生实例。窗口句柄、PID、进程创建时间、可执行路径及来源 SHA 必须一致；关闭权限不能由当前 selection、标题相同或调用方字典推导。 / Persist new-launch ownership in the original successful response and permit only explicit normal closure of that same native incarnation after recovery. Identity and original-source hashes must match; selection, equal titles and caller dictionaries grant no authority.

## Fix location / 修复位置

- `app/desktop_review/window_preparation.py`：既有新 launch 登记处输出 `launch_ownership`，contract 为 `launched_window_ownership.v1`；focus/select 无此事实。normal close 接受当前协调器绑定的不透明证明，并在 claim 前后重验原生身份。 / Persist facts at the maintained new-launch path and revalidate identity around the close claim.
- `app/execution/launched_window_ownership.py`：严格核对当前 ready epoch admission、原资源/输入证明、原 launch 命令与响应 SHA、当前宿主及指针；原来源保持不变。关闭前以 exclusive create 保存当前会话 claim；未知派发不重发，lost wait state 拒绝。claim 读写 resolved 路径必须限于当前 session。 / Verify existing admission and immutable source proof; create an exclusive session-confined claim before dispatch and reject uncertain/lost-state replay.
- `app/instant_mcp.py`、`scripts/run_local_step_session.py`：只在已有 close 命令增加可选 `request`，精确接受两个原请求 ID；无 request 保留当前协调器的既有正常路径，busy/action/admission 门禁不变。 / Add one optional request to the maintained close command, without a new executor or weakened guards.

```json
{
  "kind": "close_launched_window",
  "handle": 22284224,
  "process_id": 93032,
  "request": {
    "admission_request_id": "t15-epoch-admit",
    "launch_request_id": "t15-launch-owned"
  }
}
```

上述是 T15 原回执的实测例，其他任务必须读取自身原 ID 和身份，不能复制这个目标。请求 ID 复用原 1–80 字符小写 ASCII 校验。 / This is the actual T15 example; other tasks must use their own original IDs and observed identity.

## Why shared / 为何在共享层

缺口属于宿主与原生窗口生命周期，与 7-Zip 目录或目标文字无关。维护 launch/close 的归属契约可供其他 Windows 应用复用；没有加入 7-Zip 专属关闭坐标或新的输入后端。 / This is a shared host/window lifecycle invariant, independent of 7-Zip text or folders, and reuses maintained launch/close without app-specific coordinates or another input backend.

## Regression and live evidence / 回归与实机证据

首次源码 RED 与修复记录保留在 T13 `launch-cleanup-fix/`；初始签名探针不能单独算行为验收，Main 审查后补实际负例，保留两轮 RED。新 ownership 测试最终 47 项，覆盖旧无事实/focus/select、非 ready/跨工作区、来源/epoch 漂移、原生身份变化、未知 claim、已观察弹窗等待、丢失 wait state、ID 和路径越界零关闭；不把 mock 的身份校验称为实机。 / Preserve both RED rounds and behavioral negative coverage; a signature probe alone is not behavioral acceptance and mocked native tests are not live proof.

Main 实际运行 13 个相关测试文件，**344 passed / 35.44s**；JUnit 为 344 tests、failure/error/skip 均 0。此为相关回归，非全套，前批 166 和 worker 批次不累加。 / Main runs thirteen related files: 344 pass, with zero JUnit failures/errors/skips; do not add earlier or worker counts.

- [Main JUnit](D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261003-learning-recovery-13-host-stop/main-launch-cleanup.xml)
- [实机前 Main 审查 / Main pre-live review](D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261003-learning-recovery-15-launch-cleanup/main-source-review.json)
- [Main 实机审计 / Main live audit](D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261003-learning-recovery-15-launch-cleanup/main-lifecycle-acceptance.json)
- [887 文件冻结 / 887-file freeze](D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261003-learning-recovery-15-launch-cleanup/source-freeze.json)

全新 T15 使用新数据目录和新 shortcut，只有一个 MCP 连接：原新 launch 得到 PID 93032、创建时间 1790978848.4383757、HWND 22284224；Root 核对新 capture，故意不声明识图能力的探针保留 failed/capability_unknown 且 worker/input 均未创建。原宿主正常 stop，既有 epoch 准入用同一 request ID/preview SHA 从 starting 续查到 ready，并非两次恢复。随后原 request 显式正常关闭同一窗口，close 返回 window_closed，独占 claim 也记录 window_closed；实际 PID/HWND 消失，恢复宿主正常 stop/disconnect，driver exit 0。 / Fresh T15 uses new data and one MCP connection. Its deliberate no-capability probe remains failed without worker/input. One admission progresses from starting to ready, followed by explicit normal closure of the same original native instance and normal client cleanup.

Main 重算原 10 份来源快照 SHA 全部未变；旧/新宿主、runner、测试应用 PID 107828/95460/91204/105092/93032 均消失。887 文件冻结哈希 `60c00640300e4a14963b4f72136cc3652a73bda1fa078427ac98c6f35b2eba5c` 实机前后相同。冻结仅为继承的明示范围，不能称整个工作树及全部文档冻结；T11 的旧独立通过不自动继承到本候选。 / All ten original source snapshots and the inherited 887-file freeze remain unchanged; recorded old/new host, runner and test-process PIDs are absent. This is the specified inherited scope, not the whole worktree, and prior independent acceptance does not transfer.

## Safety and remaining scope / 安全与剩余范围

没有放松动作/epoch/workflow 门禁，没有强杀、猜坐标、关闭外部用户窗口或自动重发未知关闭。成功 proof 仍要求当前原生身份一致；弹窗必须另行观察和处理，lost wait state 拒绝。只验收本次单层正常停止后的同实例生命周期；旧无事实 launch 不能追溯授予权限，多层恢复及跨实例重绑定不在范围。 / Gates remain intact with no forced kill, guessed coordinates, external-window authority or unknown replay. Proof requires current native identity; modal handling remains explicit, and lost wait state rejects. Only this single-layer normal-stop/same-incarnation lifecycle is accepted.

完整学习工作流的原 pending ticket 结算、接管剩余步骤、限定弹窗与完整连续流程收尾仍待；原 T13 失败/旧窗口未清理仍保留。Qt 预览由 Main 核对，但原生桌面取图工具不可用，不能算桌面像素或真人验收。模型用量、准确率和速度收益未知后置，交付/独立完整验收/发布未完成。 / Original pending-ticket settlement, remaining-step takeover, live modal handling and complete workflow cleanup remain open. Retain T13 failures and its unclosed old window. Inspected Qt renders are not native pixels/human acceptance. Benefits, full independent acceptance and delivery remain unverified.

下一实机先用全新内容，在原 awaiting_grounding 等可观察边界正常停止，再核验同窗口当前效果、显式继续剩余步骤及完整收尾；不重复已完成动作的 adopt+stop 竞速，也不补写旧输入证明。 / Next use fresh content and an observable original pending boundary; verify current effects and explicitly continue remaining steps with complete cleanup, without race-based acceptance or old proof backfill.
