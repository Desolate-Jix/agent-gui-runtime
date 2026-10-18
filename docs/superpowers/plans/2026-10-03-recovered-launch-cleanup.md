# Launch cleanup after epoch recovery / 跨宿主恢复后的启动窗口收尾

Goal / 目标：修复 P3 已核实的共同生命周期缺口：原宿主停止后，恢复的新宿主仍可显式正常关闭本次新启动、身份未变的窗口；不把 select 或外部窗口当作 launch 归属。

Design / 设计：现有成功新 launch 响应补充原生完整归属事实（HWND、PID、进程创建时间、可执行路径），既有新窗口登记处产生；已有窗口 focus 不产生。现有 close_launched_window 命令仅增加可选 request，严格接受 admission_request_id 与 launch_request_id；无 request 沿用当前协调器归属。只接受同工作区、指向当前会话且 ready 的既有 epoch admission，重核原资源和输入证明、原 launch 命令及原响应 SHA、完整归属事实与前后一致；旧无事实响应不追溯授予权限。之后仍沿用现有 normal close，fresh native identity 必须逐项一致。关闭前记录当前会话独占 claim，未知派发不重发；旧来源字节不改，未取得完整证明仍拒绝。

Limits / 限界：不改变 epoch/workflow 接管门禁、不新增执行后端、不扩展跨实例重绑定、不扩展到多层恢复、不自动关闭用户窗口，不改 v0.1.1/UI v14、不打包发布。原 T13 旧失败、旧窗口未清理及未通过恢复状态保留。 / Preserve admission/action gates and original failures; no general rebinding, multi-layer extension, automatic user-window close or release change.

- [x] 原失败源契约 RED 与两轮修复记录保留；初始签名探针不单独算行为验收，Main 审查后补实际负例。 / Preserve both source RED rounds; replace signature-only acceptance with behavioral coverage.
- [x] 最小实现：成功 launch 归属事实、严格 ready admission/source 验证、现有 close 显式入口与独占关闭 claim。
- [x] 负例：旧无证明响应、focus/select、未 ready/外工作区、来源篡改、PID/HWND/创建时间/路径变化、重复 claim/未知 close 均不得发送关闭。
- [x] Main 审查实际 diff 并跑新窄测、launch/close/epoch/input 相关回归。
- [x] Main 用全新数据及真实 MCP 在新实例完成 launch、正常 stop、同实例 epoch recovery、显式正常 close、原 PID/HWND 消失及 MCP 清理；只闭合此生命周期契约，完整学习恢复仍单独验收。
- [x] 同步受影响文档并另冻候选，旧限定独立验收不继承到新候选。

2026-10-03 最新限定结果：跨宿主的启动窗口收尾缺口已修复。Main 344 项相关源码/契约回归通过；全新 T15 在同一 MCP 连接完成新启动、正常停宿主、新 epoch ready、凭原启动证据显式正常关闭同一窗口，原 PID/HWND 消失且 driver exit 0。冻结范围为 887 文件，原 10 份来源快照与冻结源码均未变。只验收这条生命周期链，未验收完整学习工作流接管或弹窗；原 T13 失败及未清理窗口保留。桌面像素与真人体验未验收，收益未知后置；正式 v0.1.1、已选 UI v14 不变，未打包发布。 / Latest bounded result: Main passes 344 related source/contract checks. Fresh T15 uses one MCP connection for new launch, normal host stop, ready epoch admission, and explicit normal closure of the same window using original launch proof. The original PID/HWND disappear and the driver exits zero. The inherited 887-file freeze and ten original source snapshots remain unchanged. This accepts lifecycle cleanup only, not full learning-workflow takeover or live modal recovery. Retain T13's failures and unclosed old window. Native pixels/human usability remain open and benefits unknown/deferred; stable v0.1.1 and accepted UI v14 are unchanged without packaging/publication.
