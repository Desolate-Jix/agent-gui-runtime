# 默认图像核验源码验证 / Default image-verification source checks

2026-10-07，`codex/dev-workflow-editor`。本轮只修改维护源码；未更新安装包、版本号或发布。 / Maintained-source change only; no installer, version or publication change.

## 结果 / Result

新学习默认对可区分前后状态的局部图像提议规则，保留待审核状态。图像匹配明确时通过现有 Trial/Runner；不确定时保留原请求交 Agent。用户关闭后保存重开不会补回。 / New learning proposes a discriminating local image rule pending review. Conclusive matching uses the existing Trial/Runner; inconclusive matching preserves the request for Agent review. Disablement persists across save/reopen.

Main 合并回归：**160 passed in 76.49s，exit 0**。覆盖原图及几何验证、歧义、伪造 proof、最终消费重算、原请求保留及 Agent 回交、编译提议、来源版本、动态读取排除，以及真实合成内容的离屏编辑、关闭重开和中英文切换。 / Main's integrated checks passed. Coverage includes evidence integrity, ambiguous matches, forged proofs, final consumption recomputation, pending preservation and Agent review, default proposals, pinned sources, dynamic-read exclusion, and synthetic offscreen edit/reopen/language journeys.

实际命令 / Actual command:

```text
python -B -X utf8 -m pytest tests/test_image_verification.py tests/test_workflow_image_verification.py tests/test_image_verification_proposal.py tests/test_image_verification_sources.py tests/test_learning_synthesis.py tests/test_learning_action_evidence.py tests/test_workflow_program.py tests/test_workflow_verification.py tests/test_workflow_runtime_verification.py tests/test_workflow_runner.py tests/test_workflow_rules_editor.py tests/test_workflow_steps_ui.py tests/test_workbench_i18n.py tests/test_workflow_image_check_editor.py tests/test_workflow_image_check_journey.py tests/test_workflow_definition_summary.py -q
```

解释器为 `D:/agent-gui-runtime/.superpowers/sdd/2026-09-13-formal-release/.venv-clean-desktop/Scripts/python.exe`，工作目录为当前维护工作树。完整命令、stdout、exit 保存在本轮证据目录 `main-final-tests.txt`。 / The full invocation and output are retained there.

翻译扫描：24 文件、1190 消息、`problems=[]`；40 个相关源码、测试和文档通过 UTF-8/源码解析检查，五个原有状态文档的原字节完整保留。双语 QM 已更新。 / Translation scan has no catalog problems; relevant files parse as UTF-8, five original status documents remain byte-preserved, and both QM files are updated.

## 真实截图及失败保留 / Live captures and retained failures

全新自有 Qt 测试窗口通过项目截图接口采集，同一窗口换数据后连续三次目标匹配通过，返回错误状态后最多三次观察并拒绝；窗口正常关闭。六张验证用原图 SHA 已重读核对。**没有派发键鼠输入**，这不是完整真实动作工作流验收。 / Fresh owned-window captures pass three successive changed-data target states, reject the wrong state, and close normally. Six retained PNG hashes were reread. No keyboard/mouse input was dispatched; this is not full real-action workflow acceptance.

首次失败仍保留：模块/规则缺失的 RED；来源节点身份读取错误；最终消费曾只信任落盘匹配标记的漏洞；摘要曾遗漏图像规则计数；测试夹具及探针导入错误。修复后结果单独记录，没有把复测成功当作首次成功。 / Initial implementation, source-identity, final-consumer, summary-count and fixture/probe failures remain distinguishable from subsequent successful runs.

证据根目录 / Evidence root: `.superpowers/sdd/2026-10-07-optional-image-verification`，包含 `backend-logs`、`ui-logs`、`main-final-tests.txt`、`main-final-catalog.json`、`main-final-static.json` 和 `live-capture-01/result.json`。最终消费漏洞的完整 RED 为 `backend-logs/consumer-red-01.txt`；部分早期 RED 仅有工具输出或摘要，未声称完整日志均已保存。 / Some early RED runs retain tool output or summaries rather than complete local logs.

## 未跑及限制 / Not run and limitations

完整真实点击、异常恢复、真实 Agent 接管的连续流程及安装包验收留待冻结候选。没有本轮端到端速度、准确率或模型用量收益 benchmark。局部相似度不是准确率，一轮学习不能证明区域长期稳定；规则仍需审核和后续新数据验证。 / Frozen-candidate real-action, recovery, live Agent takeover and installer acceptance remain. No end-to-end speed, accuracy or model-usage benefit is claimed; similarity is not accuracy, and a single observation cannot establish long-term stability.
