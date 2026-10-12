# 三张截图判断画面变化 / Three-frame picture-change verification

用户于2026-10-11明确：不依赖播放器控件；连续三张截图一次交Decision，有目标视频画面变化就按播放处理。另已选动作后成功门槛0.80、需要Main门槛0.70。 / The user selected picture change as the playback criterion and approved after-action success0.80 / Main-review0.70.

- 点击完成后在既有核验预算内等至少1秒，使用项目维护接口采三张新图，间隔至少500ms，跨度至少1秒；8秒总预算不重置。原after独立保留。 / Capture exactly three fresh frames after a brief settle, within the existing budget.
- 新路径不调用Luna定位、控件/OCR观察或本地播放进度分析；没有本地playing自动结论。 / No additional grounding, controls, OCR or local progress proof.
- temporal_playback.v2只绑定original_after、三帧及真实elapsed_ms、按序全部selected_capture_ids、剩余timeout_seconds；实际上传全部三张，带start/middle/end角色。 / V2 authenticates and uploads all three ordered samples.
- 问题只核对目标视频内容画面有无变化；不要求暂停图标或时间读数，不把无关页面/控制栏变化计入。0.80通过仍需没有可见错误且needs_agent_review<0.70；未知/拒绝/预算耗尽交Main，不重复判断或输入。 / Decision uses content change without control/progress prerequisites; the existing independent error and routing checks remain.
- 无Decision或always_main仍采三张供Main，不隐式启用API；旧v1证据与冻结策略不静默改写。普通单图/双图判断协议不扩张。 / No API auto-enable or reinterpretation of historical receipts.
- 先离线验证三张实际上传、零locator/OCR、原票据/窗口/预算/取消/防重派、v4图片交付和旧证据兼容；真实准确率及速度单独报告。 / Verify the actual pipeline and evidence boundaries before claiming real accuracy or latency.

该规则是用户选定的画面变化判据，不能证明音频播放、静止镜头持续播放或未来不中断。 / The selected visual-change criterion does not establish audio, playback of a visually static scene or future continuity.

原计划 docs/superpowers/plans/2026-10-11-video-playback-verification.md 的控件/进度优先方案为历史；本次不打包、提交或发布。 / The controls/progress-first plan remains historical; no packaging or publication.
