# 学习目标框修复 / Learned target boxes

2026-10-02，开发分支 `codex/dev-workflow-editor`，源码候选 v11。 / Development source candidate v11; no release or package version change.

## 故障与公共契约 / Failure and common contract

- 可见故障：6 个界面修订的 `content.regions` 均为空，截图原有按钮焦点边框容易被误认为可编辑标注。执行侧已有 5 个目标规则，但界面未显示其框，也没有从框进入对应步骤的入口。 / Interface annotations were empty while five executable locator references existed; a screenshot focus border was mistaken for an editable box.
- 根契约：目标显示、人工修订和执行引用必须绑定同一明确规则；代表界面和动作截图不能混用坐标。 / Display, editing and runtime consumption must share exact locator references and correctly bound source frames.
- 修复位置：学习图导入、只读目标投影服务、独立界面面板、既有步骤目标编辑器和保存服务；没有新增执行器。 / The fix spans import, projection and native editing while reusing the existing save and execution services.
- 通用性：来源身份、截图摘要、UIA 控件和动态列表约束用于所有受支持的 Windows 界面，不含 Record Desk 专用坐标或匹配规则。 / The contracts are application independent; no fixture-specific locator or coordinates were added.

## 使用和版本 / Usage and revisions

1. 新学习导入从已核对的动作观察生成标注；只在截图摘要相同的界面上保存框。旧空标注版本按归档来源只读恢复显示，不重写资产。 / New imports project validated candidates only onto matching source images; old empty revisions are recovered for display without rewriting them.
2. 独立界面库的上方列表默认显示已学步骤目标及其确切动作截图。没有动作目标的结果页可以没有目标框；不虚构可执行区域。 / Select a learned step above the canvas to see its exact action frame; result-only pages need not contain executable boxes.
3. 点击框查看其步骤，点击“修改此步骤的定位规则”打开已有目标编辑器。拖动框只能选择唯一、可见、启用、与动作类型相容的控件，框会贴合该控件完整边界。 / Boxes link to the existing target editor. Moving a box selects one supported control and snaps to its full bounds.
4. 预览唯一匹配后才能应用；保存产生新 recipe/program，相关审核失效。动态行保留容器、属性、条件与参数绑定，不变成固定行坐标。旧版本不被自动推进。 / Preview, apply and save produce immutable revisions and invalidate affected review. Dynamic row bindings remain intact; old published references never silently advance.
5. 独立界面标注可单独保存。编辑工作流目标使用已学步骤入口；不把普通标注保存误报成执行规则已更改。 / Annotation saves and executable locator edits expose their actual effects.
6. 未应用规则不能被“读取学习证据”覆盖。未保存步骤草稿或过期 program SHA/reference 会阻止从界面跳转覆盖现有编辑。 / Reload, unsaved edits and stale links are guarded against draft loss.

## 验证 / Verification

主 Agent 最终运行以下源码检查，结果 **168 passed in 90.43s**： / The final main-agent source run passed 168 checks:

```text
python -m pytest
 tests/test_interface_target_box_journey.py tests/test_learned_target_regions.py
 tests/test_workflow_target_boxes.py tests/test_learning_membership_ui.py
 tests/test_learning_memory_v1.py tests/test_workflow_target_editor.py
 tests/test_workflow_target_journey.py tests/test_workflow_target_editor_service.py
 tests/test_learning_observation_source.py tests/test_learning_action_evidence.py
 tests/test_target_recipe.py tests/test_target_resolution.py tests/test_target_resolution_rows.py
 tests/test_workflow_program_target_dependencies.py tests/test_memory_grounding_execution.py
 tests/test_workflow_user_journey.py -q
```

覆盖首次标注、错图拒绝、完整界面入口、换框与实际新定位候选、应用/保存/关闭重开、原版本保留、动态绑定、歧义和越界拒绝、未应用修改重载保护与过期引用。原始 RED 和审阅发现后 RED 均保留；77 项中间回归与各子任务检查和本次 168 项有重叠，不相加。 / Checks cover imports, frame binding, complete native entry, locator consumption, persistence, immutability, dynamic bindings and rejection/draft guards. Intermediate and worker counts overlap the final run.

证据目录 / Evidence directory:
`D:/AgentGUI-Projects/verification/AgentReviewAcceptance/20261002-learning-mainline-01/target-box-fix`

- `main-final.xml`：最终主回归。 / Final main regression.
- `import/red.log`、`import/green.log`；`service/red-contract.log`、`service/green.log`：子任务首次失败与修复结果。 / Worker red/green evidence.
- `existing-library-readback.json`：当前库 5 个执行目标均有框；49 个资产文件摘要未变。 / Five executable targets restored, 49 existing files unchanged.
- `render-existing.json`、`interface-target-box.png`、`workflow-target-box.png`：当前归档内容的离屏只读显示与跳转检查，动态行框明确为学习示例。 / Read-only offscreen debugging of archived content; dynamic boxes represent learning examples.
- `source-freeze-v11.json`、`main-source-receipt.json`：本批源文件摘要和实际修改范围。 / Candidate digests and change receipt.

离屏工具首先遇到字体未注册和布局尚未刷新，补充 Windows 字体与 Qt 事件处理后截图可读；没有把方块字截图记为视觉验收通过。 / The offscreen harness registered the system CJK font and allowed layout events to settle before visual inspection.

## 边界与下一步 / Limits and next step

本批没有派发真实外部点击或输入，也没有验证新的完整实机连续旅程。当前可拖框修订的是完整 UIA 证据中的唯一控件；缺 UIA 的视觉模板仍走现有独立模板入口，不把任意矩形当作安全点击坐标。 / No physical input or full live journey was executed in this slice. Box editing selects supported UIA controls; visual-only templates retain their existing explicit route.

下一验收用全新内容和新连接，在同一冻结候选中运行修改后的目标、保存重开、变化与恢复、连续复用和清理。稳定性主线优先，收益测量仍后置；本批不声称模型准确率或加速幅度。 / Next validate freshly edited targets, persistence, variation, recovery and cleanup with new content and connections on the same frozen candidate. Stability remains the priority; measured benefits remain pending.

安全影响：候选继续由当前截图/UIA 重新定位，原 action gate、窗口身份、上下文、freshness、最终提交阻止和歧义拒绝保持。预览不派发输入，归档框不构成执行授权。 / Current-capture grounding and existing action gates remain mandatory; preview and archived boxes grant no execution authority.
