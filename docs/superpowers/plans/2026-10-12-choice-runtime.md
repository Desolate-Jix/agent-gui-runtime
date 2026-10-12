# Choice 直接路由 / Direct Choice routing

用户已批准：满足继续，不满足或证据不足交回原 Main；困难反例后复用同一个独立浏览器资料目录连续测试，不清理缓存。 / User-approved: continue on condition_met, return condition_not_met or evidence_insufficient to the existing Main session; validate hard negatives before continuous browser tests with the same retained profile.

1. 判断核心：显式 v2 `decision_format=choice`，一次请求返回三选一；保留原 choice/confidence/distribution，按选项采用，概率阈值不参与该路线。错误、拒绝和超时交 Main，不自动切回 predicate。 / Core: explicit v2 Choice mode, one request, raw label/confidence/distribution, label-based adoption, error/refusal/timeout to Main without predicate fallback.
2. 保留旧省略字段的 predicate 配置、摘要和回执语义；新默认示例显式 Choice。动作权限、窗口/图像/坐标绑定、取消、截止时间、既有危险动作规则不变。 / Preserve omitted-field legacy predicate semantics and receipt hashes; new example profiles opt into Choice. Preserve action authorization, bindings, cancellation, deadlines and existing dangerous-action rules.
3. 离线：响应严格校验、低置信度直接选择、拒绝/不足不派发、同请求只读重取、篡改认证失败、公开接管摘要。先窄回归再相关整合。 / Offline: strict response validation, low-confidence label adoption, no dispatch for negatives/unknowns, idempotent reread, tamper rejection, public handoff evidence; focused then integrated checks.
4. 真实 API：原截图困难反例、正例和证据不足；固定条件且每例首次请求保留，不问到通过。 / Live API: fixed saved-image hard negatives, positives and insufficient-evidence cases; preserve first outcomes without retry-until-pass.
5. 实机：冻结源码后，同一已保留 profile、同一宿主连续两轮 Google URL → java → 首个普通结果；失败保留并审阅原回执，必要时修复后相关回归再复测。只关闭归属可证明的测试窗口/宿主，保留全部资料。 / Desktop: frozen source, same retained profile and host, two consecutive runs; preserve failures and inspect original receipts before repair/regression/retest. Close only owned windows/host, retain all browser data.

不在本轮发布、打包、提交、清理旧版本或修改密钥。 / No release, packaging, commits, archive cleanup or credential modification in this slice.
