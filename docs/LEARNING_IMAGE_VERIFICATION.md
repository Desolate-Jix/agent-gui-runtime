# 学习工作流图像核验 / Workflow image verification

新学习默认优先本地图像匹配，用户可以关闭。没有可用规则或匹配不确定时，仍由 Agent 审核。此功能当前在维护源码中，已有独立安装预览包不包含本轮修改；没有变更版本号或发布。

New learning defaults to local image matching, with a user option to disable it. Missing or inconclusive rules retain Agent review. This is a maintained-source change; existing preview installers do not contain it. No version or publication change.

## 学习、修改、复用 / Learn, edit, reuse

- 新学习编译器从审核成功的操作后原图提议局部模板。自动提议要求前后状态不同、图像尺寸一致、局部有足够纹理，而且目标模板在操作前不能匹配；草稿仍待审核。没有可用区域时保留原核验路径，不把整屏变化写成成功。
- 工作台在“Agent 判断”规则下显示“本地图像核验（可选）”。实际存在规则时默认勾选。用户可选该固定目标状态的已学结果原图，修改稳定模板区域、搜索区域和阈值；避免动态编号、时间和变化的内容。
- 取消勾选并保存会删除附加图像规则，保存新版本。普通加载、保存和重开不会自动补回；已固定的旧程序和正在运行的程序不改变。
- 运行时核对原执行回执的窗口，使用项目维护接口重新截图，在搜索区域匹配模板。只读观察使用约100 ms间隔及两秒启动预算；匹配明确即通过原 Trial/Runner 记账并继续，不等待预算耗尽。只有普通不匹配继续轮询；歧义、身份或图像合同错误立即保留原请求交 Agent。
- 不匹配、歧义、缺图、尺寸或窗口变化，以及其他成功条件未满足，均保留原 pending 请求及比较证据，交原 Agent 审核入口处理，不重新点击。

- The compiler proposes a localized template from a successful reviewed after image only when the state differs, dimensions agree, texture is sufficient and the before image cannot match it. Draft review remains required.
- The workbench shows the optional local check beneath Agent judgment. A real configured rule appears checked. Users select an image from the pinned target state's successful observations and edit template/search regions and threshold.
- Disabling removes the extra rule in a new revision. Load/save/reopen do not regenerate it; pinned versions remain immutable.
- Runtime binds fresh screenshots to the original execution window and polls read-only observations at approximately100ms intervals within a two-second capture-start budget. A conclusive match immediately continues through the existing Trial/Runner; ambiguity or contract errors retain the original ticket for Agent review.
- Inconclusive matching, missing images, changed geometry or unmet success conditions retain the original pending ticket and evidence for Agent review without replaying input.

已审核且使用图像规则的学习步骤由共同命令编译入口设置 `observation_wait_ms=0`，目标绑定、恢复和计量均重编核对该完整命令。普通执行、无图像规则和 `steps_only` 保留原等待。取消可中断轮询等待；已经启动的同步截图不能在中途取消，所以两秒不是硬性的总调用超时。 / The shared compiler emits zero additional render grace only for reviewed image steps; target binding, recovery and measurement recompile the exact command. Other execution and steps_only retain their defaults. Cancellation interrupts polling waits, but an already-started synchronous capture can finish beyond the budget.

## 范围 / Scope

第一批只支持没有输出、没有读取规则的非读取步骤，且使用 `agent_judgment` 的附加配置。字段相等、可见文本和其他已有规则保留。图像核验不能从学习原图产生当前详情或动态输出。手工配置也必须审核；模板相似度阈值不是准确率。

The first slice supports only non-read steps without outputs/read specifications, using an extension of Agent judgment. Existing field/text rules remain. Historical images never produce current dynamic values. Manual configuration also requires review; a matching threshold is not an accuracy score.

自动提议只是候选：一轮学习无法证明该区域长期稳定。换数据或界面变化时可能转给 Agent；用户可以重选区域或关闭规则。尚无本轮功能的正式速度或准确率收益数字。

Automatic proposals are candidates: one observation cannot establish long-term stability. Changed data or UI may require Agent review; users can revise or disable the rule. No formal speed/accuracy benefit has been measured for this change.

## 保存接口 / Saved contract

```json
{
  "verification": {
    "kind": "agent_judgment",
    "image_check": {
      "contract_version": "workflow_image_check.v1",
      "reference_sha256": "<SHA256 of the archived successful after PNG>",
      "reference_size": [800, 600],
      "template_bbox": [100, 80, 180, 40],
      "search_roi": [80, 60, 240, 100],
      "threshold": 0.95
    }
  }
}
```

原图按 SHA 保存于本记忆库 `desktop-review/evidence-objects`；程序保存、运行观察和最终记账核验原字节及几何。`learning_workflow` 的既有编译、保存、核验和审核入口承载该配置，不新增执行器或权限。启用只由配置存在表示，删除配置即关闭。

Reference PNGs live under the same library's content-addressed evidence directory. Save, observation and final consumption validate original bytes and geometry. Existing workflow compile/save/verify/review interfaces carry this configuration, without a new executor or authority. Configuration presence enables the check; removal disables it.

源码回归和真实截图验证的证据及未跑范围见 [本轮验证记录](verification/LEARNING_IMAGE_VERIFICATION_20261007.md)。 / Source checks, live captures and untested scopes are recorded in [the verification report](verification/LEARNING_IMAGE_VERIFICATION_20261007.md).
