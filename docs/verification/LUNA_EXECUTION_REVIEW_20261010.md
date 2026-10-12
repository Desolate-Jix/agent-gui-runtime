# Luna 执行改动复审 / Luna execution change re-review

**后续处理 / Resolution:** 用户要求修复后，下列三项已完成源码修复及647项离线组合回归，见[修复记录](LUNA_EXECUTION_FIXES_20261010.md)。本文保留修复前的发现、复现和原始验证范围，不代表仍有三项待修。 / All three findings were subsequently repaired and verified by a 647-test offline group; the original review evidence below is retained.

2026-10-10，用户要求再次审核上次改动。本轮只审查及离线复现，不修生产代码或现有测试；真实桌面、UIA、API和安装均未执行。 / User-requested review with offline reproductions only; no production/test repairs, live desktop/UIA/API or installation.

候选与[上轮577项离线组合](LUNA_EXECUTION_OFFLINE_20261010.md)一致，1084个源码/测试/配置文件SHA未变。Codegraph未初始化，采用限定源码和调用方检查。三个Sol ultra独立审查API、UIA与调用入口，Main复核证据并独立运行下列三项复现。 / The reviewed candidate matches all 1084 hashes from the prior offline run. Bounded source/caller review replaces the unavailable index; Main independently reproduced the findings.

## 原始待修问题 / Original findings

### P1：固定JSONL入口丢失MCP图片 / The fixed JSONL caller drops MCP images

位置 / Location: `scripts/execution_client.py:142-150`；继承解析器 / Inherited parser: `scripts/learning_benchmark_client.py:139-149`。

新入口允许`instant_image`和`instant_result(images="after")`，但继承解析器只接收structuredContent或text。纯图片成功响应报`benchmark_client_response_missing`；混合响应仍声称`image_delivery.status=included`，实际图片块丢失。新入口自己返回的图片工具引用因此不能正常用于Main审核。 / Pure image results fail, while mixed results retain a false delivery claim after discarding the pixels, breaking the documented image-review route.

Main使用真实合成PNG、正式MCP CallToolResult形状及FakeSDK复现；无宿主/网络。现有测试只核对图片引用或使用字典FakeSDK，未覆盖实际图片块。建议在新客户端明确接收并保存/返回原图与摘要，同时纠正delivery描述；增加纯图片和混合响应回归。 / A real synthetic PNG and actual MCP result shape reproduce both failures. Handle image blocks explicitly and test both shapes.

证据 / Evidence: [Main图像复现](../../.superpowers/sdd/2026-10-10-luna-review/main-caller/image_transport_evidence.json)。

### P2：非200正文读取掩盖错误并延迟失败 / Reading error bodies masks HTTP status and delays failure

位置 / Location: `app/judgment/http_deadline.py:38-51`；上层映射 / Mapping: `app/vision/external_grounding_api.py:275-281`。

新默认transport在向上层返回状态/响应头前读取整个正文。回环复现：401且正文超限变成`api_response_too_large`、无status/request-id；429慢正文变成`api_timeout`，消耗约188ms的200ms预算。对照原同步transport立即保留401鉴权错误或429限流及request-id。 / The new default transport reads the body before exposing headers. Local reproductions turn 401 into a size error and slow 429 into timeout, losing the known status and request ID.

建议非200收到头后关闭正文并保留状态/头，由上层准确分类；成功正文继续按总预算及字节上限读取。已有默认transport测试使用Mock，已有回环状态测试使用立即完成的小JSON，漏掉慢/大错误正文。 / Close non-200 bodies promptly while preserving headers/status; retain bounded success-body reads. Existing tests miss slow or oversized error bodies.

证据 / Evidence: [Main HTTP复现与对照](../../.superpowers/sdd/2026-10-10-luna-review/main-api/repro_error_status_buffering.json)。

### P2：普通命令等待未遵守调用方总预算 / Ordinary commands lack a client-side total deadline

位置 / Location: `scripts/execution_client.py:157-162`；继承等待 / Inherited waits: `scripts/learning_benchmark_client.py:601-603,626-640`。

新JSONL入口暴露`total_timeout`，普通run只把剩余时间传给服务器的wait_ms，没有限制正在await的MCP调用。纯离线设置5ms预算、80ms延迟响应，Main实测94ms才返回；如果响应挂起，串行JSONL会话持续阻塞。task_plan使用的run_plan已有客户端有限等待。此问题来自旧helper，经新公共入口暴露，不是本轮HTTP deadline的新缺陷。 / The new public caller inherits an old helper's unbounded MCP awaits. A 5ms budget waited 94ms for an 80ms fake response. This is separate from the new HTTP transport regression.

建议为普通run的首次提交及后续回读落实剩余总预算；超时保留原request_id和只读恢复入口，禁止因超时再次派发动作。现有pending测试立即响应，未覆盖延迟等待。 / Bound each MCP await by remaining time while retaining the original request and no-replay recovery.

证据 / Evidence: [Main等待复现](../../.superpowers/sdd/2026-10-10-luna-review/main-caller/wait_budget_evidence.json)。

## 其余核对与验证边界 / Other checks and limits

- UIA缓存未确认确定的正确性/回退缺陷。本机生成接口核对Full=1及泛型矩形/接口定义；离线工厂复现显示真实pywinauto包装仍额外读取Current属性。这属于未测的性能开销，不作为行为缺陷。真实provider、rich_text、弹窗、失效和整链速度仍待实机。 / No confirmed UIA correctness regression; extra factory reads remain a performance risk requiring live measurement.
- Main检查输入validator接线、render_grace传递和结果认证免编码逻辑，未确认另一项引入缺陷；这不是完备性或实机安全保证。 / No additional confirmed defect in the scoped validator, grace or authentication changes.
- API审查相关原测试三模块88通过（4.31秒）；三项离线复现也执行完成并证明上述缺陷，不能把复现脚本exit 0当作产品修复通过。 / Existing 88 tests passed; successful reproduction scripts demonstrate bugs, not repaired behavior.
- 未修代码、未发布；首要顺序为图片交付、普通命令等待边界、HTTP错误分类，再补针对性离线回归后申请真实连续使用验收。 / Repair image delivery, ordinary-call deadlines and HTTP error handling, then run targeted offline regressions before scoped live acceptance.

证据目录 / Evidence directory: [luna-review](../../.superpowers/sdd/2026-10-10-luna-review/)。
