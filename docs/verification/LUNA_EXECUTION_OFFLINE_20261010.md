# Luna API 执行提速离线验证 / Luna API execution offline verification

日期 / Date: 2026-10-10. 分支 / Branch: `codex/dev-decision-api`.

**后续复审与修复 / Subsequent review and repairs:** 同一候选复审发现图片交付、慢错误正文和普通MCP等待三项缺口；随后已修复并完成[647项组合回归](LUNA_EXECUTION_FIXES_20261010.md)。下方577通过记录保持原范围，不补写成当时已覆盖这些场景。 / Three later findings were repaired and verified by a 647-test group; the historical 577 passes retain their original scope.

## 授权与范围 / Authorization and scope

用户批准“如果是离线测试可以”。本轮采用合成图片、临时数据、模拟UIA/输入、MockTransport，以及127.0.0.1随机端口的HTTP超时检查；不操作桌面、不发真实Luna或Decision请求、不启动执行宿主、不安装。组件仅核对依赖及临时源码复制，排除完整载荷构建 `real_payload`。 / Approved offline tests use synthetic data, fake desktop boundaries, mocked HTTP and loopback-only timeout servers. No live desktop, paid API, execution host or installation; full payload builds are excluded.

测试命令均使用 `D:/agent-gui-runtime/.venv/Scripts/python.exe -B -X utf8 -m pytest -p no:cacheprovider`。证据目录 / Evidence: [run-01](../../.superpowers/sdd/2026-10-10-luna-offline/run-01/).

## 首轮结果与修复 / First attempts and repair

| 分组 / Group | 结果 / Result | 耗时 / Time | 原件 / Evidence |
|---|---|---|---|
| 固定入口及输入 / Caller and input | 123 passed | 4.07s | `client-input-first.log/.xml` |
| 视觉API与定位 / Visual API and grounding | 155 passed | 3.76s | `vision-first.log/.xml` |
| 批量控件 / Bulk UIA | 161 passed | 3.60s | `uia-initial.log/.xml` |
| Decision认证、HTTP与等待 / Authentication, HTTP and waits | 116 passed | 26.59s | `main-first.log/.xml` |
| 组件依赖 / Component dependencies | 6 passed, 1 failed, 1 deselected | 51.74s | `component-first.log/.xml` |
| 失败单项复测 / Failed case rerun | 1 passed | 21.82s | `component-retest.log/.xml` |

组件首败位于 `test_copied_execution_sources_close_adaptive_protocol_and_linked_profile`：依赖及复制字节一致检查通过，末尾仍要求旧 `mode=shadow`。用户先前要求和当前配置/文档都已采用 `v2/auto/proactive/adaptive`。仅修正这个过期预期，并精确断言 `proactive_review=true`、`review_policy=adaptive`、`auto_conditions=[]`；生产代码和配置不变。最终组合加入实际默认路由测试，验证自动继续、需Main审核和无API路径。 / The copy test expected obsolete shadow mode despite the approved auto default. Only its assertion was corrected, retaining exact policy and empty allow-list checks; production/configuration did not change. Functional default-routing tests join the final group.

首败原件保留，不将复测改记为首次通过；分组与最终组合重叠，不累加通过数。 / Original failure is retained; reruns and overlapping groups are not summed.

## Main最终组合 / Main integrated verification

Main最终21模块组合：**577 passed，1 deselected，0 failed/error/skipped，113.02秒，exit 0**。唯一排除项为完整载荷构建 `real_payload`，并非跳过失败。覆盖固定Luna入口、模拟API/输入、UIA缓存、认证、等待、组件依赖和实际默认路由。 / Main's final 21-module group passed all 577 selected tests; one full-payload build was deliberately deselected, with no failures/errors/skips. Test-suite time is not GUI execution latency.

组合前后 **1084个源码/测试/配置文件的SHA256完全一致**。本轮首轮到最终仅组件测试文件发生上述预期修正，生产代码没有因本轮验证再变动。 / All 1084 tracked snapshot entries stayed unchanged during integration; only the documented test assertion changed between the initial and final groups.

证据 / Evidence: [完整命令](../../.superpowers/sdd/2026-10-10-luna-offline/run-01/integrated-command.json)、[原始输出](../../.superpowers/sdd/2026-10-10-luna-offline/run-01/integrated.log)、[JUnit](../../.superpowers/sdd/2026-10-10-luna-offline/run-01/integrated.xml)、[结果与源码稳定性](../../.superpowers/sdd/2026-10-10-luna-offline/run-01/integrated-result.json)。

## 结论边界 / Limits

- 离线测试验证入口选择、连接/协议、坐标变换、输入前拒绝、缓存一致性、原证据认证、等待及审核分流，不证明模型真实识别准确率或网络延迟。 / Offline contracts are not real-model accuracy or latency evidence.
- UIA真实Windows缓存矩形、rich_text、接口HRESULT、别名/弹窗及失效行为和完整扫描用时仍待实机验证；属性微基准不能推广为当前整链提速。 / Windows provider behavior and full-scan timing still need live acceptance.
- Luna定位与Decision结果判断仍分别配置；本轮没有收费请求，未改变用户已安装宿主、版本或公开下载。 / No paid calls or installed/released changes.
- 下一步须先申请有明确动作范围和费用上限的真实API/桌面测试，验证连续使用、异常恢复和清理，并按阶段拆分用时。 / Obtain scoped live/API approval before continuous-use, recovery and latency comparisons.
