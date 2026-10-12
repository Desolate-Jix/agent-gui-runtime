# Execution stable release plan / 执行正式版发布计划

User scope: execution 0.1.2 only, emphasize Decisions API in README; learning 0.1.0-preview.3 unchanged. / 仅执行正式版，更新首页，学习版本不变。

1. Close resources, set version and stable display names while preserving upgrade identity.
2. Rewrite README around current behavior; retain old checkpoints and failures in an archive.
3. Freeze execution dependency closure, excluding workbench UI/translations and private evidence. Run scoped source/contract checks.
4. Build one isolated execution payload and installer. Verify real entrypoint dependencies and installed bytes.
5. Main runs consecutive API/browser acceptance using the retained profile, then independent acceptance on the same frozen candidate. Fix failures before publication.
6. Commit only execution/release scope, publish instant-v0.1.2 and hashes, verify public downloads, update final status. Learning assets remain unchanged.

Use only project desktop interfaces. Never delete browser data. No LinkedIn publication. / 仅用项目桌面接口，不清浏览器资料，不代发领英。

## 连续输入修正 / Continuous input correction

用户确认：默认视觉输入在定位审核通过后，将点击、Ctrl+A 和替换文字绑定为同一次运行时动作；中间不调用 Decision、不截图、不重新选窗或激活。输入后只核验规定文字；满足后才按请求执行 Enter。暂不增加点击是否被弹层吞掉、焦点外观或空框检查。 / After the existing target gate accepts, bind click, select-all and replacement into one runtime action. No intervening model call, screenshot or activation. Verify only the requested text afterward and dispatch requested Enter only on success. Do not add click-consumption, focus-style or empty-field checks.

- 复用原识别点击门禁、剪贴板恢复及键入阶段回执；内部单次绑定 HWND/PID、坐标和原请求文字。 / Reuse the recognition click gate, clipboard restoration and typing-stage receipts with a single-use internal target/text binding.
- 返回真实组合回执，分别保留点击、全选、键入状态；不得虚构独立 type 步骤，失败或未知均不自动重放。 / Keep a real compound receipt with separate dispatch facts; never synthesize an independent type step or replay an unknown action.
- 先验证源码合同、拒绝/取消/部分输入/文本不符/Enter抑制，再用同一保留资料目录执行完整连续流程；不增加弹层吞点击专项确认。 / Verify contracts and failure settlement offline, then rerun the full consecutive flow with the same preserved browser profile, without a separate click-consumption investigation.
- 新逻辑验收完成前不重打包、不发布；学习和显式原生输入保持原路线，阈值不变。 / Do not rebuild or publish before source validation. Learning/native routes and thresholds remain unchanged.
