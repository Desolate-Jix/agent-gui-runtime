# 直接身份分类实测 / Direct identity live verification

2026-10-14；维护分支 `codex/dev-decision-api`，源码增量未发布。 / Maintained source increment, unreleased.

## 范围与实现 / Scope and implementation

用户要求：Decision 直接识别标记处是什么控件，本地判断是否符合目标；不符或无法识别由普通 Luna 用同图同问题复核一次，复核通过继续，否则返回原 Main。 / Decision identifies the observed control; compare locally with the expected identity. One ordinary Luna review handles a mismatch/unknown; its match continues, otherwise hand off to the original Main.

`task_plan.v3` 的 click/input_sequence 支持冻结 `target_identity.v1` 的具体身份选项。期望 ID、未来输入、整体任务、定位标签不进入分类请求；两层原始分类及本地条件投影分别保存并认证。候选点击、输入候选、Enter 回锚及 recorded-click 透传声明；文字值、页面结果、新鲜度保留独立条件。旧计划未声明字段时兼容原问法。 / Concrete identity choices are frozen in the v3 action. Expected ID and planning intent stay local; raw answers and derived conditions are separately authenticated. Target checks carry the declaration; text values, page results and freshness keep their own contracts. Legacy plans retain their original behavior.

## 实际连续流程 / Actual consecutive flows

证据根 / Evidence root: `D:/AgentGUI-Projects/evidence/target-identity-live-20261014-01`。

使用维护 `scripts/execution_client.py --luna-api --decision-profile … --allow-actions`，同一 MCP 连接、同一窗口、同一保留独立 Edge profile。只使用项目截图与门禁输入；未使用 Codex 原生 Computer Use。 / One maintained client/MCP connection and owned Edge window, with the retained isolated profile. Project capture and gated input only.

| 流程 / Flow | 首次结果 / First attempt | 调用方整轮墙钟 / Caller wall time |
|---|---|---:|
| 地址栏输入 Bing 搜索网址 → 打开 Python itertools 官方文档 / Enter a search URL, open official itertools docs | completed，2/2 步、无 Main 接管 / no Main handoff | 34.472 s |
| 从上轮页面输入下一搜索网址 → 打开 Python collections 官方文档 / Continue from the previous page and open collections docs | completed，2/2 步、无 Main 接管 / no Main handoff | 25.281 s |

原回执 / Receipts: `responses/10-plan.json`、`responses/20-plan.json`；调用方计时见相应 `*-timing.json`。最终原截图由 Main 查看，URL 与标题均对应官方页面。调用方墙钟包含动作、页面响应、定位、核验及轮询；不包含人工准备和启动，不等于单次 API 时延，也没有同场景旧版 A/B。 / Main inspected the final captures and their official URLs/headings. Wall time includes execution, navigation, grounding, checks and polling; it excludes setup/launch and is not a single-call latency or matched before/after comparison.

六次目标身份分类均返回本地期望类别：四次地址栏（输入候选及 Enter 回锚）和两次官方结果链接；没有自然触发普通复核。身份分类输入共 4,470 tokens、输出 0；HTTP 中位 570.070 ms，服务中位 744.932 ms。首个服务调用 3.544 s，HTTP 1.775 s，存在明显首次开销。**这些是本轮有限样本的结果，不是通用准确率。** / Six identity classifications matched: four address-bar checks and two official-result links; no natural secondary review. Identity-only usage and timings are distinct from the whole flow, and do not establish general accuracy.

只读账本核对补齐输入值两次（不能只统计任务状态外层可见的判断）： / Read-only ledger verification includes the two nested input-value checks:

| 两轮合计 / Both flows | 请求 / Calls | 输入 / Input tokens | 输出 / Output tokens | 服务累计 / Service sum | HTTP累计 / HTTP sum |
|---|---:|---:|---:|---:|---:|
| 目标身份 / Target identity | 6 | 4,470 | 0 | 7.510 s | 4.511 s |
| 输入值 / Entered value | 2 | 1,357 | 0 | 0.726 s | 0.456 s |
| 页面结果 / Page result | 4 | 15,478 | 0 | 2.896 s | 2.681 s |
| Decision总计 / All Decision | 12 | 21,305 | 0 | 11.133 s | 7.648 s |
| 定位Luna / Grounding Luna | 4 | 11,001 | 1,272 | 21.228 s | 20.699 s |

主实时会话共16次已记录API请求，32,306输入 / 1,272输出 tokens；不含下面反例、本聊天规划上下文或其他进程。定位Luna单次服务中位5.250秒，HTTP中位5.154秒，仍是主要模型耗时。服务包含HTTP，不能相加；请求累计也不能与整轮墙钟直接互换。没有模型超时、重试或普通复核账本记录。 / The live session recorded16 API requests and33,578 total tokens, excluding the negative replay and this chat. Grounding remained the largest measured model component. Service includes HTTP; these sums are not additive to each other or interchangeable with caller wall time. No timeout, retry or secondary dispatch appeared in the live ledger.

12条Decision记录已从只读账本核对，完整输出为本地 `live-ledger-judgments.json`、聚合为 `live-metrics.json`。启动时生成的report里used=0是过时快照，不能代替真实账本used=12。外层初次导出只见8条，递归补为10条，最终以12条账本为准；漏统计已纠正，没有重新调用API。 / The ledger is authoritative; the startup report's zero-use snapshot and incomplete initial outer-record exports are not usage totals. Reporting was corrected without new API calls.

## 两级拒绝反例 / Two-stage negative case

对本轮真实 collections 页面做只读重放：标记中心位于地址栏，冻结选项为网页搜索框/地址栏/标签标题，故意将期望设为网页搜索框。没有派发任何点击或输入。 / Read-only replay of the actual collections capture: the marker is in the address bar, while the expected identity is deliberately the webpage search field. No input was dispatched.

`negative-readonly-02` 原始请求/回答保留：Decision 选 `b`（地址栏），普通 Luna 也选 `b`；最终 `condition_not_met / review_required`，认证通过。服务总耗时 3.153 s；Decision HTTP 475.654 ms，Luna HTTP 2,474.499 ms；合计 1,552 输入 / 5 输出 tokens。两层同一标图、同一身份问题；后者没有首层答案。 / Both selected the actual address bar, producing an authenticated nonmatch and review-required outcome. This confirms the two-stage refusal route, not recovery from a false rejection.

反例首次 harness 将截图留在服务会话目录之外，正式证据校验拒绝，0 API 调用。保留 `negative-readonly`；将相同截图字节复制进独立诊断会话后运行 02，未放宽生产校验。 / The first diagnostic harness failed the session-local evidence contract before dispatch. Its record remains; attempt 02 copied identical bytes into its own session, without weakening production validation.

## 离线检查与限制 / Offline checks and limitations

Main 最新复跑： / Latest Main verification:

```text
python -X utf8 -m pytest tests/test_target_identity_contract.py tests/test_target_identity_provider.py tests/test_target_identity_plan.py tests/test_target_identity_recorded_click.py tests/test_ordinary_review_cascade.py tests/test_luna_choice_review_provider.py tests/test_ordinary_review_input_consumers.py -q --tb=short
179 passed in 4.75s
```

覆盖原始身份/投影绑定、期望不上传、同图同问题、复核纠正后通过与拒绝、超时/预算、持久化重开、篡改及重复请求不重派。复核纠正后通过仅有离线模拟覆盖，实机两轮没有出现该分支。 / Covers binding, privacy of expected IDs, identical review evidence, corrected and rejected secondary results, deadlines/caps, persistence, tampering and no redispatch. Secondary correction is verified offline; it did not naturally occur in the two live flows.

扩展回归在 `--maxfail=8` 停止：**1519 passed、8 failed、1 skipped**；不宣称全量通过。两项旧提示词文本断言失败，另六项 `test_task_plan_target.py` 原生定位预期触发 `native match must not call model`；相关请求不含本次身份声明，失败路径未在本次修改。单独复跑 target 文件仍 47 passed、1 failed 后停止。没有跑修改前基线，不能仅凭分类断言这些失败已在之前实测。 / The broader scan stopped at eight failures: two legacy prompt assertions and six native-grounding expectations conflicting with the visual default. No pre-change baseline was executed; these failures remain open and are not hidden by the focused passes.

窗口通过 `close_launched_window` 返回 `window_closed`，finish 返回 `cleanup_verified:true`。浏览器 profile、缓存、Cookie、历史及扩展保留。冻结的 27 项生产源码 SHA256 直到收尾均一致。 / The owned window and host closed normally, browser data was retained, and all 27 frozen production hashes remained unchanged.

本轮未打包、安装、提交、推送或发布；未执行外部独立实机验收。首层误放仍绕过第二层（`DECISION-FALSE-ACCEPT-001`），按用户要求暂缓。Choice 直接选择参与路由，不新增概率阈值；部分正确选择置信度很低，不能据此推导可靠性保证。 / No build, install, commit, push, release or independent live acceptance. First-stage false passes still bypass review as explicitly deferred. Choice controls routing without adding a probability threshold; some matching choices had low confidence, so reliability is not guaranteed.
