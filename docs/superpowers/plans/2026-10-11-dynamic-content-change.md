# 通用动态内容三图判断 / Generic dynamic-content comparison

用户要求：三图视频核验成功后，尝试做成通用动态内容判断。YouTube 首次真实三图已由 Decision 自动采用（0.99，核验5.234秒）；暂停动作因截图不含控件未触达核验，不算通过。

User direction: generalize after a real positive three-frame playback result. The first YouTube sample passed automatically; pause/resume remains unaccepted because the pause action never dispatched.

## 范围 / Scope

- 新增 task_plan.v2 verification.kind=dynamic_content，必填 target_description 与精确 decision_condition；click 或提交式 input_sequence 后复用同一三图驱动、1秒首图等待、至少500ms间隔、8秒总预算、单次Decision。
- Add an explicit dynamic_content verification with target_description and decision_condition; reuse the current three-frame driver and all timing, authority and cancellation guards.
- temporal_visual_change.v1 采用 temporal_playback.v2 的严格三图字段，加 target_description。独立 prompt_version；比较指定内容本身，忽略外围动画、鼠标、遮挡和加载装饰，不依赖控件/OCR。
- The generic temporal schema adds a bound target description. The predicate asks only whether the named content changes; it does not prove task completion outside that declared observable condition.
- video_playback 已有语义及历史认证保持；通用使用 dynamic_content_binding.v1、analysis_policy=dynamic_content_change.v1；video_playback_binding.v2 不改义。共用账本实现，不建立第二执行器。
- Keep video and historical semantics stable. The generic binding/policy are versioned separately, using the same ledger and runner.
- 无API/always_main仍交原Main；未知、失败、拒答不重放动作。现有阈值、精确允许条件、原输入及证据绑定继续有效。
- Without API or under always_main, deliver the three images to the existing Main. Uncertainty never replays input or creates authority.

## 验证 / Verification

1. 合同拒坏字段、API三图完整上传和目标绑定、认证拒篡改、公共MCP/CLI审核交付、视频兼容离线回归。
2. 源码稳定后，新数据根：真实公开时钟页面动态正例、静态公开文档负例；保留首次结果、实际图及API耗时，清理本轮窗口和宿主。
3. 不宣称通用准确率或安装版已更新；新功能是否可靠以实际结果报告。

Offline contract/provider/authentication/delivery and compatibility checks precede fresh public-clock positive and static-document negative trials. Retain first attempts and cleanup; do not claim general accuracy or an installer update.
