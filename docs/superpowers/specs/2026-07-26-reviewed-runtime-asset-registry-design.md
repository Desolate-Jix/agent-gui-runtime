# Reviewed Runtime Asset Registry 设计

## 目标

把已经经过人工修订和 promotion preflight 的学习产物发布为不可变、可版本化、可回滚、可在程序重启后重新加载的 `Reviewed Runtime Asset`。

本阶段只建立 Runtime 可消费的资产与注册表边界，不授权点击、填写、提交或 Runtime PathGraph 执行。后续 State Match 和 Target Resolver 只能读取该资产，不能修改它。

## 当前基础与缺口

现有链路已经提供：

```text
Learning Draft
  -> Human Review Patch
  -> Assisted Template Review Package
  -> Human Review Record
  -> Assisted Template Asset Candidate
  -> Assisted Template Graph Draft
  -> Promotion Preflight
  -> Audited Promotion Request
```

`assisted_template_audited_promotion_request_v1` 明确停留在审计请求预览，不执行 promotion。当前没有：

- 不可变 Runtime 资产对象；
- 持久化资产注册表；
- active version 指针；
- 回滚；
- 重启后的 checksum 校验和重新加载；
- 稳定语义 `element_id` 合同。

## 方案选择

### 采用：内容寻址对象 + 原子注册表

- 每个资产版本写入独立 JSON 对象，文件名包含内容 SHA-256。
- 已存在的对象不能覆盖；相同内容发布幂等复用。
- 注册表保存 `asset_id -> active_version_id` 和版本历史。
- 发布与回滚只原子更新注册表，不修改旧对象。
- 加载时同时验证注册表、对象路径、对象 SHA-256 和内部版本身份。

该方案比“直接覆盖一个模板文件”更适合审计、回滚和重启恢复，也不会把 CorrectionMemory 当成 Runtime 资产。

### 不采用：数据库或 Git 作为第一版存储

- 当前项目已经使用原子 JSON 持久化 workflow state 和 worker journal。
- SQLite 会增加迁移和锁语义，但第一版并不需要查询能力。
- Git 适合开发版本控制，不适合作为运行时资产激活协议。

## 存储结构

```text
runtime_state/
  reviewed-runtime-assets/
    registry.json
    objects/
      <asset_id>/
        <version_id>.json
```

`registry.json` 使用临时文件、flush、fsync 和 atomic replace 写入。对象文件先完整写入并校验，再提交注册表指针。

## Reviewed Runtime Asset 合同

```json
{
  "contract_version": "reviewed_runtime_asset_v1",
  "asset_id": "seek_job_results",
  "version_id": "rra_<sha256-prefix>",
  "content_sha256": "<sha256>",
  "created_at": "<iso8601>",
  "source_tracking": "human_reviewed",
  "source_lineage": {
    "audited_promotion_request_path": "...",
    "audited_promotion_request_sha256": "...",
    "asset_candidate_path": "...",
    "asset_candidate_sha256": "...",
    "graph_draft_path": "...",
    "graph_draft_sha256": "...",
    "screenshot_path": "...",
    "screenshot_sha256": "..."
  },
  "surface_match": {
    "adapter_id": "browser_job_search",
    "required_evidence": [],
    "forbidden_app_name_only_match": true
  },
  "states": [],
  "elements": [
    {
      "element_id": "job_results.search_input",
      "semantic_role": "search_input",
      "parent_element_id": "job_results.search_toolbar",
      "historical_bbox": [0, 0, 0, 0],
      "locator_evidence": {
        "uia": [],
        "ocr": [],
        "visual": [],
        "relative_geometry": []
      },
      "action_semantics": ["fill_field"],
      "danger_class": "non_destructive"
    }
  ],
  "transitions": [],
  "safety_policy": {
    "artifact_is_authorization": false,
    "execute_binding_enabled": false,
    "real_action_requires_gate": true,
    "final_submit_forbidden": true
  }
}
```

### 身份规则

- `asset_id` 是人工确认的稳定界面族标识，不从应用名称自动生成。
- `element_id` 是稳定语义身份，不能包含当前截图坐标。
- 同一资产内 `element_id` 必须唯一。
- `parent_element_id` 必须引用同一资产中的 element，且不能形成环。
- `historical_bbox` 只作为学习和相对布局证据，不能直接作为真实点击坐标。
- locator evidence 可以为空，但空证据的 element 不能被 Target Resolver 判为可执行。

## 发布合同

发布输入必须是 `assisted_template_audited_promotion_request_v1`，并满足：

1. request、preflight、asset candidate 和 graph draft 文件存在；
2. 所有声明 SHA-256 与实际文件一致；
3. preflight 状态为 `ready_for_audited_runtime_promotion_review`；
4. 人工 review record 有 accepted item；
5. graph draft 通过人工资产检查；
6. 调用方显式提供 `asset_id` 和人工批准记录；
7. 不包含普通点击化的 final submit / send / confirm / payment action；
8. 资产仍保持 `artifact_is_authorization=false` 和 `execute_binding_enabled=false`。

发布失败不得创建 active version。对象写入成功但注册表提交失败时，对象可以保留为未引用内容对象，下一次相同发布可幂等复用。

## 注册表合同

```json
{
  "contract_version": "reviewed_runtime_asset_registry_v1",
  "revision": 3,
  "assets": {
    "seek_job_results": {
      "active_version_id": "rra_abcd1234",
      "versions": [
        {
          "version_id": "rra_abcd1234",
          "object_path": "runtime_state/reviewed-runtime-assets/objects/seek_job_results/rra_abcd1234.json",
          "content_sha256": "...",
          "status": "active",
          "created_at": "...",
          "supersedes_version_id": ""
        }
      ]
    }
  }
}
```

- 每次发布或回滚递增 `revision`。
- 一个资产最多一个 active version。
- 回滚只把 active pointer 指向已有且校验通过的版本。
- 被回滚版本保留，不删除。
- registry 中的重复版本 ID、路径越界、checksum 不一致或多个 active 状态会使加载 fail closed。

## Runtime 读取边界

本阶段提供：

- `publish_reviewed_runtime_asset(...)`
- `load_reviewed_runtime_asset(asset_id, version_id=None)`
- `list_reviewed_runtime_assets()`
- `rollback_reviewed_runtime_asset(asset_id, version_id)`

返回的资产是深拷贝或重新读取结果，调用方不能修改磁盘对象。

后续 State Match 的输入是当前 Observe 证据和只读资产；输出是 `runtime_interface_context_v1`。后续 Target Resolver 的输入是 `element_id + current evidence`，不能读取 `historical_bbox` 后直接点击。

## API 与面板边界

第一版增加后端 API：

- `POST /panel/publish_reviewed_runtime_asset`
- `GET /panel/reviewed_runtime_assets`
- `POST /panel/rollback_reviewed_runtime_asset`

发布必须是人工显式命令，不在 Save Review 后自动触发。面板保存人工修订后可以显示“可发布”状态和版本列表，但不会自动激活资产。

## 错误处理

- 路径越界、SHA 不一致、旧 request、无 accepted item、无稳定 element ID：拒绝发布。
- registry 损坏：拒绝加载全部资产并返回明确错误，不静默重建。
- active object 丢失或 checksum 变化：该资产不可用，不回退到旧版本。
- 回滚目标不存在或损坏：拒绝回滚，保留当前 active version。
- 幂等重复发布：返回已有 version，不增加 registry revision。

## 测试与验收

### 单元合同

- 发布生成不可变对象和 registry active version。
- 相同输入重复发布幂等。
- 不同修订生成新版本并保留旧版本。
- 回滚改变 active pointer，不改对象文件。
- 新 Registry 实例能够在“重启”后加载 active version。
- checksum mismatch、路径越界、重复 element ID、parent 环和 unsafe action 均 fail closed。
- `historical_bbox` 不出现在任何可执行 click point 字段。

### API 合同

- 发布、列表和回滚返回结构化 `APIResponse`。
- 缺少人工批准或 promotion preflight 不通过时拒绝。
- API 不返回 Execute 授权。

### 本阶段完成标准

1. 一份人工审查链 fixture 可以发布为版本 1；
2. 修订后可以发布版本 2；
3. 新进程实例默认加载版本 2；
4. 回滚后新进程实例加载版本 1；
5. 两个版本的文件和 SHA 保持不变；
6. 没有真实点击、填写、提交或 Runtime PathGraph promotion。

## 后续独立阶段

1. `Current Observe + State Match -> Runtime Interface Context`
2. `semantic element_id -> Runtime Target Resolver`
3. `Resolver candidate -> Gate -> Operation -> Trace -> post-action Observe`
4. SEEK 重复任务闭环
5. 第二应用族复用验证

