# Interface Review Pages And Workflow Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将学习成果区重构为未审核界面、已审核界面和独立软件流程三个顶级大页，并硬性禁止 Agent 使用未审核单界面证据。

**Architecture:** 单界面资产作为唯一事实来源，审核页只做状态过滤，软件流程仅保存界面引用。面板共享一套证据预览组件；后端集中计算 `agent_usable` 并在 Agent 上下文边界 fail closed，未审核节点可参与流程设计但只投影阻断元数据。

**Tech Stack:** FastAPI、Python 3.11、原生 HTML/CSS/JavaScript、Node.js `node:test`、pytest。

## Global Constraints

- Agent 负责决策，Operation 负责真实操作，Gate 检查每个真实动作，Trace 保存证据。
- Workflow / PathGraph 不是执行授权。
- 未审核单界面可以加入流程，但不得进入 Agent 可操作上下文。
- 修改已审核证据必须撤销审核资格。
- 不修改 final-submit 阻断策略，不放宽 Gate。
- 不使用历史坐标执行；执行时必须基于当前截图重新定位。
- 所有中文文件使用 UTF-8，JSON 使用 `ensure_ascii=False`。
- 只修改与本功能有关的面板、流程投影、Agent 上下文和对应测试，不做无关格式化。

---

## File Structure

- Modify: `app/learn/interface_workflow_review.py` — 统一审核状态、资产投影、流程节点可用性和 Agent 上下文门控。
- Modify: `app/web_panel/learning_workflow_review.js` — 建立去重后的单界面资产视图模型和流程节点状态投影。
- Modify: `app/web_panel/index.html` — 三个顶级页面、共享证据工作区和加入流程弹窗结构。
- Modify: `app/web_panel/panel.js` — 页面切换、资产列表、预览、加入流程和路径图选择状态。
- Modify: `app/web_panel/interface_workflow_graph.js` — 节点审核状态和连线视觉投影。
- Modify: `app/web_panel/panel.css` — 三页布局、状态颜色、响应式证据区和路径图高度。
- Modify: `tests/test_interface_workflow_review.py` — 后端审核分组与 Agent 门控回归。
- Modify: `tests/js/learning_workflow_review.test.cjs` — 前端资产去重和审核状态投影测试。
- Modify: `tests/js/interface_workflow_graph.test.cjs` — 图节点状态和混合流程测试。
- Modify: `tests/test_web_panel_route.py` — HTML 结构、事件绑定和安全文案测试。
- Modify: `README.md` — 同步新的学习成果和流程管理入口。
- Review/update locally when behavior changes: `PROJECT_SUMMARY.md`, `CURRENT_STATE.md`, `NEXT_STEPS.md`。

---

### Task 1: 统一审核状态与 Agent 可用性

**Files:**
- Modify: `app/learn/interface_workflow_review.py:530-685`
- Test: `tests/test_interface_workflow_review.py`

**Interfaces:**
- Produces: `project_interface_review_eligibility(node: dict, *, projection_error: str = "") -> dict[str, Any]`
- Produces registry fields: `agent_usable`, `agent_eligibility_reason`, `review_bucket`。
- Consumes: `review_status`, `reviewed_by_human`, `source_paths`, `editable_review_source_path`。

- [ ] **Step 1: 写失败测试，确认普通候选不能给 Agent 使用**

```python
def test_interface_review_eligibility_fails_closed_for_unreviewed() -> None:
    result = project_interface_review_eligibility(
        {"review_status": "reviewed_candidate", "reviewed_by_human": False}
    )
    assert result == {
        "review_bucket": "unreviewed",
        "agent_usable": False,
        "agent_eligibility_reason": "human_review_required",
    }
```

- [ ] **Step 2: 写失败测试，确认只有人工审核状态进入 reviewed**

```python
def test_interface_review_eligibility_accepts_human_reviewed_node() -> None:
    result = project_interface_review_eligibility(
        {"review_status": "human_approved", "reviewed_by_human": True}
    )
    assert result["review_bucket"] == "reviewed"
    assert result["agent_usable"] is True
```

- [ ] **Step 3: 运行窄测试并确认失败**

```powershell
uv run pytest tests/test_interface_workflow_review.py -k "review_eligibility" -q
```

Expected: FAIL，因为集中式资格计算函数尚不存在。

- [ ] **Step 4: 实现最小资格计算并让 `_project_interface_review_groups` 复用**

```python
def project_interface_review_eligibility(
    node: dict[str, Any],
    *,
    projection_error: str = "",
) -> dict[str, Any]:
    status = str(node.get("review_status") or "needs_human_review").strip().casefold()
    reviewed = (
        node.get("reviewed_by_human") is True
        and status in _HUMAN_REVIEWED_INTERFACE_STATUSES
        and not projection_error
    )
    return {
        "review_bucket": "reviewed" if reviewed else "unreviewed",
        "agent_usable": reviewed,
        "agent_eligibility_reason": (
            "human_reviewed_current_revision"
            if reviewed
            else projection_error or "human_review_required"
        ),
    }
```

- [ ] **Step 5: 运行测试**

```powershell
uv run pytest tests/test_interface_workflow_review.py -k "review_eligibility or projects_interface_review_groups" -q
```

Expected: PASS。

---

### Task 2: 在 Agent 上下文边界阻断未审核节点

**Files:**
- Modify: `app/learn/interface_workflow_review.py:629-685`
- Test: `tests/test_interface_workflow_review.py`

**Interfaces:**
- Consumes: `project_interface_review_eligibility`。
- Produces: `agent_ready`, `blocked_interfaces`, `agent_usable_interfaces`。
- Produces blocker contract: `blocked_unreviewed_interface`，不包含控件或历史坐标。

- [ ] **Step 1: 写混合流程失败测试**

```python
def test_agent_context_blocks_unreviewed_workflow_nodes(tmp_path: Path) -> None:
    context = load_interface_workflow_agent_context(
        project_root=tmp_path,
        application_identity_key="website:example.test",
    )
    assert context["agent_ready"] is False
    assert context["blocked_interfaces"][0]["availability"] == "blocked_unreviewed_interface"
    assert context["blocked_interfaces"][0]["agent_usable"] is False
```

- [ ] **Step 2: 写阻断投影不泄露动作证据测试**

```python
def test_blocked_interface_does_not_expose_actionable_evidence() -> None:
    blocked = build_blocked_interface_projection({"node_id": "pending_form"})
    serialized = json.dumps(blocked)
    assert "controls" not in blocked
    assert "actions" not in blocked
    assert "bbox" not in serialized
    assert "click_point" not in serialized
```

- [ ] **Step 3: 运行失败测试**

```powershell
uv run pytest tests/test_interface_workflow_review.py -k "agent_context_blocks or actionable_evidence" -q
```

Expected: FAIL，因为当前上下文会投影整个流程。

- [ ] **Step 4: 实现 fail-closed 投影**

只把 `agent_usable=true` 的节点送入 Agent 证据。未审核节点生成最小 blocker；流程包含必要 blocker 时 `agent_ready=false`。保留现有 `historical_coordinates_forbidden`、`current_capture_required`、`fresh_grounding_required`、`gate_required` 和 `post_action_verification_required`。

- [ ] **Step 5: 运行测试**

```powershell
uv run pytest tests/test_interface_workflow_review.py -q
```

Expected: PASS。

---

### Task 3: 建立去重的单界面资产视图模型

**Files:**
- Modify: `app/web_panel/learning_workflow_review.js:880-980`
- Test: `tests/js/learning_workflow_review.test.cjs`

**Interfaces:**
- Produces: `buildInterfaceAssetLibrary(registry, availableSources)`。
- Returns: `{ reviewed: InterfaceAsset[], unreviewed: InterfaceAsset[] }`。
- Asset fields: `asset_key`, `node_id`, `display_name`, `review_status`, `agent_usable`, `application_identity`, `workflow_memberships`, `source_path`。

- [ ] **Step 1: 写失败测试，确认同一来源跨流程去重**

```javascript
test("buildInterfaceAssetLibrary deduplicates one interface across workflows", () => {
  const library = review.buildInterfaceAssetLibrary(registryWithSharedSource(), []);
  assert.equal(library.reviewed.length, 1);
  assert.deepEqual(
    library.reviewed[0].workflow_memberships.map((item) => item.workflow_id),
    ["flow_a", "flow_b"],
  );
});
```

- [ ] **Step 2: 写失败测试，确认未知状态 fail closed**

```javascript
test("unknown review states fail closed", () => {
  const library = review.buildInterfaceAssetLibrary(registryWithUnknownStatus(), []);
  assert.equal(library.unreviewed[0].agent_usable, false);
});
```

- [ ] **Step 3: 运行失败测试**

```powershell
node --test tests/js/learning_workflow_review.test.cjs
```

Expected: FAIL，因为新视图模型尚不存在。

- [ ] **Step 4: 实现资产键与合并规则**

优先使用规范化 `source_path` 作为 `asset_key`；来源缺失时使用 `application_identity_key + node_id`。审核冲突时 fail closed：任一引用未审核或证据状态未知，则资产进入未审核页。

- [ ] **Step 5: 运行测试**

```powershell
node --test tests/js/learning_workflow_review.test.cjs
```

Expected: PASS。

---

### Task 4: 重构为三个顶级页面

**Files:**
- Modify: `app/web_panel/index.html:703-870`
- Modify: `app/web_panel/panel.css:4872-5335`
- Modify: `app/web_panel/panel.css:7240-7270`
- Modify: `app/web_panel/panel.js:10110-10201`
- Test: `tests/test_web_panel_route.py`

**Interfaces:**
- Produces DOM IDs: `interfaceAssetUnreviewedPage`, `interfaceAssetReviewedPage`, `interfaceWorkflowLibraryPage`, `interfaceAssetSharedEvidence`。
- Produces state: `interfaceAssetWorkspaceState = { activePage, selectedAssetKey }`。
- Reuses the existing evidence renderer and box editor。

- [ ] **Step 1: 写失败的 HTML 结构测试**

```python
def test_learning_assets_use_three_top_level_pages(index_html: str) -> None:
    for element_id in (
        "interfaceAssetUnreviewedPage",
        "interfaceAssetReviewedPage",
        "interfaceWorkflowLibraryPage",
        "interfaceAssetSharedEvidence",
    ):
        assert f'id="{element_id}"' in index_html
    assert "interface-workflow-review-groups" not in index_html
```

- [ ] **Step 2: 写未审核安全文案测试**

```python
def test_unreviewed_page_explains_agent_block(index_html: str) -> None:
    assert "未审核界面不会提供给 Agent 直接使用" in index_html
```

- [ ] **Step 3: 运行失败测试**

```powershell
uv run pytest tests/test_web_panel_route.py -k "three_top_level_pages or unreviewed_page_explains" -q
```

Expected: FAIL。

- [ ] **Step 4: 修改 HTML 和 CSS**

移除并排 `interfaceWorkflowReviewGroups` 和永久 `interfaceWorkflowSourceManager`。资产页使用左侧列表和右侧共享证据；流程页保留路径图在上、节点证据在下。桌面列表与证据比例为 `30% / 70%`，路径图高度使用 `clamp(300px, 38vh, 460px)`，窄屏改为单列。

- [ ] **Step 5: 修改页面切换逻辑**

```javascript
function showInterfaceAssetPage(page) {
  interfaceAssetWorkspaceState.activePage = page;
  renderInterfaceAssetWorkspace();
}
```

点击资产只更新共享证据，不自动切换流程。

- [ ] **Step 6: 运行测试**

```powershell
uv run pytest tests/test_web_panel_route.py -k "interface_workflow or three_top_level_pages" -q
node --test tests/js/learning_workflow_review.test.cjs
```

Expected: PASS。

---

### Task 5: 将“加入流程”改为资产页弹窗

**Files:**
- Modify: `app/web_panel/index.html:1690-1750`
- Modify: `app/web_panel/panel.js:10203-10470`
- Modify: `app/web_panel/panel.js:18286-18340`
- Modify: `app/web_panel/panel.css`
- Test: `tests/test_web_panel_route.py`
- Test: `tests/js/learning_workflow_review.test.cjs`

**Interfaces:**
- Produces DOM ID: `interfaceAssetAttachDialog`。
- Produces: `openInterfaceAssetAttachDialog(assetKey: string)`。
- Consumes existing workflow registry options and `addInterfaceWorkflowSource` persistence path。

- [ ] **Step 1: 写弹窗结构测试**

```python
def test_interface_assets_use_attach_dialog(index_html: str) -> None:
    assert 'id="interfaceAssetAttachDialog"' in index_html
    assert 'id="interfaceWorkflowAttachWorkflowSelect"' in index_html
    assert "interface-workflow-source-manager" not in index_html
```

- [ ] **Step 2: 写未审核提示测试**

```javascript
test("attach dialog warns when selected asset is unreviewed", () => {
  const model = review.buildAttachDialogModel(unreviewedAsset(), workflows());
  assert.equal(model.agent_usable, false);
  assert.equal(model.warning_code, "blocked_unreviewed_interface");
});
```

- [ ] **Step 3: 运行失败测试**

```powershell
uv run pytest tests/test_web_panel_route.py -k "attach_dialog" -q
node --test tests/js/learning_workflow_review.test.cjs
```

Expected: FAIL。

- [ ] **Step 4: 实现弹窗和加入后导航**

弹窗支持“仅加入节点”和“加入并连接”。前者保存节点后切换到流程页并居中节点；后者加入后打开现有 `interfaceWorkflowLinkDialog`。未审核资产显示警告，但允许保存节点。

- [ ] **Step 5: 运行测试**

```powershell
uv run pytest tests/test_web_panel_route.py -k "interface_workflow or attach_dialog" -q
node --test tests/js/learning_workflow_review.test.cjs
```

Expected: PASS。

---

### Task 6: 路径图状态颜色与混合流程状态

**Files:**
- Modify: `app/web_panel/interface_workflow_graph.js`
- Modify: `app/web_panel/panel.js`
- Modify: `app/web_panel/panel.css`
- Test: `tests/js/interface_workflow_graph.test.cjs`
- Test: `tests/test_web_panel_route.py`

**Interfaces:**
- Consumes: `review_status`, `agent_usable`, `agent_eligibility_reason`。
- Produces visual states: `reviewed`, `unreviewed`, `invalid`, `selected`, `disconnected`。
- Produces summary: `{ reviewed, unreviewed, invalid, agent_ready }`。

- [ ] **Step 1: 写图节点状态测试**

```javascript
test("workflow graph keeps review state separate from selection", () => {
  const node = graph.projectNode({ agent_usable: false, review_status: "needs_human_review" });
  assert.equal(node.review_state, "unreviewed");
  assert.equal(node.fill_token, "warning");
  assert.equal(node.selected, false);
});
```

- [ ] **Step 2: 写混合流程状态测试**

```javascript
test("mixed workflow is not agent ready", () => {
  const summary = graph.summarizeWorkflowReadiness([
    { agent_usable: true },
    { agent_usable: false },
  ]);
  assert.equal(summary.agent_ready, false);
  assert.equal(summary.unreviewed, 1);
});
```

- [ ] **Step 3: 运行失败测试**

```powershell
node --test tests/js/interface_workflow_graph.test.cjs
```

Expected: FAIL。

- [ ] **Step 4: 实现颜色和线型**

绿色、橙色、红色只表达审核状态；蓝色外圈只表达选择；未连接节点使用灰色虚线；经过未审核节点的边使用橙色虚线。点击节点保留完整图，只更新下方证据。

- [ ] **Step 5: 运行测试**

```powershell
node --test tests/js/interface_workflow_graph.test.cjs
uv run pytest tests/test_web_panel_route.py -k "interface_workflow" -q
```

Expected: PASS。

---

### Task 7: 完整回归、面板烟测与文档同步

**Files:**
- Modify: `README.md`
- Review/update: `PROJECT_SUMMARY.md`
- Review/update: `CURRENT_STATE.md`
- Review/update: `NEXT_STEPS.md`

**Interfaces:**
- Verifies browser panel, workflow registry API, Agent context boundary and existing Gate safety invariants。

- [ ] **Step 1: 运行前端测试**

```powershell
node --test tests/js/learning_workflow_review.test.cjs tests/js/interface_workflow_graph.test.cjs
```

Expected: PASS。

- [ ] **Step 2: 运行后端窄测试**

```powershell
uv run pytest tests/test_interface_workflow_review.py tests/test_web_panel_route.py -q
```

Expected: PASS。

- [ ] **Step 3: 运行安全相关回归**

```powershell
uv run pytest tests/test_reviewed_interface_memory_execution.py tests/test_execute_recognition_plan_route.py tests/test_final_submit_guard_fixtures.py -q
```

Expected: PASS；final-submit 与 Gate 断言无退化。

- [ ] **Step 4: 启动面板并执行真实 UI 烟测**

验证未审核和已审核两个大页、共享证据预览、两类资产加入流程、路径图状态颜色、节点切换、未审核 Agent 阻断，以及已审核节点仍要求实时定位与 Gate。

- [ ] **Step 5: 同步文档**

README 描述用户可见行为；状态文档记录已验证范围和限制，明确“审核通过不是执行授权”。

- [ ] **Step 6: 最终验证**

```powershell
uv run pytest tests -q
git diff --check
git diff --stat
```

Expected: 测试通过，无空白错误；不引入无关格式化。

