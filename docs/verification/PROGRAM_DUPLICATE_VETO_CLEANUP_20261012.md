# 程序重复拦截清理 / Duplicate program-veto cleanup

日期 / Date: 2026-10-12。未发布源码 / Unreleased source.

认证 Decision 通过后，普通点击不再追加截图、像素比较和第二次语义审核；视觉字段不再因光标、边框或候选整框遮挡重复否决。Decision 提示词、阈值和初始/结果语义未改。本轮仅离线验证，没有真实 API 或桌面测试。

After authenticated approval, ordinary clicks no longer trigger another capture/pixel/review loop. Visual fields no longer veto caret, border or full-candidate-box presentation changes. Decision prompts, thresholds and initial/result semantics are unchanged. Offline verification only.

## 故障与修复 / Failure and repair

1. **故障 / Failure**：上轮 Decision 通过后，程序追加变化审核，再以第三帧像素不同拒绝；字段路径也因光标或边框变化重新审核，产生 freshness 暂停。
2. **通用约定 / Invariant**：Decision 负责语义可行性，程序负责绑定、权限及真实输入事实，不用像素相等另建一套语义否决。
3. **修复位置 / Location**：`app/execution/action_review_dispatch.py`、`decision_check.py`、`visual_field_proof.py` 和 `app/api/action.py`。合并审核与独立 auto 采用入口均清理；shadow 和未接入 Decision 的原行为保留。
4. **通用性 / Generality**：没有 Google、Java、特定浏览器或坐标特判，适用于共同视觉动作和字段证明路径。
5. **回归 / Regression**：离线真实路由验证 caret、border、outside 和 target 像素变化不追加语义调用；窗口身份、源 PNG 改写、取消、期限、真实焦点与实际点击点遮挡仍有拒绝负例。
6. **输入影响 / Input impact**：保留权限、危险动作限制、窗口/进程身份与几何、原候选点、真实输入回执和实际点击点门禁。已有 native 字段证据时保留身份、焦点、值、来源和选区连续性。Ctrl+A 后仍核验真实选区效果。删除像素循环不证明模型审核与输入之间页面绝不改变；每个新动作仍重新取证和定位，并核验结果。

The shared runtime now separates semantic approval from physical dispatch facts. It does not grant new authority or guarantee an atomically unchanged page between model review and input. Native continuity and real selection effects remain checked; each new action still needs its own evidence.

## 验证 / Verification

- 点击初始红测：4 failed / 3 passed；独立入口红测 1 failed，分别复现额外请求、局部像素及整图 hash 否决。
- 键盘新红测：4 failed / 2 passed；中间20个旧合同/采集数冲突经授权更新后，相关133项通过。
- 独立代码审阅发现原生读取可能跨越期限；新增红测1 failed，补入读取后的期限/取消检查。
- **Main 最终17个相关文件：374 passed / 19.19s**。该总数包含上述切片，不能累加。证据：`.superpowers/sdd/2026-10-12-remove-duplicate-veto/main-final.xml`。
- 旧像素循环专用断言保存于本轮 `.before` 快照，两个专用测试文件退出维护；用新合同的路由/原生事实覆盖替代。
- Decision 供应商提示、条件常量和示例 profile 的 SHA256 与上轮最终冻结一致。
- Codegraph 未初始化，使用 rg 和直接读取。未运行全测试集、桌面、真实 API、安装/打包或独立实机验收；未提交、推送或发布。

Final focused regression: **374 passed**, including the component checks above. Red tests and superseded assertions are retained as evidence. Provider prompts, condition constants and the example profile match their prior frozen hashes. No full-suite, live API/desktop, packaging, publication or independent desktop acceptance was performed.

运行命令 / Command:

```text
D:/agent-gui-runtime/.venv/Scripts/python.exe -B -X utf8 -m pytest -q tests/test_action_review_single_authority.py tests/test_action_review_route.py tests/test_decision_click_visibility.py tests/test_action_review_contract.py tests/test_execution_decision_check.py tests/test_recognition_no_dispatch.py tests/test_nonmodal_popup_parent_click.py tests/test_popup_decision.py tests/test_visual_field_proof.py tests/test_visual_field_freshness.py tests/test_native_caret_freshness.py tests/test_visual_field_no_duplicate_review.py tests/test_input_sequence_type_partial.py tests/test_input_sequence_focus_partial.py tests/test_input_sequence_search_partial.py tests/test_type_text_no_dispatch.py tests/test_key_no_dispatch.py
```

## 后续 / Next

单独评估 Decision 对真实正负样本的焦点、字段值和最终页面判断。程序重复像素否决不再是该路径的变量；旧实测失败保持原样，本轮离线通过不能当成模型准确率或真实速度提升。

Evaluate semantic quality separately using retained real positive/negative evidence. This offline cleanup does not establish model accuracy, live speed gains or intervention-free task completion.
