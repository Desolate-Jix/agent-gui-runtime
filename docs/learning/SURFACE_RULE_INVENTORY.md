# 学习模式 Surface Rule Inventory

更新时间：2026-07-22

## 目的

本清单冻结当前真实流程中的页面类规则，避免继续在 `two_stage.py` 和 API 中追加无法审计的应用特例。Surface Adapter 只能提供布局先验、排除区和验证规则；deterministic root partition 仍负责候选几何，精准定位仍负责原子控件坐标，Gate 仍负责安全判断。

## 规则层级

| 层级 | 允许内容 | 不允许内容 |
|---|---|---|
| Common hard rule | 坐标空间、父子包含、候选 freshness、危险动作阻断、最终提交阻断 | 按应用名改变安全阈值 |
| Surface Adapter | 布局先验、语义分组建议、排除区、验证规则 | 最终 bbox、click point、执行授权 |
| Approved human rule | 有截图 checksum、适用范围、反例和回归证据的修正规则 | 未审核即进入生产 |
| Model review | 删除明显错误候选、指出缺失、提出修复建议 | 绕过 integrity gate 或直接授权点击 |

## 当前规则审计

| 家族 | 当前位置 | 当前状态 | 迁移决定 |
|---|---|---|---|
| deterministic root partition | `app/learn/recognition/root_partition.py` | 生产权威 Stage1 | 保留为 common geometry layer |
| Stage1 gate / containment | `app/learn/recognition/stage1_audit.py`, `two_stage.py` | 生产安全与结构校验 | 保留为 common hard rule |
| browser chrome Execute 阻断 | `app/api/vision.py::_point_in_browser_chrome` | Execute 安全路径正在使用 | 不迁移、不放松 |
| browser chrome Learn candidate 过滤 | `surface_adapters.py`, `two_stage.py`, `app/api/vision.py::_learn_target_candidate_is_browser_chrome` | 已消费 BrowserAdapter 显式 evidence | 不再使用应用名或顶部固定比例；保留显式系统外壳硬规则 |
| browser chrome legacy Stage1 校准 | `two_stage.py::_stage1_region_localization` 及 clamp/partition helpers | 仅旧报告路径；主两阶段流程使用 authoritative root partition | 标记 legacy duplicate，暂不删除 |
| browser evidence granularity / Stage1.5 | `two_stage.py::_items_have_browser_chrome_evidence` 的多个调用点 | 主流程仍有使用 | 迁入 BrowserAdapter validator 后再收敛 |
| chat conversation / message / composer | `two_stage.py` 的 Stage1.5、message parent、conversation row、image message helpers | 主流程正在使用，规则分散 | 迁入 ChatAdapter 的先验与验证入口，几何 helper 暂保留 |
| media card / visual parent | `two_stage.py` 的 media card synthesis、card row、partial card helpers | 主流程正在使用，规则分散 | 迁入 MediaPlayerAdapter 的启用条件与验证入口，视觉几何 helper 暂保留 |
| model interface classification | `app/learn/recognition/interface_classification.py` | 模型类别可选择 class profile，但缺少统一 Adapter 证据门 | Adapter 必须增加结构证据门和 Generic 回退 |
| panel browser app IDs | `app/web_panel/panel.js::BROWSER_APP_IDS` | UI 绑定辅助 | 不得作为识别几何或最终 Adapter 的唯一证据 |

## 新增 Adapter 合同

`learning_surface_adapter_decision_v1` 当前包含：

- `adapter_id`: `browser` / `chat` / `media_player` / `generic`
- `selection_evidence`: 可审计证据，不包含原始 PII 值
- `layout_priors`: 只读布局先验
- `excluded_zones`: 语义排除区 ID，不是 bbox
- `validation_rules`: 后续结构验证规则 ID
- `final_geometry_allowed=false`
- `execute_binding_enabled=false`
- `artifact_is_authorization=false`

应用名只记录为弱证据，不能单独激活专用 Adapter。模型类别必须有对应的 `structure_signals`；冲突或缺失时退回 GenericAdapter。BrowserAdapter 还要求明确的地址栏/标签页证据，或 `browser_chrome` 语义区与其内部 URL 文本互相佐证。单个模型语义框不能激活 BrowserAdapter。

## 基线与防污染

固定回归集使用 `tests/fixtures/deterministic_first_recognition_manifest_v1.json` 中的历史界面。它目前覆盖 Apple Music、Steam、WhatsApp、WeChat 等已知资产。两周验收前还需要建立至少六个陌生界面 holdout，并为每个界面保存：

1. 原始截图；
2. Stage1 根分区图；
3. 最终融合图；
4. trace 与 screenshot checksum；
5. Surface Adapter decision；
6. 人工修改前后差异。

新增规则必须同时跑历史界面和 holdout。只改善单一应用、但使其他界面退化的规则不得进入 active。

2026-07-22 已冻结第一版六 case Adapter holdout：`tests/fixtures/learning_surface_adapter_holdout_manifest_v1.json`。它包含 QQ 新状态、GitHub Desktop、Calculator、NVIDIA Overlay、Bilibili 新状态和 Apple Music 新状态；所有 trace 与 screenshot 都有 SHA-256。固定复跑命令：

```powershell
uv run python scripts\run_surface_adapter_benchmark.py `
  --manifest tests\fixtures\learning_surface_adapter_holdout_manifest_v1.json `
  --out logs\benchmarks\surface_adapter_holdout_20260722 `
  --json
```

本轮还发现 File Explorer 的原子证据曾被旧布局层标记成 `browser_chrome`。Adapter 现在用已验证的 `file_browser + file_or_folder_rows` 作为冲突证据，拒绝 BrowserAdapter 并退回 Generic；这不是应用名白名单。BrowserAdapter 的排除范围由 `excluded_item_ids` 固定到原子证据，`surface_adapter_application` 明确记录 `fixed_height_boundary_used=false` 和 `final_geometry_changed=false`。

## 当前限制

- BrowserAdapter 已接管 Learning Mode 的 browser-chrome 原子候选排除；旧 Stage1 几何 helpers 仍作为未调用的 legacy 代码保留。
- Chat/Media 内容策略已经迁入 Surface Adapter。Browser 是宿主 Adapter，Chat/Media 是内容 Adapter；同一页面可以形成组合链，避免浏览器外壳覆盖内容类型。Stage2 仍复用原有几何 helper，但启用条件由已验证的内容 Adapter policy 提供。回归测试明确覆盖“应用名本身不能启用专用 Adapter”和“Media policy 必须到达真实 Stage2 输出”；当前相关回归为 `257 passed`，全仓为 `1859 passed`。
- 当前没有宣称陌生界面识别稳定，也没有总准确率。
- 人工框编辑器和 CorrectionMemory 候选记录已经接入保存流程；生命周期已实现，但当前没有默认激活规则。只有证据 checksum 有效、完成回归、人工批准并明确激活的规则才能被生产读取。
- Active CorrectionMemory 目前只作为非几何建议参与真实面板流程；不会复用旧 bbox、生成 click point 或改变 Gate。多界面真实面板验收仍待后续 checkpoint 完成。
