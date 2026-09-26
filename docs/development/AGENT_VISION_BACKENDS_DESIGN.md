# 可切换视觉识别设计 / Switchable visual recognition design

> v0.1.0-test.8：源码与隔离候选各 2025 项通过，本方 local、当前 Agent、实际 Luna 委派的单项及连续操作与清理通过；同候选独立 local、visual 与 cleanup 均已完成。首次失败、恢复与具体覆盖见验收记录。独立 API 仍仅预留接口，宿主禁用。 / Source and isolated candidate each passed 2025 checks. Main-agent local/current/actual-Luna single and continuous journeys passed; same-candidate independent local, visual and cleanup gates are complete. Initial failures and scope remain documented. External API remains interface-only with its host route disabled.

日期 / Date: 2026-09-26
candidate03 验收已闭合；最终交付非文档源文件保持一致，详细证据和限制见 [本版验收](../verification/TEST8_CANDIDATE_ACCEPTANCE.md)。 / Candidate03 acceptance is complete; delivered non-document sources are unchanged. See acceptance for evidence and limitations.

## 1. 目标与边界 / Goals and boundaries

让接入的 Agent 提供视觉理解，框架提供可靠的截图、定位协议、键鼠执行与证据。用户可以不部署本地视觉模型，也可以保留 VISTA；主 Agent 和识别模型独立选择。例如 Astra 决策、Luna 定位，不必把整个会话换成 Luna。

The connected agent supplies visual intelligence; the framework supplies observation, grounding contracts, input and evidence. Local VISTA becomes optional. Planner and recognizer can differ: Astra may plan while Luna grounds targets without changing the main conversation model.

本次不重写执行器、不开发学习模式、不新增自动风险审批系统、不自动读取 Agent 密钥，也不保证任意客户端都能切换子模型。不支持多模态时，只停用不可用的视觉路线，不停用窗口管理、截图、UIA 读取和已有可用操作。

This does not replace the executor, implement learning, add a policy-approval system, extract client credentials or promise model selection in every client. An unavailable visual route must not disable unrelated runtime capabilities.

## 2. 三个角色、四种来源 / Three roles, four sources

| 角色 / Role | 职责 / Responsibility | 默认归属 / Default owner |
|---|---|---|
| 决策者 / Planner | 理解任务、决定目标与下一步 / Understand the task and choose goals | 接入的主 Agent / Connected main agent |
| 定位者 / Grounder | 从当前图像返回目标、框、点击点或歧义 / Ground the target or report ambiguity | 用户选择的视觉路线 / Selected visual route |
| 结果判断者 / Reviewer | 看操作前后证据，判断任务效果 / Judge effects from before/after evidence | 主 Agent；可显式委派 / Main agent; explicit delegation optional |

| 来源 / Source | 谁调用模型 / Invocation owner | 适用情况 / Use case |
|---|---|---|
| `agent_current` | 当前 Agent 客户端 / Current agent client | 主 Agent 能看图，不额外配 API / Image-capable main agent; no separate API setup |
| `agent_delegate` | 客户端指定的视觉子 Agent / Client-selected visual worker | Astra 决策、Luna 识别；客户端必须支持 / Separate planner and recognizer; requires client support |
| `external_api` | 框架调用用户配置的 API / Framework calls configured API | 客户端不能委派，或需要独立部署 / No client delegation or independent deployment |
| `local` | 现有本地模型运行时 / Existing local runtime | 离线、已有 VISTA 用户 / Offline and existing VISTA users |

**本版 API 边界（2026-09-26 用户确认） / Release API boundary (operator confirmed 2026-09-26):** 只保留适配器、配置和 mock 协议检查；`external_api` 宿主路由禁用，不读取或要求密钥，不要求 live-provider/付费 API 验收。该路线未作为本版已支持功能。 / Reserve the adapter, configuration and mock protocol checks only. Keep the `external_api` host route disabled, do not read or require keys, and do not require live-provider/paid API acceptance. This route is not a shipped capability.

**UIA 优先不是第五种模型。** 它是公共定位策略：可唯一读取的当前控件优先使用 UIA；必须看图时才调用选定视觉来源。OCR 也不是强制依赖，不能为了“无需本地模型”路线又自动加载一套本地 OCR 模型。

**UIA-first is a shared strategy, not a fifth model.** Use a unique current UIA target where available; invoke the selected visual route when needed. Local OCR must remain optional rather than silently reintroducing model dependencies.

## 3. 总体结构 / Architecture

```text
Main Agent / Astra
   │ task, explicit action intent
   ▼
MCP observation + recognition request
   │ current capture + target description + request ID
   ├── agent_current  ── caller sees image
   ├── agent_delegate ── client dispatches image to Luna
   ├── external_api   ── configured provider adapter
   └── local          ── existing VISTA provider
   │
   ▼
Common GroundingResult + capture/coordinate validation
   ▼
Existing execute_recognition_plan / combo executor
   ▼
SendInput + before/after evidence
   ▼
Agent review: success / failure / uncertain
```

识别来源只更换“坐标和候选从哪里来”，不增加绕过现有动作入口的第二套点击器。文本输入、滚动、快捷键、文件选择、组合填写继续复用已有实现。

The source changes where candidates originate, not the input backend. Existing text, scroll, key, file-picker and batch-form implementations remain shared.

## 4. Astra 主 Agent、Luna 识别怎么接 / Astra planner with Luna grounding

### 4.1 客户端可委派 / Client supports delegation

1. Astra 决定目标，例如“定位搜索框”。框架返回当前截图及精简定位任务。
2. 客户端把同一原图或带明确变换的裁剪图交给指定 Luna 子 Agent；不把整个会话、个人资料和无关历史复制过去。
3. Luna 只返回结构化识别结果，不操作鼠标，不自行继续任务。
4. 调用方把结果提交回原请求；公共执行器校验后执行明确请求的动作。
5. 返回前后图。默认 Astra 判断结果；也可配置 Luna 先给出判断，Astra 负责下一步。

The client delegates a bounded image-grounding request to Luna, submits its result to the original request, and retains exclusive input ownership. Workers cannot click or independently continue the task. Evidence review may be delegated explicitly; planning remains with Astra.

**框架不能仅凭 MCP 配置把任何 Agent 的主模型切成 Luna。** 子 Agent 启动、模型选择和配额归客户端管理。普通 MCP 工具返回图像，不等于客户端支持模型委派，也不能假设客户端实现了 MCP sampling。

**The framework cannot change an arbitrary agent's model through MCP configuration.** Delegation, model selection and quota belong to the client. Image transport does not imply delegation or MCP sampling support.

### 4.2 客户端不能委派 / Client cannot delegate

用户显式选择：继续用当前多模态 Agent，或配置独立视觉 API，或用本地模型。不能自动借用隐藏密钥，也不能默默改用更贵的主模型或外部收费服务。

Offer explicit alternatives: current multimodal agent, separately configured API or local provider. Never extract hidden credentials or silently switch to a paid or more expensive route.

## 5. 能力发现与自动停用 / Capability detection and disabling

会话握手记录 `image_transport`、`image_understanding`、`structured_output`、`delegation`、`model_selection`，每项取 `supported / unsupported / unknown`，并记录来源是客户端声明还是实测。

Track image transport/understanding, structured output, delegation and model selection separately as supported, unsupported or unknown, with declaration/probe provenance.

| 情况 / Condition | 行为 / Behavior |
|---|---|
| 确认当前 Agent 不支持图像 / Explicitly unsupported | 会话内停用 `agent_current`，显示原因；其他路线不受影响 / Disable that session route only |
| 主 Agent 纯文本，但 Luna 子 Agent 能看图 / Text planner with visual worker | 允许 `agent_delegate`；检查实际接收图像的模型 / Validate the actual visual worker |
| 能力未知 / Unknown | 标记待验证；用无敏感信息的小图做传输与协议探测 / Optional nonsensitive transport/schema probe |
| 超时、限流、401、网络断开 / Timeout, rate limit, auth, network | 分别报告，不能当作“不支持多模态” / Report the actual failure, not lack of vision |
| 图像能传但输出不合规 / Image delivered, malformed result | 返回结构化错误，不执行；允许有界的纯识别重试 / Reject action; bounded recognition-only retry is possible |

小图探测仅证明链路与格式，不证明真实按钮识别准确率。没有统一可靠的 MCP 接口能自动知道所有客户端的多模态能力，必须支持客户端声明和人工配置。自动停用只影响当前会话，不能悄悄删除用户偏好。

A probe proves transport and format, not real-world accuracy. There is no universally reliable client-capability enumeration through ordinary MCP tools. Support declarations and explicit configuration; session disabling must preserve preferences.

## 6. 配置与用户入口 / Configuration and user experience

设置提供：识别来源、模型/委派名称、连接测试、能力状态、结果判断者；高级配置收起。切换仅在两次动作之间生效，在途请求固定配置版本。失败必须显示当前实际来源，不能界面选 Luna 而后台仍加载 VISTA。

Expose source, model/delegate, connection test, capability status and reviewer; keep advanced options collapsed. Pin each in-flight request to a configuration revision and switch only between actions. Display the actual route and failure reason.

以下为**拟议配置，不是当前可用字段** / **Proposed configuration, not existing executable settings**:

```json
{
  "recognition": {
    "source": "agent_delegate",
    "delegate_profile": "vision-luna",
    "local_model_autostart": false,
    "fallback_policy": "explicit_only"
  },
  "review": {"source": "agent_current"},
  "client_profiles": {
    "vision-luna": {
      "requested_model": "gpt-6-luna",
      "dispatch_owner": "agent_client"
    }
  }
}
```

模型名须与用户所在客户端或服务商的实时可用 ID 核对。配置里的名称不构成模型实际身份的证明；回执分别记录请求模型、客户端声明模型和服务商实际返回标识，未知就保留未知。

Validate model identifiers against the actual client/provider. Requested, client-declared and provider-returned model identities are different evidence; do not infer identity from a display label.

外部 API 配置包含协议适配器、`base_url`、`model`、`api_key_env`、超时、响应长度上限和并发上限。先支持一个经验证的图像 API 协议，再按适配器扩展；不宣称所有“兼容 API”都可用。密钥只从显式配置的环境变量或凭证设施读取，日志与诊断不得输出密钥。

External API settings specify a validated protocol adapter, endpoint, model, key reference, timeouts, output limits and concurrency. Compatibility requires testing; credentials stay outside reports.

## 7. MCP 交接与状态机 / MCP handoff and state machine

**不能让一个 MCP 调用一直等当前 Agent 回答它自己。** Agent 路线必须异步交接，否则可能形成死锁。

**Do not block an MCP call waiting for the calling agent to answer that same call.** Use an explicit asynchronous handoff.

```text
created → capture_ready → awaiting_grounding → grounding_ready
        → executing → awaiting_agent_review → completed
                       ↘ evidence_incomplete
any pre-input state → failed / cancelled / expired
```

- 首次识别请求返回 `needs_agent_grounding`、原图引用、目标、坐标约定、请求 ID 和失效条件；不占住模型准备线程或键鼠锁。
- 调用方查看/委派图像，再提交同一 ID 的 `GroundingResult`。可把“提交候选＋执行已明确请求的动作”合成一次往返，不强制增加一次模型思考。
- 优先扩展已有 MCP command 与 `execute_recognition_plan`，不为了每个来源增添一套重复工具。精确字段在实施时版本化，旧客户端不应被要求发送新字段。
- 候选只有显式执行请求才触发输入；重复提交同一执行 ID 返回既有回执，不再次点击。
- 识别结果迟到、取消后回调、不同连接伪用 ID、窗口已变，都返回明确状态，不能重新激活已结束操作。
- 客户端断线按现有会话所有权规则收尾；重新连接只能按受支持方式读取旧回执，不能假定未收到回执等于未执行。

Return a pending request with image reference and expiry conditions, release locks, and accept the correlated result later. Reuse existing commands where possible, version extensions, deduplicate execution, reject late/cancelled/stale results and preserve session cleanup semantics. A lost response never proves an action did not occur.

本地与外部 API 路线在内部产出同一种结果，无需向 Agent 暴露模型进程细节。自动重试仅限尚未派发输入的识别请求，并有界、留痕；输入一旦派发，交给 Agent 看证据决定下一步。

Local/API routes produce the same contract internally. Recognition-only retries may be bounded and logged before input; dispatched actions are never automatically replayed.

## 8. 公共识别契约 / Common grounding contract

拟议成功示例 / Proposed example:

```json
{
  "schema_version": "grounding.v1",
  "request_id": "grounding-example-001",
  "capture_id": "capture-example-001",
  "status": "found",
  "coordinate_space": "capture_image_pixels",
  "image_size": {"width": 1920, "height": 1080},
  "candidates": [{
    "id": "candidate-1",
    "label": "Search",
    "bbox": {"x": 200, "y": 180, "width": 360, "height": 40},
    "click_point": {"x": 380, "y": 200},
    "evidence_source": "agent_visual",
    "confidence": null
  }],
  "selected_candidate_id": "candidate-1"
}
```

公共运行时从自身捕获记录补充截图摘要、窗口身份、尺寸、时间、裁剪变换和配置版本；不能信任模型伪造这些元数据。输出严格验证必填字段、有限数字、边界和请求关联。状态包括 `found / absent / ambiguous / unsupported / error`；不存在目标时不能硬造坐标，多候选时返回列表和可消歧说明。

The runtime owns capture hashes, target identity, dimensions, timestamps, transforms and configuration revision. Validate schema, finite bounds and request correlation. Absence must not fabricate coordinates; ambiguity returns candidates and actionable clarification.

### 坐标与新鲜度 / Coordinates and freshness

- 原图像素为统一坐标系，屏幕坐标仅由框架使用已记录的窗口变换计算。
- 裁剪或缩放必须携带变换；例如 `full_x = crop_x + display_x / scale`。变换不明确则不能执行。
- 模型点击点周围人工扩出的框只能标记 `synthetic`，不能当成独立命中证据；模型置信度不是校准后的准确率。
- 保存 `capture_id`、窗口 HWND/PID 身份与生命周期、尺寸、视口及来源；滚动、弹窗或布局变化后按现有新鲜度契约重新观察。
- 不要求两张全屏像素完全相同：光标闪烁不应让所有操作失败。复用现有目标区域/窗口一致性检查，不借此新增一层过严的全局像素闸门。
- 同图可批量识别多个字段，减少往返；不代表后续动作永远可复用旧坐标。输入触发布局变化时中断剩余批次并返回当前状态。

Canonicalize to original-image pixels with explicit transforms. Synthetic boxes are not independent target evidence, and confidence is not accuracy. Preserve capture/window provenance, reassess changed layouts, tolerate irrelevant pixel changes, and invalidate stale batch targets when necessary.

## 9. 执行与结果判断 / Execution and outcome review

前后图必须稳定绑定同一动作 ID；后续截图不能覆盖之前的 `after`。如果需要即时帧和稳定帧，明确命名 `after_immediate`、`after_settled`，并指明哪一帧用于 Agent 判断与差异计算。

Bind before/after evidence immutably to the action. Distinguish immediate and settled frames and declare the frame used for review and diff computation.

框架回报 `input_dispatched`、实际使用坐标、来源、失败信息和证据引用；**不得把“光标移动了”“像素变化了”写成任务成功**。判断前 `verified=null`，缺图标记 `evidence_incomplete`，不伪装已完成。

Report dispatch, actual coordinates, provenance, errors and evidence. Cursor movement or changed pixels do not establish task success. Keep verification null pending review; missing evidence stays incomplete.

Agent 判断记录 `success / failure / uncertain`、判断者、证据 ID 与简短依据。确定性的字段读回可由 UIA 提供，但只证明对应字段，不证明整项任务完成。结果判断不自动授权下一步，也不触发无条件重试。

Record the reviewing agent, evidence IDs and concise rationale. UIA readback can prove a field value, not completion of an entire task. Review is not automatic permission to replay or continue.

## 10. 体积、资源与隐私 / Footprint, resources and privacy

纯 Agent/API 路线不启动 VISTA，不下载权重、不预热本地模型。轻量依赖与本地模型依赖分组；真实移除 torch/transformers 等依赖前必须完成导入闭合验证，不能再发生发布包缺少活跃依赖的问题。

Agent/API routes must not load or warm VISTA. Separate lightweight and local-model dependencies only after isolated entrypoint validation; do not remove active dependencies from delivery bundles.

模型进程只能按框架所有权清理，不停止用户的 AI 助手或其他应用模型。云端视觉减少框架本地模型显存占用，不等于用户整台电脑零显存，也不保证比本地更快。

Clean up only framework-owned model processes. Cloud vision removes framework-local model loading, not all GPU use, and does not guarantee lower latency.

截图按用户选定路线传输，切换到新外部服务需明确配置；不自动发送整段历史和无关屏幕。原图按需读取、避免 Base64 进入普通文本回执；缓存和日志复用现有保留策略，不另存重复大文件。外部发送不能被“本地截图已获得”默认为所有服务商授权。

Use the explicitly chosen transport, minimize history and image duplication, and keep image bytes out of ordinary text receipts. A locally captured image is not blanket consent to send it to unrelated providers.

## 11. 故障、可观测性与速度 / Failures, observability and latency

统一错误至少包含 `code`、`stage`、`request_id`、实际来源、是否已经输入、可恢复方式。建议错误：`vision_capability_unknown`、`vision_unsupported`、`delegate_unavailable`、`provider_auth_failed`、`provider_timeout`、`grounding_schema_invalid`、`grounding_ambiguous`、`capture_stale`、`evidence_incomplete`。

Errors identify stage, request, actual source, input-dispatch state and recovery. Separate unsupported capability, authentication, timeout, malformed output, ambiguity, stale capture and missing evidence.

耗时由框架/客户端实际时钟记录，不让模型填写“开始时间”。拆分截图、图像传输、客户端排队、模型请求、解析、输入、事后观察及调用方空档；跨进程记录时间基准，不能简单相减未同步的时钟。嵌套 span 不重复相加，缺失时间标记未知。

Instrument clocks in runtime/client code, not model text. Separate capture, transport, queueing, inference request, parsing, execution, observation and caller gaps. Avoid cross-clock subtraction and nested-span double counting; unknown remains unknown.

加速顺序：优先 UIA 和现有组合动作；一次发送必要截图与多个确定目标；精简结构化结果；保持同一连接与可复用会话；不每步同时调用 Astra 和 Luna 看同一张图。异常时再让主 Agent 深入复核。费用仅记录实际服务商 usage，可得时换算，不把 Codex 套餐额度当作 API 账单。

Prefer UIA, batching, compact results and session reuse. Do not require both planner and grounder to inspect every image. Escalate exceptions; record actual provider usage without conflating subscription quotas and API billing.

现有静态试验只证明两张图上的可行性：Sol/Luna 均通过 11 个可见目标＋1 个不存在目标的人工判据，但 Luna 原始格式出错、模型自报计时无效。不能据此声称通用准确率、速度优势或已经接入。

The two-image Sol/Luna probe demonstrates feasibility only. Both met 12 manual criteria, but Luna's original output format and self-reported timing failed. It does not establish general accuracy, speed or runtime integration.

## 12. 代码复用与实施位置 / Reuse and implementation locations

| 已有位置 / Existing path | 拟议改动 / Proposed change |
|---|---|
| `app/vision/base.py`, `schemas.py` | 复用接口思想，补统一轻量 grounding 契约；不强制点选生成整页语义 / Add lightweight grounding without mandatory full-scene analysis |
| `app/vision/configuration.py`, `factory.py` | 来源、能力与配置版本；保留旧 local 配置 / Source/capability/config revision, backward compatibility |
| `app/vision/api_provider.py` | 当前是占位实现，另行实现并验证真实 API；不能宣称已有 / Replace stub only with tested adapter |
| `app/instant_mcp.py` | 异步识别交接、能力状态、原 ID 回执；扩展旧命令 / Async handoff, capability status, correlated receipts |
| `app/desktop_review/local_direct_step.py` | 本地模型准备按来源执行；Agent/API 不得进入本地预热 / Conditional preparation, no local prewarm for Agent/API |
| `app/api/action.py` | 所有来源回到公共动作入口 / Converge sources on existing action path |
| `app/desktop_review/input_sequence.py`, `form_fill.py` | 保持组合执行；接入通用定位结果 / Reuse batch execution |
| `app/core/input_controller.py`, `screenshot.py`, `window_manager.py` | 复用真实输入、截图、窗口变换；不另造执行器 / Reuse input, capture and window transforms |

当前正式配置加载器仍拒绝 `api` 模式，API provider 仍是 stub；源码 Agent 候选单步已跳过本地模型准备，local 路线保持原行为。因此“增加一个下拉菜单”不足以完成此设计，必须同时接通配置、依赖、调度和实际执行路径。

Configuration still rejects API mode and the API provider remains a stub. Agent-candidate steps now skip local preparation; local steps retain it. A selector alone is not implementation; configuration, dependencies, scheduling and execution all need integration.

## 13. 分阶段交付 / Delivery stages

1. **统一协议＋当前 Agent 视觉**：能力声明、原图、候选回传、公共执行、前后证据；无本地模型环境可完成低风险操作。保留旧 local 行为。
2. **指定子 Agent**：客户端适配层实现 Astra→Luna；不支持委派的客户端明确提示，而不是悄悄调用主模型。只有识别工作并发，键鼠仍单一所有者。
3. **独立 API**：实现一个经过验证的协议适配器、密钥引用、错误和计费观测；配置脚本与文档完整。未完成前明确显示“未支持”。
4. **完整验收与交付**：轻量依赖闭合、组合操作回归、连续实机、AionUi 同候选复验；累积到功能闭合后集中打包。

Deliver current-agent grounding first, then client-controlled delegation, a verified external API adapter, and isolated delivery validation. Preserve local compatibility throughout; do not package every small edit.

学习模式以后保存与识别来源无关的界面记忆、锚点和局部图像，不把 Luna/VISTA 的私有输出固化成执行前提。本轮不实现或发布学习模式。

Future learning should store provider-neutral interfaces, anchors and image patches rather than model-specific output. Learning is outside this delivery scope.

## 14. 验收标准 / Acceptance criteria

### 契约与离线 / Contract and offline

- 不支持/未知/纯文本主 Agent＋视觉子 Agent 三种能力组合处理正确。
- 原图、缩放、裁剪、DPI、窗口移动、过期候选、重复回包、乱序、取消和断线有覆盖。
- 非 JSON、尾部垃圾、坐标越界、歧义、模型返回错误身份不能进入输入路径。
- 本地/API/Agent 来源共享动作证据格式，不冒充任务已验证；快照不被后续截图覆盖。
- Agent-only 隔离包无需本地模型依赖即可导入和执行受支持入口；原 local 包回归不退化。

Test capability combinations; coordinate transforms; stale, duplicate, late and cancelled results; malformed outputs; immutable evidence; isolated lightweight dependency closure and local-provider compatibility.

### 实机与连续使用 / Live and continuous use

使用全新低风险真实网站和新记事本：搜索、连续填写、展开后选择下拉项、滚动后定位、小按钮、中英文、空目标、弹窗、异常恢复和关窗清理。先 Codex 单项，再同一会话连续任务；全部通过后才交 AionUi 验收同一冻结候选。保留首次失败，不用重跑成功覆盖它。

Use fresh real sites and Notepad: search, forms, expanded dropdowns, scrolling, small controls, bilingual labels, absent targets, dialogs, recovery and cleanup. Codex single and continuous tests precede AionUi acceptance of the same frozen candidate. Preserve first failures.

比较同组任务的首次成功率、错误点击、恢复率、完整收尾、冷/热启动、端到端 p50/p95、识别调用次数和实际费用。小样本先报逐项结果与分母；累积至少 100 次定位机会并覆盖多场景后才报告探索性分位数，不把两张图的命中率宣传为产品准确率。故障注入只在隔离环境，不用付款、删除或最终提交测试。

Compare first-attempt success, misclicks, recovery, cleanup, cold/warm latency, calls and cost on matched tasks. Report small samples individually with denominators; use at least 100 grounding opportunities across scenarios for exploratory percentiles, not a claim of universal accuracy. Fault injection stays isolated; exclude consequential submissions and destructive tasks.

**发布门槛 / Release gate:** 无未解决的错误派发、证据串图、重复输入或漏包阻断；能力与限制真实标明；关键流程单项和连续通过，独立验收完成。未验证的客户端/服务商不列为已支持。

No unresolved wrong dispatch, evidence mix-up, duplicate input or missing-dependency blockers; truthful capability documentation; verified key single/continuous flows and independent acceptance. Untested clients/providers must not be advertised as supported.

## 15. 本轮交付状态 / This design's status

本文最初为设计交付。历史 candidate01 的源码与隔离包各 2010 项、283 个模块及 715 项清单已核对；该阶段待验描述已由当前 candidate03 验收状态替代。用户明确没有独立 API，本版仅保留适配器、配置与 mock 协议，宿主路线禁用，无在线服务商兼容性结论，不以付费 API 验收为发布前提。

This began as a design record. Historical candidate01 passed 2010 source/bundle checks with 283 module origins and 715 manifest entries; its pending-stage notes are superseded by current candidate03 acceptance. The operator deferred API use: reserve adapter/config/mock checks, keep the host route disabled and make no live-provider compatibility claim. Paid API acceptance is not a release requirement.
