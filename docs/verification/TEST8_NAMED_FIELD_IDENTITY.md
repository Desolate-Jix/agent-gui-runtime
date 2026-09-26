# test.8 明确字段身份 / Explicit field identity

## Failure / 首次失败

候选 candidate02 的独立验收发现：`form_fill` 明确请求不存在的文本字段时，完整 UIA 扫描返回零匹配，后续视觉候选仍指向第一个真实输入框。操作员模式放行了视觉候选；旧点击前检查只验证可写控件身份，未验证请求标签。写入后读取同一错误字段，错误地报告 `matched`。candidate02 因此禁止发布，首次失败保留。

Independent acceptance of candidate02 found that an explicitly nonexistent text-field label could fall through a complete zero-match UIA inventory to a visual candidate on the first real input. Operator mode allowed that candidate. The former pre-click check verified a writable control but not its requested label, so readback from the wrong field incorrectly reported `matched`. Candidate02 is rejected for release; its first failure remains recorded.

## Invariant and fix / 契约与修复

明确给出的 `TextField.label` 必须在真实点击前绑定到当前窗口中唯一匹配的控件，且其 RID 和 UIA 元素必须与点击命中一致。`form_fill` 将标签经 `input_sequence` 传入公共 `LocalTextFocusTarget`，由 `probe_local_focus_target` 在派发点击前复验。缺失、重名、命中不符、扫描异常均拒绝；操作员模式不能跳过此检查。

An explicit `TextField.label` must identify one current control before a real click, with both its runtime ID and UIA element matching the hit target. `form_fill` carries the label through `input_sequence` into the shared `LocalTextFocusTarget`; `probe_local_focus_target` verifies it before click dispatch. Missing, duplicate, conflicting or unavailable identity rejects input even in operator mode.

复用有限 UIA 完整扫描及既有可见标签关联，接受直接名称、唯一 `LabeledBy` 和保守几何标签证据；保留 NFC、空白、大小写及末尾冒号归一化。自然语言 `field_goal` 未被强制解释为确切标签。标签校验与后续值回读是两个独立条件。

The fix reuses the finite complete UIA scan and existing label associations: accessible Name, unique `LabeledBy`, and conservative visible-label geometry. NFC, whitespace, case and trailing-colon normalization remain supported. Natural-language `field_goal` is not reinterpreted as an exact label. Identity verification and subsequent value readback are separate conditions.

## Scope and safety / 复用范围与安全

公共点击前作用域覆盖本地模型、当前 Agent 及指定代理识图，不依赖 Google 页面或坐标。不增加输入权限，不放宽提交、发送、确认或支付动作。失败时必须阻止点击及后续键盘输入。

The common pre-click scope covers local-model, current-Agent and delegated grounding without Google-specific selectors or coordinates. It grants no input authority and does not relax submit/send/confirm/payment rules. Failure must prevent both click and subsequent keyboard input.

## Regression / 回归

`tests/test_named_text_focus.py` 覆盖不存在、错误字段、重名、有效名称及两类标签关联、编排传递和真实探针调用。首次 RED 和修复后结果分别保存。源码与隔离 candidate03 各 2025 项通过；本方三来源连续使用及同候选独立验收已完成，真实缺失标签均在输入前拒绝。完整证据、首次失败和范围见 [本版验收](TEST8_CANDIDATE_ACCEPTANCE.md)。

`tests/test_named_text_focus.py` covers missing, wrong and duplicate fields; valid Name and both supported label associations; orchestration propagation; and the actual pre-click probe. Initial RED and corrected results are preserved separately. Source and isolated candidate03 each passed 2025 checks. Main-agent three-source continuous journeys and same-candidate independent acceptance are complete; live missing-label checks reject before input. See the release acceptance record for evidence, retained first failures and limits.
