# 两条核验路线的历史截图离线验证 / Historical-image offline verification

2026-10-14，`codex/dev-decision-api` 维护源码，未发布。 / Maintained source, unreleased.

后续真实测试已完成：一轮输入前失败，下一轮自动成功；详见[真实记录 / Live record](TARGET_CHECK_LIVE_20261014.md)。以下仅描述此前离线批次，不把模拟结果变为真实准确率。 / A later live batch has mixed results. The offline evidence below remains fixture-based.

## 结果与边界 / Outcome and scope

默认路线已改为原图形/按钮匹配或指定输入框内包含关系，二者互斥；定位描述不能改原goal或原动作路线。已移除自动生成控件干扰类别。Luna示例同次输出外观与所属区域，Decision和普通复核使用同一标图、同一个固定Choice问题。 / Exactly one original-goal check replaces automatic distractor classification. The same grounding call supplies an unverified appearance/container hint; both decision stages receive identical evidence and question.

本轮仅离线：**0真实API、0桌面动作、0实际API tokens**。所有判断回复和新定位描述均明确标为 synthetic fixtures。不能将下表的路由结果写成模型准确率、纠错收益或速度表现。未修改裁剪，未再次操作浏览器或清理资料。 / This is entirely offline. Synthetic replies establish contracts, not model accuracy, correction gains or latency. No crop or browser-data changes.

## 历史原件与回放 / Historical sources and replay

证据根：`D:/AgentGUI-Projects/evidence/target-check-offline-20261014-04`。`harness.py` 使用真实 `DecisionService/OpenAIDecisionsProvider`，只在HTTP边界采用 `httpx.MockTransport`，没有网络客户端回退。 / The maintained service/provider execute with an explicitly mocked HTTP boundary, without network fallback.

| 场景 / Scenario | 路线 / Route | 模拟回答 / Fixture answers | 验证结果 / Contract outcome |
|---|---|---|---|
| 历史＋目标 / Historical plus | graphic | 符合 / match | 直接采用 / adopted |
| 原目标＋，点在× / Plus goal, point on cross | graphic | 不符→不符 / nonmatch twice | review_required |
| 首次误拒的地址栏图 / Previously refused address-bar image | input_field | 不符→符合 / nonmatch then match | 复核后采用 / secondary adoption |
| 同一地址栏图，不确定 / Same image, uncertain fixture | input_field | 不确定→不确定 / uncertain twice | review_required |
| 目标地址栏，点在网页搜索框 / Wrong field | input_field | 不符→不符 / nonmatch twice | review_required |
| 原目标＋，定位提示声称× / Conflicting hint | graphic | 不符→不符 / nonmatch twice | 原目标未改变 / original goal retained |

6场景、11次模拟HTTP交互通过；认证重读没有新增交互，改原goal或kind后认证拒绝。历史原件SHA逐一匹配；＋/×和首次地址栏标图与原发送图字节一致。五个双层场景同图、相同前置文本，解析后的问题对象完全相同。定位提示冲突不会改变问题中的原目标。 / All six fixture-driven routes passed. Sources and annotated baselines match byte for byte; all five secondary reviews reuse the same image and parsed question. Replay is authenticated without redispatch, and altered intent is rejected.

最初01 harness漏review_context，被服务 `skipped / decision_review_context_missing`，账本used=0；02在比较JSON转义后的问题字符串时断言失败，已改为解析JSON再比较问题对象。03及最终04全部通过，原目录保留。02具体断言仅见Main工具输出，目录没有独立traceback文件，不冒称已保存原始异常日志。 / Initial harness failures are retained: missing review context before dispatch, then an incorrect escaped-string assertion. The fixed comparison parses JSON; final replay passes without paid calls. The second traceback exists in Main's tool history, not as a separate saved file.

## 源码检查 / Source checks

Main相关两组分别 **565 passed / 150 passed**；原动作类型决定路线的最终增量复跑 **40 passed**。新用例先观察失败再实现，包括类型错误的明确拒绝、原goal保持、同图同问题、普通复核采用/拒绝、重开不重派、源回执和缓存篡改、值核验与回锚绑定及新鲜度排除。 / Two scoped Main batches passed565 and150; a final40-check rerun covers the routing refinement and affected wiring.

主要命令 / Principal checks:

```text
python -X utf8 -m pytest tests/test_target_check.py tests/test_grounding_target_check_wiring.py tests/test_grounding_target_description.py tests/test_grounding_identity_wiring.py tests/test_grounding_identity_options.py tests/test_grounding_identity_expected.py tests/test_target_identity_contract.py tests/test_target_identity_provider.py tests/test_target_identity_plan.py tests/test_target_identity_recorded_click.py tests/test_vision_grounding_contract.py tests/test_external_grounding_api.py tests/test_external_grounding_call_budget.py tests/test_agent_command_action_review.py tests/test_visual_field_proof.py tests/test_visual_field_freshness.py tests/test_ordinary_review_cascade.py tests/test_ordinary_review_input_consumers.py tests/test_luna_choice_review_provider.py -q --tb=short
python -X utf8 -m pytest tests/test_agent_grounding_target.py tests/test_agent_grounding_execution.py tests/test_agent_grounding_choice_revalidation.py tests/test_visual_compound_input.py tests/test_visual_submit_target.py tests/test_visual_submit_settlement.py tests/test_visual_submit_proxy.py tests/test_visual_field_no_duplicate_review.py tests/test_action_review_single_authority.py tests/test_action_review_route.py tests/test_action_review_contract.py -q --tb=short
python -X utf8 -m pytest tests/test_target_check.py tests/test_grounding_target_check_wiring.py -q --tb=short
```

前一轮超宽框裁剪假设的2个未实现RED测试已原样归档到原实测证据的 `abandoned-crop-hypothesis`，未加入当前验收；生产裁剪源码没有变化。 / Unimplemented crop-hypothesis tests were archived without changing production rendering.

独立Sol做过03的只读证据核对及新producer/provider合同审阅；未做独立真实模型或实机验收。本轮没有运行仓库全套测试；此前广扫的8项失败保留在旧报告，不能据此宣称本轮仓库全部回归通过。此前真实两层误选标签栏的首败保留，本次没有证明它已被真实模型修复。 / Independent review was read-only and offline. No full-suite, live-model or installed acceptance was performed, and the prior real false rejection remains historical evidence.
