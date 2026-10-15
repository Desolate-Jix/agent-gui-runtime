# 直接身份分类 / Direct target identity classification

**历史实验，已停止默认使用 / Historical experiment, no longer the default.** 下文保留此前自动类别方案的记录；当前源码改为[图形匹配／输入框包含关系](TARGET_CHECK.md)，不再默认生成身份干扰项。仅旧显式身份请求保留诊断兼容。 / The current default uses one target check, retaining explicit legacy identity requests only for diagnostics.

当前源码的 `--luna-api` 示例开启 `identity_options:true`：定位 Luna 在同一次响应返回坐标和通常两个简短的易混淆身份备选，v3 click/input_sequence 不必再由主 Agent 手写选项。运行时将冻结的原 `action.goal/field_goal` 原文加入选项，按中立描述稳定排序、编号；期望ID从原目标精确派生，不能由模型返回的候选标签或选择决定。 / The source Luna profile enables identity_options. One grounding response supplies coordinates and usually two short alternative identities. New v3 actions need no manually prepared choices; the runtime adds the exact frozen original action goal, orders the descriptions neutrally and derives the expected ID locally.

定位响应的 `identity_options` 是1～7个具体备选描述，不含期望ID或识别答案；它们是候选类别，不是已观察事实。启用后found必须返回该字段，缺失或格式错误按协议失败处理，不暗中切回旧判断。原图坐标映射、请求/采集ID、单次调用与不重试约束不变。其他profile默认不开启，旧定位输出与配置省略新字段时保持原序列化。 / Alternatives are possible identities, not observations. Enabled found responses must include valid options; omissions are protocol failures. Other profiles remain opt-in, and omitted legacy fields preserve old serialization.

目标审核只从当前内部定位状态派生选项，与原任务、截图、候选及认证回执绑定。输入后的回锚复用已认证的原定位声明，不再追加一次定位；值核验仅携带本地身份来源绑定，不把身份识别当作文字正确的证据。 / Target checks derive choices from current internal grounding state. Enter reanchoring reuses authenticated original choices without another grounding call; value checks retain a local provenance binding and still verify the entered text independently.

显式 `action.target_identity` 仍作为高级覆盖优先使用，格式如下。调用方列出具体、互斥的身份描述，不使用“正确目标/错误目标”作为选项。 / Explicit declarations remain an advanced override with the following format; use concrete mutually exclusive identities, not correctness labels.

```json
{
  "schema": "target_identity.v1",
  "choices": [
    {"value": "a", "description": "Browser address bar"},
    {"value": "b", "description": "Webpage search input"},
    {"value": "c", "description": "Browser tab title"}
  ],
  "expected": "a"
}
```

`choices` 有2～8项，ID唯一且不能占用 `other/unknown`。运行时自动追加未列出身份与无法识别两项。期望ID、完整任务、未来输入、定位模型的目标标签都不上传到本次身份分类请求。Decision只看裁剪标图、标记中心坐标及中立选项。明显禁用或遮挡的目标选择unknown，不把遮挡后面的控件当作可见证据。 / The runtime adds other/unknown. Expected ID, task intent, future input and grounding labels stay local. The model sees the annotated crop, marker coordinates and neutral identity choices; disabled or obscured targets are unknown.

本地将观察身份与冻结的expected比较：一致继续；其他身份或unknown由普通Luna对完全相同的问题与图像复核一次。第二层不接收首层答案；一致继续，否则返回原Main并保留两层记录。传输、协议或认证错误不伪装成模型拒绝，不用复核掩盖。 / Compare the observed identity locally. Nonmatching/unknown choices invoke one ordinary Luna review with identical evidence and question, without the first answer. A match continues; otherwise return to Main. Transport/protocol/authentication errors are not model refusals.

`identity_result` 保存原始身份分类、选项表、期望ID；`choice_result` 是本地派生的旧条件协议投影。普通复核记录位于 `ordinary_review.identity_result`。概率汇总仅用于兼容输出，不用阈值替换Choice；confidence仍是原身份分类的供应商置信度。两层共用原预算和截止时间，结果持久化、篡改校验与重复请求不重派保持有效。 / Raw identity and derived condition results are distinct. Choice controls routing; scores do not add a threshold gate. Existing budget, deadline, persistence and authentication remain.

适用范围是候选定位、输入候选、Enter回锚和实际点击位置核验；文字值、页面结果、变化/新鲜度和时间证据保留各自条件。身份识别不授予输入权限，窗口/坐标绑定、原动作类别限制和终提交门禁仍有效。 / Identity applies to target checks, not text-value, page-result or temporal assertions, and grants no action authority.

兼容性：只有v3支持此声明或自动选项接线。使用旧provider、缺少该能力的定位结果或旧版本计划时保留原路线；当前发布的安装包、旧冻结配置和学习模式未更新。首层误放仍会跳过复核，既有缺陷保留。 / Automatic identity wiring is v3-only; legacy providers and plan versions retain their existing route. Installed releases and learning are unchanged. First-stage false accepts still bypass review.

离线与实机证据分别记录，不用模拟响应证明模型准确率；两张符号图的10/10也不外推到通用GUI。 / Offline routing and real model accuracy evidence are reported separately.

2026-10-14 当前源码已完成同窗口两轮真实文档搜索，以及真实截图的双层错目标拒绝；179项相关离线通过，扩展回归8项失败保留。安装与独立实机验收未执行。 / The current source completed two consecutive real documentation flows and a two-stage negative replay. Focused179 passed; eight broader failures remain. No installed or independent live acceptance. See [完整记录 / Full record](../verification/TARGET_IDENTITY_LIVE_20261014.md).
