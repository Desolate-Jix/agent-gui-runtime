# Recording overlay allowlist / 录屏覆盖窗白名单

Status / 状态：2026-10-12，未发布源码；补修后237项离线通过，覆盖窗存在时完整流程成功复测一轮，首败及人工中断保留。 / Unreleased source;237 offline checks passed after repair, followed by one successful complete overlay-present rerun. First failure and user interruption remain recorded.

## Failure and invariant / 故障与公共约束

- Failure / 故障：two-rounds-06 的浏览器仍可见，但截图在模型调用前以 `capture_window_occluded` 停止，Decision 使用量为0。 / The browser was visible, but rectangular occlusion stopped capture before any Decision call.
- Root invariant / 根因约束：透明录屏宿主的全屏 HWND 矩形不等于全屏不透明像素；截图可见性不得将经过明确豁免的宿主矩形当成真实遮挡。 / An explicitly exempt recording host's rectangle must not be mistaken for opaque pixels.
- Fix location / 修复层：公共 `app/core/window_manager.py` 的截图矩形核验；现有 `ScreenshotService` 自然保留未遮罩的真实合成像素，不引入新的截图器或模型请求。 / The common capture-visibility path; the existing ScreenshotService preserves the actual composed pixels.
- Why not app-only / 通用性：此规则与 Google、浏览器或网页内容无关，适用于使用公共截图入口的目标应用。 / The rule is independent of any target website or application.

## Match and scope / 匹配与边界

The built-in allowlist requires all of / 内置白名单须同时满足：

1. Executable basename `NVIDIA Overlay.exe`, case-insensitive, no prefix/substring matching. / 进程名严格匹配，忽略大小写，不允许 NVIDIA 前缀放行全部进程。
2. Window class exactly `CEF-OSC-WIDGET`. / 窗口类精确匹配。
3. `WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST` present. / 必须具备已观察到的分层、鼠标穿透和置顶属性。
4. Valid process ID, unchanged across the identity read. / PID 有效且读取身份前后保持一致。

Capture checks and region checks with an outward-rounded1×1 footprint use the allowlist through `allow_partial=True`. Multi-pixel native region validation and `WindowFromPoint` hit checks do not use it. Unknown identity/style remains subject to ordinary occlusion handling. The match is recorded as `capture_visibility.capture_overlay_exemptions`; it is not proof that the target is visually unobstructed. Real HUD/panel pixels remain available to the existing model review. / 截图及向外取整后1×1点击区域共享豁免；多像素原生区域与真实点位检查不使用白名单。查询失败按普通遮挡处理。豁免记录不代表模型已确认目标无遮挡，实际 HUD/面板像素仍进入既有审核。

Safety impact / 动作影响：允许模型观察此前误拒的合成截图，不自动授权点击、键入或最终提交；若实际点位命中覆盖窗，仍拒绝动作。Decision 提示词、阈值和请求数未改变。 / The change admits observation, not input; a point hitting the overlay is still rejected. Decision prompts, thresholds and request count are unchanged.

## Evidence / 依据

- `D:/AgentReviewAcceptance/native-focus-geometry-20261012-two-rounds-06/overlay-diagnostic.json`: HWND66436, PID14740, class `CEF-OSC-WIDGET`, exstyle `0x800a8`, alpha255, cloaked=false. 此原件没有记录exe名称或路径。 / This record did not retain executable name or path.
- `.superpowers/sdd/2026-10-09-adaptive-live/independent-installed-01/session-01/windows.json`: another historical instance records `NVIDIA Overlay.exe`, title `NVIDIA GeForce Overlay`. 两份记录来自不同实例，不能拼接成同一实例的完整身份取证。 / This is a different instance, not a complete identity record of the October12 failure.
- Current worktree CodeGraph was not initialized; exact source inspection was used. / 当前工作树无CodeGraph索引，本批使用精确源码读取。

## Verification / 验证

Main command / Main 实际命令：

```powershell
& D:/agent-gui-runtime/.venv/Scripts/python.exe -m pytest tests/test_capture_overlay_allowlist.py tests/test_capture_window_ownership.py tests/test_capture_observation_geometry.py tests/test_native_menu_ownership.py tests/test_native_menu_capture_surface.py tests/test_point_visibility_no_dispatch.py tests/test_target_freshness.py -q --junitxml=.superpowers/sdd/2026-10-12-overlay-allowlist/final.xml
```

Result / 结果：**189 passed in 5.19s**, zero skipped/failed. The new tests exercise the real window manager and ScreenshotService with isolated Win32/MSS boundaries: known overlay allowed, unrelated names/classes/styles refused, query failure refused, other windows still masked, real HUD pixels preserved, native region and actual-point checks still reject. / 真实公共管理器及截图服务配合隔离的Win32/MSS边界，覆盖白名单匹配及反例、真实像素保留、其他窗口遮挡和点位/原生区域拒绝。

Development failures retained / 保留开发失败：
- `red.xml`: 5 failed, 11 passed against the original code, reproducing the missing exemption.
- `initial-green.xml`: patch anchor mismatch prevented source write; original failure remained (5 failed,182 passed).
- `green.xml`: an incomplete source insertion left the helper missing (29 failed,158 passed). The helper was saved and read back, then the same seven modules passed in `green-fixed.xml`.
- 本批未运行真实桌面、真实API、完整仓库套件、安装或打包；未清理浏览器资料、缓存或修改录屏设置。 / No live GUI/API, full repository suite, install/build, browser-data cleanup or recording-setting changes.

Final regression added missing/changed PID cases and passed all189 checks in `final.xml`. Read-only Sol review found no blocking defect in this slice; this was source review, not independent live acceptance. / 最终补充PID缺失/变化反例，189项全部通过；Sol只读源码审查未发现阻断缺陷，不算独立实机验收。

## Live acceptance and dispatch repair / 实机验收与派发补修

User explicitly requested the complete browser flow while recording and preservation of the same isolated profile. / 用户授权录屏时执行完整浏览器流程，沿用独立资料目录，保留缓存。

1. First run: `D:/AgentReviewAcceptance/native-focus-geometry-20261012-overlay-allowlist-09`. Capture allowed the actual NVIDIA host (HWND66436/PID14740, exact executable/class/style now jointly confirmed). Luna located the address bar; candidate Decision passed; actual hit was owned by Edge. The shared region check nevertheless rejected the same overlay rectangle for `reviewed_click_point`1×1. Business input was explicitly not dispatched. / 首轮证实截图豁免，但动作前单像素区域漏接，零业务输入，保留失败。
2. Root invariant and fix: point-sized region validation must agree with capture about the same exempt recorder; a common method had kept all region calls strict. `WindowManager.validate_bound_region_visibility` now derives outward-rounded width/height and enables the existing exemption only when both are1. Any ordinary window covering that single pixel still yields visible_fraction0 and rejects; multi-pixel native regions and actual point ownership remain unchanged. This fixes the common runtime rather than Google-specific handling. / 修复公共单像素一致性，保留普通遮挡、真实点位及完整原生区域约束。
3. Regression: `dispatch-red.xml` reproduces2 failures/20passes, including real InputController logic with mocked Win32/input boundaries. The repair passed237 tests across9 modules (`dispatch-final.xml`,4.15s). Those modules are the seven listed above plus `tests/test_decision_click_visibility.py` and `tests/test_nonmodal_popup_parent_click.py`. / 回归包含真实输入层逻辑，鼠标穿透时确实派发一次，覆盖窗截获点位时零按下。
4. First rerun: `...-09-rerun-1`. The user confirmed manually closing the test window and authorized continuation. The original `capture_window_occluded` failure and unknown action-status receipt remain unchanged; this run is not counted as success. / 用户关闭窗口造成中断，原失败及unknown记录不改写。
5. Final rerun: `D:/AgentReviewAcceptance/native-focus-geometry-20261012-overlay-allowlist-09-rerun-2`, session `session-c51955e0be064b06990e8e8741f00161`. The runtime reports planned3/settled3/successful3, terminal completed; no Main intervention. Main inspected the project after-image: Java | Oracle at `https://www.java.com/zh-CN/`; the Edge translation popup did not block completion. All three action after-images include the same NVIDIA exemption. The new `The recorded click is inside the intended visible text input.` condition appears in actual input receipts. / 最终3/3自动完成，项目截图确认Java官网，同一覆盖窗全程豁免，新输入条件已实际使用。
6. Cleanup: runtime host cleanup_verified=true; the owned test window was closed normally with force_termination=false. The original profile `D:/AgentReviewAcceptance/current-step-decision-20261012-1791764425288/edge-profile` remains present. No cache/profile deletion/reset or threshold changes. Frozen source hashes match after execution. / 正常收尾、资料保留，阈值及源码冻结核对无变化。

The success is a repaired rerun, not first-attempt or continuous-use success. No new package/release was produced. The existing browser launcher retains its test-only flags; everyday browser data is not used. / 结果属于修复后单轮成功，不能覆盖首败或宣称连续稳定；未打包或发布。

## Remaining / 待验收

Retained-profile consecutive acceptance and explicit panel/HUD negative cases remain. One completed overlay-present rerun does not establish reliability across recorder versions or a measured latency improvement. / 仍需连续验收及明确面板/HUD遮挡反例；单轮通过不证明不同录屏版本的稳定性或性能收益。
