# Decision API integration evidence / 判断 API 接入证据

Date / 日期: 2026-10-08. Candidate / 候选: `codex/dev-decision-api`, based on published `origin/main` `db443ef99eee67cd4dbaf7f57ce997d1542b2fd1`. Source changes only; no release tag, installer build or publication. / 本轮仅源码开发，未打标签、打包或发布。

## Real provider smoke / 真实服务调用

Main used the production `DecisionService` and `OpenAIDecisionsProvider`, not a standalone substitute client. Two newly generated 640×360 synthetic Record Desk images were uploaded; no desktop screenshot or user page was uploaded. The process read the user-authorized credential without logging or persisting it. A one-use runner marker and a service cap of two bounded dispatches. / 主 Agent 通过生产适配器发送本轮新建合成图；未上传真实桌面或私人页面，凭据未进入输出或持久记录；一次性标记及额度限制为两次发送。

| Case / 样本 | Result / 判断 | Input tokens | Output tokens | HTTP ms | Server processing ms | Service elapsed ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| DEC-210, Ready | success; condition=1.0, visible_error=0.0 | 608 | 0 | 1204.3862 | 474 | 1885.2819 |
| DEC-999, error page while expecting DEC-210 | failure; condition=0.0, visible_error=0.99 | 608 | 0 | 205.1191 | 103 | 211.0407 |

Both returned completed authenticated results. Reopening the same session without the key returned both exact original results; the dispatch database still contained exactly two sends. Two independent predicates shared each request. / 两次均为完成且可认证结果；移除 Key 后重开原会话回读完全一致，发送记录保持两条，每次合并两个独立谓词。

Total: 1,216 input tokens and zero output/cache tokens. At the documented input rate of $0.10/M tokens, the estimated input charge is **$0.0001216**; this is an estimate from returned usage, not an account invoice. [Official Decisions guide](https://developers.openai.com/api/docs/guides/decisions). / 按返回用量估算输入费用，不等于账户账单。

Server timing is the returned `openai-processing-ms`, not a measured pure inference breakdown. The service duration includes local preparation, client setup and the dispatch marker, but ends before final result encryption/persistence; the outer evaluate-call times were 1891.1322/216.3911 ms. The HTTP timer starts after client construction, and the second call reused the client. These nested timings must not be added. Two samples do not establish warm/cold distributions, guaranteed latency or model accuracy. / 服务端时间不是纯推理分解；服务计时包含本地准备、客户端初始化与发送标记，不含最终结果加密落盘；外层完整调用为 1891.1322/216.3911 ms。HTTP 计时不含客户端创建，各层耗时不可相加。两次样本不构成延迟分布或准确率结论。

Local evidence (kept outside public release artifacts): `.superpowers/sdd/2026-10-08-decision-api-integration/live-production-adapter/result.json`, its synthetic images and SQLite records; runner `live_adapter_smoke.py` intentionally refuses a second invocation with the same marker. / 本地保留原始结果、合成图、数据库与一次性脚本；不会通过删标记重跑计费。

## Source checks / 源码验证

Interpreter: the existing clean Windows desktop Python environment, Python 3.11 dependencies already installed; no dependency installation in this task. Tests use current maintained source interfaces and fresh temporary data. / 使用现有干净桌面解释器，未安装新依赖；所有测试使用当前维护接口和新临时数据。

- Provider final regression: `tests/test_decision_service.py tests/test_openai_decisions.py tests/test_optional_judgment.py`: **89 passed**. Evidence includes invalid images/paths/window/hash, strict responses, probability conflicts, no retries, cap, duplicate/conflict, DPAPI corruption, offline reopening, cross-thread close/finalization and strictly read-only result authentication. / 覆盖证据、协议、额度、重开、关闭竞态及真正只读认证。
- Execution worker regression: 208 passed across the new check and ten affected execution files. Includes real coordinator → ASGI action route → DecisionService → mock HTTP/DPAPI → input test double; no native input performed. / 真实源码链路，输入边界使用替身。
- Learning initial regression: 170 passed across eleven files, including real Trial settlement with mock HTTP and DPAPI. Independent review then identified a recovery-history compatibility gap; this first pass does not count as final recovery acceptance. / 首轮通过后独立审阅发现恢复历史缺口，保留发现记录。
- Main configuration, projection and cleanup focus: 19 passed after fixing profile snapshot drift and provider-close cleanup interruption. Original input status remains distinct from task effect; asynchronous status binds the original command. / 修复冻结配置及清理异常后通过。
- Main final execution/configuration/client/compatibility check: 29 files, **591 passed in 39.03s**, saved in `main-final-execution-rerun.xml`, including the final read-only authentication change. The earlier 586-test result remains in `main-final-execution.xml`. / 主 Agent 最终组合含认证只读化，保留早期结果。
- Main final learning/recovery check: 20 files, **320 passed in 27.94s**, saved in `main-final-learning.xml`. Maintained recovery now admits decision evidence and authenticates the original condition, receipt, frame, frozen profile and DPAPI ledger without a key, provider call or source-session write. It rejects missing/tampered evidence and oversized ledgers before reading them. / 主 Agent 最终学习与恢复组合通过；原证据只读认证，缺失、篡改和超大账本均拒绝。
- Main offscreen rule/image editor check: **12 passed in 0.52s**; changing a local image rule preserves its reviewed decision condition. / 离屏验证图像规则编辑保留判断条件。
- Independent review: provider close/finalization follow-up **3 passed**; Main epoch/client follow-up **56 passed**; final learning/recovery follow-up **172 passed in 17.13s**, saved in `learning-review-recovery-final.xml`. The original recovery incompatibility and pre-read size-limit failure were retained, fixed and rechecked. No unresolved actionable finding remained in these reviewed scopes. / 独立复核已闭合已发现问题；首次失败未改记为通过。

These groups overlap; their counts are not a total of distinct tests. Exact commands and retained failures are in the local Main ledger and worker reports. / 各组合存在重复用例，数量不相加作为独立测试总数；命令与首败记录保留在本地。

Final static checks: all 40 changed/new Python source and test files decoded as UTF-8 and parsed; all 32 local links in the four affected public documents resolved; the sample profile validated and newline-aware `git diff --check` passed. All three updated skill copies passed `quick_validate.py`; personal and maintained vision skill contents matched. / 最终静态检查通过：40 个 Python 文件、32 个本地文档链接、示例配置、差异格式及三份技能；视觉技能两份内容一致。

Initial failures are retained in worker reports and the Main ledger, including missing feature contracts, wrapper authentication, async execution ID, isolated admin import, metadata forwarding, mutable-profile projection and recovery origin validation. They are not relabelled as first-attempt passes. / 首次失败与修复复测分别记录。

## Scope remaining / 未覆盖范围

No new physical GUI flow, installed-package/UAC acceptance or comparative accuracy benchmark was run for this API slice. Existing installed hosts and release packages have not reloaded these changes. / 本 API 开发批次未进行新实机流程、安装包/UAC 验收或准确率对照测试；现有安装版本未更新。

Before wider automatic adoption, collect fresh labeled cases and compare Agent-only, local-image verification and local-image+Decision on identical tasks: first-pass correctness, false acceptance, uncertain rate, full-task time p50/p95, actual provider calls/tokens, interruption/recovery and final cleanup. Keep failed first runs separate from repaired reruns. No whole-task token savings or performance uplift is claimed now. / 扩大自动采用前用同批新任务对照正确率、误放行、不确定率、全任务时间、真实用量与完整恢复清理，不据两个合成样本宣称收益。
