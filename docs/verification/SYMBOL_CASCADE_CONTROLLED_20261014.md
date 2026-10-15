# 符号二选一受控复测 / Controlled symbol cascade rerun

2026-10-14。仅调用真实 API 的诊断实验；未修改正式提示词、路由、阈值或桌面行为。 / Real API diagnostic only; production prompts, routing, thresholds and desktop behavior are unchanged.

## 方法 / Method

- A：原样复制旧 `decision-symbol-choice-20261014-01` 请求和两张裁剪标注图。重建发送载荷的 SHA-256，与旧调用日志逐一一致。问题仍为标记中心是什么符号，选项顺序为 `plus`、`cross`。 / A reproduces the old Decision requests byte for byte, including image data, verified against the historical dispatch hashes.
- B：仅将同一问题转换为普通 Responses 请求，附加仅输出选项的格式指令。图片、坐标、问题文本与选项不变；`gpt-6-luna`、reasoning `none`、32 output tokens、default tier、store false。协议信封不能字节一致，差异完整保存。 / B changes the endpoint adapter, retaining identical evidence and question, with a fixed option-only formatting instruction.
- C：重新调用 A；`plus` 直接继续，`cross` 才调用 B；第二层 `plus` 继续、`cross` 转 Main。第二层不接收第一层答案或历史。所有请求复用 A/B 固定载荷。 / C makes fresh sequential calls with the fixed A/B payloads; no answer leakage or manufactured refusal.
- 每组两图各五次，交替图片顺序，共35个独立请求ID，零重试、零解析/HTTP失败。图片哈希、原始响应、用量和分支计时逐项核对。 / Five repetitions per image per group, 35 unique requests, no retries or transport/parser errors; raw evidence and accounting checked.

## 结果 / Results

|组 Group|正确 Correct|调用 Calls|每题 HTTP 中位数 Median|输入总量 Input|输出总量 Output|
|---|---:|---:|---:|---:|---:|
|A：Decision 原样复现|10/10|10|0.219 s|8,280|0|
|B：普通 Luna 二选一|10/10|10|1.646 s|9,230|50|
|C：条件触发两级|10/10|15|0.842 s|12,895|25|

C 的混合中位数受正反例各半影响，应优先看两个分支： / Prefer branch timings over the mixed median:

- `plus → continue`：5/5；HTTP 中位数0.208秒；每次828输入、0输出token。
- `cross → Luna cross → Main`：5/5；两次HTTP合计中位数1.956秒；每次1,751输入、5输出token。

全批30,405输入、75输出token；API报告缓存token均为0。旧二选一基线也是10/10、HTTP中位数0.224秒、8,280输入/0输出。 / Total: 30,405 input and75 output tokens, zero reported cache tokens. The old binary baseline was also10/10, median0.224s, 8,280/0 tokens.

## 解释与限制 / Interpretation and limits

这次确认了旧二选一结果可复现，以及真实非通过结果能触发普通Luna复核并正确转Main。上一轮5/10与2/10使用的是另一种通用目标匹配问题，不能当作同方案复测失败。 / The old binary result reproduced and genuine nonpass results traversed the secondary branch correctly. Earlier5/10 and2/10 used a different target-match question and were not reproductions of this scheme.

本轮第一层没有误拒，因此未验证“第一层错误拒绝→Luna纠正通过”的收益，也没有证明两级提高准确率。第一层误放仍会跳过第二层，既有缺陷未解决。两张固定图片反复测试不代表通用GUI准确率；二选一没有未知类。 / No first-stage false rejection occurred, so correction benefit was not measured. First-stage false accepts still bypass review. Two repeated images and a forced binary choice do not establish general GUI accuracy.

分组依次执行，时间可能受服务负载和连接复用影响，不能将历史差异全部归因于提示词。HTTP时间包括网络，不含桌面动作、截图采集、Main接管或生产服务开销。这是独立实验脚本的路由验证，不是正式 runtime 端到端验收。 / Sequential batches are not interleaved latency controls. HTTP timings exclude desktop/Main/production-service work. Diagnostic routing is not production end-to-end acceptance.

Evidence: `D:/AgentGUI-Projects/evidence/amadeus-codex-runtime-2026-10-14/run-caa6cb09/symbol-cascade-controlled-20261014-01`. See `manifest.json`, `summary.json`, `dispatch.jsonl`, frozen requests, raw replies and per-trial records. Harness: `E:/amadeus-prs/symbol_cascade_controlled.py`.
