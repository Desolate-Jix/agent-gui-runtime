# test.8 验收与限制 / Acceptance and limits

状态：candidate03 本方与同候选独立复验完成，作为 test.8 发布依据。 / Status: main-agent and independent acceptance of the same candidate03 are complete and form the test.8 release evidence.

## 交付范围 / Delivery scope

保留 `local`，新增 `agent_current` 和客户端明确指定模型的 `agent_delegate`。Agent 路线使用原图、结构化候选及公共执行器，支持单步和组合命令暂停、继续、取消与清理；不加载本地视觉/OCR权重。能力未知或不支持时拒绝所选路线，不静默回退。`read_text` 返回原图给 Agent 阅读。

Retain local vision and add current-Agent or explicitly delegated grounding through original images, structured candidates and the shared executor. Agent routes require no local vision/OCR weights and support single actions and resumable batches. Unknown/unsupported capabilities reject the selected route; image-based reading introduces no hidden local OCR or fallback.

用户明确暂不提供外部 API。本版仅预留 adapter/config/mock 协议，宿主 API 路线禁用；没有 key、付费调用或在线服务商兼容性验收。学习模式、自动重放、任意表单及无人值守可靠性不在本次范围。

The user deferred external API use. This release reserves adapter/config/mock contracts with the host route disabled; no key, paid invocation or live-provider compatibility is claimed. Learning, automatic replay and universal unattended operation are outside scope.

## 冻结与回归 / Freeze and regression

- 候选：`v0.1.0-test.8-candidate03`，718 项文件清单。 / Candidate: 718 manifest entries.
- MANIFEST SHA-256：`89e38118c52056e1334c6b695159cc498cbe2e36a990e8f064d4a42d4782692d`。
- 源码最终 `pytest -q`：2025 passed，41.58s。隔离候选：2025 passed，43.65s。两者为重叠集合，不相加。 / Source and isolated-candidate checks overlap; do not sum their counts.
- 独立包入口依赖校验通过；283 个项目模块均来自候选目录，718 项清单哈希相符。 / Functional entrypoint checks passed; all 283 project-module origins are inside the candidate and all 718 file hashes match.
- 发布包从维护源码重新生成；发布门槛要求所有非文档文件与已验候选逐字节一致。原始图片、日志、凭据、用户数据和模型权重不进入 ZIP。 / Delivery is freshly built from maintained source, requiring byte-identical non-document files. Raw evidence, credentials, user data and weights are excluded.

## 本方真实单项与连续使用 / Main-agent live acceptance

全部使用新数据根目录、新窗口和本轮截图，通过公开 MCP 与受控动作入口执行；未提交表单。每条路线包含同会话状态累积、异常中断、恢复和最终清理。Agent 路线的耗时包括人工/模型看图与调度等待，不能解释成纯模型推理延迟。

All routes used fresh roots/windows/captures through public MCP and gated input, without form submission. Each covered accumulated state, interruption, recovery and cleanup. Agent wall times include visual reasoning and scheduling waits, not just model inference.

| 路线 / Route | 已核对结果 / Verified result |
|---|---|
| local | 不存在标签拒绝且零输入；真实第二字段 7.086s；两文本+PDF 33.947s；错误选项在字段1中断，未执行后续字段；已打开弹窗恢复完整三字段 27.017s；关闭本轮窗口及宿主清理通过。 / Missing-label rejection with no input, named-field and mixed positive runs, option interruption, open-popup recovery and cleanup passed. |
| agent_current | 单字段 24.685s；针对不存在标签故意注入错误真实控件候选，公共点击前校验拒绝且零输入；首次混合流程发生调用方坐标换算错误，框架在选项点击前拒绝；新截图恢复完整三字段 69.773s；清理通过。 / Single-field success, injected wrong-field rejection, correctly rejected caller coordinate error, complete fresh-image mixed recovery and cleanup. |
| agent_delegate | 实际 Luna 逐张读取新截图返回候选；单字段 38.139s，三字段 168.711s；打开菜单后取消保留已执行状态，再显式发起恢复 38.608s；字段值、最终选项、窗口关闭和清理均核对。 / Actual Luna grounded fresh images; single/mixed runs, cancellation after opening a popup, explicit recovery and cleanup passed. |

主控原始证据：`20260927-test8-recovery-01/local-f1`、`current-f1`、`delegate-f1`，分别保留结构化摘要、每次请求/回执、原图及最终宿主状态。 / Each evidence directory retains requests, receipts, original images, an audited summary and final host status.

## 独立验收 / Independent acceptance

AionUi 在相同 candidate03、新根目录完成 local 缺失标签拒绝（零输入且图片与基线一致）、单字段 6.839s、混合三字段 33.663s、错误选项中断及恢复 26.699s；窗口和宿主清理通过。独立多模态 Agent 在另一新根目录完成当前 Agent 单字段、连续混合输入、弹窗取消与恢复，逐张查看原始图片并核对回执，最终清理通过。主控另外核对原始回执、图片和最终状态。AionUi 的文字/UIA 回读不冒充多模态视觉验证。

AionUi passed missing-label rejection with zero input and an unchanged image, named-field and mixed positive runs, invalid-option interruption, recovery and cleanup on the same candidate. A separate multimodal agent passed current-Agent single and continuous mixed input, popup cancellation/recovery and cleanup in a fresh root, inspecting original images and receipts. The main agent additionally reviewed raw evidence. AionUi textual/UIA checks are not presented as multimodal visual inspection.

原始独立证据目录：`20260927-test8-aionui-03`、`20260927-test8-independent-vision-04`。此前 visual-03 把下拉框确切标签 `文件类型：` 改成半角冒号 `文件类型:`，收到 `form_control_not_found`；保留该调用方失败并清理后，在同一冻结候选上修正请求复测，没有放宽控件匹配。 / Independent evidence roots are listed above. The earlier visual-03 caller changed the dropdown label’s fullwidth colon to ASCII and received an exact-label rejection. That failed attempt remains recorded separately from the corrected same-candidate rerun; matching rules were not relaxed. visual-04 另有误用旧 grounding ID 的 `result_conflict`，以及给 dropdown 添加不支持的 `field_goal` 导致的请求校验拒绝，均为调用方错误并保留原件；修正请求、采用新 pending 与匹配原图后完成恢复，未重放已完成输入。 / Visual-04 also retained caller errors: a stale-grounding-ID conflict and schema rejection of an unsupported dropdown field_goal. Corrected requests with matching current images completed recovery without replaying prior input.

## 保留的首次失败 / Retained initial failures

1. candidate01 的表单精简回执丢失底层步骤错误，已修复并通过 RED→GREEN 与原始回执重放。该阶段的裸自然语言目标冲突不通过放宽字段匹配来处理。参见 [诊断记录](TEST8_FOCUS_DIAGNOSTICS.md)。 / Compact receipts dropped step errors; projection was repaired without weakening field matching.
2. candidate02 独立验收发现 F1：不存在的明确标签可落到错误字段并因值回读而报告匹配。候选被否决；修复公共点击前标签身份，包括名称与有效别名的混合重名歧义。参见 [根因与回归](TEST8_NAMED_FIELD_IDENTITY.md)。 / Candidate02 was rejected for wrong-field input under a missing explicit label; candidate03 adds pre-click identity verification.
3. 修复初稿导致5个日期字段测试失败，限定仅文本字段传递标签后复测通过；新增歧义回归先 RED 后 GREEN。 / Five date-field regressions in the initial repair were fixed; mixed-name/alias ambiguity has a retained RED/GREEN regression.
4. 历史外部驱动非原子 JSON 写入、重启旧 inbox、能力声明位置错误和截图过期均单独保留。当前候选的主控选项坐标错误记录为调用方失败，未改记首次成功。 / Driver races, stale inbox/captures and client declaration/coordinate errors remain separate from product failures and successful reruns.

## 安全与限制 / Safety and limits

这是操作员监督的执行模式预览版。部分历史风险策略可由操作员模式调整，不能把本次通过说成自动策略全量通过。字段身份、原图新鲜度、窗口归属、候选边界及公共执行检查仍须满足。取消不是撤销；已完成输入不会自动重放或回滚。包依赖闭合、真实输入成功和原图效果判断分别记录。

This is a supervised execution preview, not a claim that every automatic policy passed. Identity, freshness, ownership and dispatch constraints remain mandatory. Cancellation is not rollback; completed input is neither replayed nor automatically undone. Dependency closure, input execution and visual task-effect review are reported separately.
