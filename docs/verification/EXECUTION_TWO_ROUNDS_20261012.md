# 同资料目录两轮实测 / Two retained-profile live rounds

2026-10-12，源码未发布。 / Source-only live verification.

## 结果 / Result

**连续验收未通过：第一轮3/3自动完成，第二轮在重新输入Google网址前转Main。** 两轮使用同一浏览器窗口、同一宿主session和原独立profile。阈值及条件未改；单宿主请求上限仅由20增至24以容纳授权的两轮，实际Decision累计13次。 / Continuous acceptance failed: round1 completed3/3 autonomously; round2 requested Main before typing the Google URL. Both used the same window, host session and retained profile. Thresholds/conditions were unchanged; only the request cap increased from20 to24 for the two authorized rounds, with13 Decision calls used.

| 轮次 / Round | 结果 / Result |
| --- | --- |
| 1 | 输入Google网址 → 搜索java → 打开首个普通结果Java官网；三个结果均为已认证Decision成功，无Main接管。 / All three steps completed with authenticated Decision success and no Main takeover. |
| 2 | 从第一轮Java页面继续；点击地址栏后，输入可用性Choice返回condition_not_met，内容Choice返回empty；未键入、未Enter，原输入明确failed并交Main。 / From the same Java page, input readiness rejected after the address-bar click. No typing/Enter occurred; the known click prefix settled failed and handed back to Main. |

运行目录 / Run: D:/AgentReviewAcceptance/native-focus-geometry-20261012-two-rounds-07
会话 / Session: runtime/session-37aa23a7b3d2425fad4919cd8ad76fcc
保留资料 / Retained profile: D:/AgentReviewAcceptance/current-step-decision-20261012-1791764425288/edge-profile

## 第二轮证据 / Round2 evidence

- 原图地址栏清楚显示 https://www.java.com/zh-CN/，与辅助内容判断empty不符。 / Visible URL contradicts the auxiliary empty classification.
- 真实点击点为图内(570,60)、屏幕(633,74)，位于地址栏bbox(77,43,986,33)内；原回执、图像与标注摘要一致。 / Click coordinates, target geometry and authenticated evidence agree.
- 主Choice为condition_not_met，confidence0.55；概率仅诊断，未用于旧阈值重判。API未给主拒绝的自然语言理由，不能将辅助empty误判直接当成主拒绝的已证实原因。 / The primary label rejects; diagnostics do not determine the routing. Its precise cause is not exposed by the API.
- 主问题仍只问标记处是否为目标输入且当前可输入，不要求caret或焦点样式；只上传一张点击标注整图。 / The question checks marked input usability, not caret/focus styling; one annotated frame is uploaded.
- round-2-decision-export/ 保存从原认证请求经当前正式provider、MockTransport离线重建的问题与图像，未再次调用真实API，不是另一次模型结果或网络抓包。原请求与策略摘要已验证。 / The export reconstructs the authenticated production request offline; it is neither a new model call nor a network capture.

## 启动前首败与修复 / Startup failures and repair

此前two-rounds-06首次被NVIDIA覆盖层拦截，零业务输入、零Decision；项目诊断截图显示浏览器可见，但该覆盖窗的原生属性不能证明整窗不绘制。用户选择手动关闭覆盖层后继续；原测试窗口随后已不在，原身份续接失败。相关原件保留，未按进程名放行、未改NVIDIA设置。 / The first attempt stopped on an overlay before input/Decision. The user handled it; the previous browser window was subsequently absent. Original failures remain; no process-name bypass or settings change was introduced.

新窗口仍复用原profile。其首次完整可见截图成功，却暴露了另一项运行时合同缺陷： / The new window reused the same profile and exposed a separate runtime defect:

1. 故障：截图成功但启动不提交计划。 / Failure: a successful capture did not admit the plan.
2. 根合同：每张已验证截图都须透传其可见性证明，不能仅局部遮罩时返回。 / Invariant: every validated capture must retain visibility evidence.
3. 修复：app/core/screenshot.py统一返回capture_visibility与masked布尔；启动仍核对外层成功、身份、原图摘要。 / Fix: the common screenshot producer always returns visibility and masking facts.
4. 非站点特例：适用于所有普通窗口的完整/局部可见截图。 / Generality: applies to all supported windows.
5. 回归：真实ScreenshotService输出接入selection_ready，初始1失败4通过；修后相关109通过、1跳过（环境无符号链接创建权限）。 / Regression: actual producer-to-startup coverage;109 pass and one permission-related symlink skip.
6. 安全影响：仅补回原检查结果，未绕过遮挡、取消、身份或动作门禁。 / Safety: evidence is propagated without weakening checks.

红/绿XML：.superpowers/sdd/2026-10-12-input-readiness/capture-visibility-{red,green}.xml。two-rounds-07的startup-missing-proof-*保留修复前结果。此前786项离线记录早于本次字段修复，不转计为此修改的重跑。 / Initial failures remain; the earlier786-check run predates this small repair.

## 收尾与后续 / Cleanup and remaining work

host-cleanup.json确认宿主正常关闭；isolated-browser-cleanup.json确认仅本轮窗口关闭、profile_preserved=true、force_termination=false。未删除或重置缓存，没有对第二轮同图换ID重试、没有重放未知输入。独立只读审阅复核22个历史证据引用的摘要及两轮结果，未操作桌面，不计作独立实机验收。 / Host and owned-window cleanup completed normally with the profile preserved. No cache reset or repeated model draw occurred. Independent evidence review is not independent live acceptance.

仍需解决可输入/内容Choice的实际误判，再复测连续使用；当前不宣称两轮稳定或通用性能收益。覆盖层兼容性限制也仍存在。 / Readiness/content misclassification and overlay compatibility remain; continuous reliability and general performance gains are not established.
