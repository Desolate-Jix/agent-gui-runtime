# Agent 视觉开发状态 / Agent vision implementation status

> v0.1.0-test.8：源码与隔离候选各 2025 项通过，本方 local、当前 Agent、实际 Luna 委派的单项及连续操作与清理通过；同候选独立 local、visual 与 cleanup 均已完成。首次失败、恢复与具体覆盖见验收记录。独立 API 仍仅预留接口，宿主禁用。 / Source and isolated candidate each passed 2025 checks. Main-agent local/current/actual-Luna single and continuous journeys passed; same-candidate independent local, visual and cleanup gates are complete. Initial failures and scope remain documented. External API remains interface-only with its host route disabled.

设计始于 2026-09-26；当前交付为 test.8。 / Design began 2026-09-26; current delivery is test.8.

candidate03 验收已闭合；最终交付非文档源文件保持一致，详细证据和限制见 [本版验收](../verification/TEST8_CANDIDATE_ACCEPTANCE.md)。 / Candidate03 acceptance is complete; delivered non-document sources are unchanged. See acceptance for evidence and limitations.

candidate01 根因复核：裸 `field_goal` 的模型定位与当帧 UIA 身份冲突时正确拒绝。此次修复精简回执遗漏步骤错误；已知精确名称时传 `label`，不自动把任意目标句改为精确名称。56 项回执相关测试通过，针对性检查分别为 6 项和 90 项通过；这些离线检查不冒充实机验收。 / Candidate01 conflict rejection was correct. Compact step diagnostics are fixed; supply an exact `label` when known. Receipt checks passed 56 tests; targeted runs passed 6 and 90 tests respectively. Offline checks do not substitute for live acceptance.

## 已实现的薄链路 / Implemented thin slice

- `recognition_source.py`：四种来源的配置与能力判断；未知与不支持分开；文本主 Agent 可搭配视觉委派；不自动回退，不启动模型。`eligible` 不代表连接或模型已经可用。
- `grounding_contract.py`：严格 `grounding.v1`；坐标、框、截图尺寸、请求关联、状态和候选 ID 验证；重复 JSON 键、尾部垃圾、非有限数字直接报错，不静默修复。
- `grounding_handoff.py`：会话内落盘请求、冻结意图、候选回传、读取、取消、180 秒默认失效（与动作等待无关）；首次验证 PNG 摘要；重复相同回执不重新依赖文件存在；不同 owner 不能接管请求。
- MCP 原有 `instant_submit/run` 新增四种只读 command，宿主已接入对应处理器，prepare 返回输出 JSON schema 与图像证据。未增加第二套输入器。
- 新增显式 `grounding_execute`：先落盘占用，再进入原 `execute_recognition_plan`；复核进程身份、尺寸及局部像素一致性，派发前再次采集。执行失败或结果不确定均不自动回到可重试状态。无新增风险策略，沿用现有 operator 模式；像素一致性不是语义命中或原子点击证明。
- `--recognition-source agent_current|agent_delegate` 不再要求模型目录、不配置/预热 VISTA；委派要求 `--delegate-profile`。命令来源必须与会话配置一致。API 仍明确拒绝启动，默认 local 不变。
- `external_grounding_api.py` 预留 Chat Completions JSON 图像传输、环境变量密钥引用、受限响应解析与结构化错误；未接到执行宿主。用户已明确没有独立 API，本版不要求服务商实测，不主动查找凭证。 / The reserved API transport is not host-integrated; the operator deferred provider acceptance and credential provisioning.

Source/capability selection, strict validation, persisted handoff and explicit one-click dispatch through the existing action route are implemented. Agent sources skip VISTA startup/preparation; delegation requires a profile. Source selection is session-pinned. No new risk policy is added. Region checks are not semantic-hit or atomic-input proof. Eligible is not a working-provider claim.

## 源码实验接口 / Source-only experimental commands

```json
{
  "request_id": "ground-1",
  "command": {
    "kind": "grounding_prepare",
    "request": {
      "goal": "Find the Search input",
      "configuration": {"source": "agent_current"},
      "capabilities": {"image_transport": "supported", "current_vision": "supported"}
    }
  }
}
```

先选择目标窗口；该请求采集当前图像并返回 `awaiting_grounding`、`capture_id`、`output_schema`。Agent 按返回 schema 给出结果，再以新的外层命令 ID 提交 `grounding_resolve`，request 含原 `grounding_request_id` 和 `result`。`grounding_status/cancel` 只需原 ID。外层重复命令仍沿用已有回执幂等规则。

Select a window first. Prepare returns a fresh image, correlation ID and result schema. Resolve under a new outer command ID with the original grounding ID and model result. Status/cancel use the original grounding ID; outer command deduplication remains unchanged.

**候选 ready 后 `execution_available=true`。**四个交接命令不点击；另用新外层 ID 提交 `{"kind":"grounding_execute","request":{"grounding_request_id":"ground-1"}}`。只引用冻结候选，不接受替换坐标。重复执行请求拒绝；读取原执行 ID 的结果及 before/after 图。未派发交接回执是 `action_executed=false`；执行后查询交接状态会返回执行请求 ID，可能派发时不再误报 false。效果判断仍交给 Agent，不自动重放。

**Ready candidates enable explicit execution.** Submit grounding_execute under a new outer request ID, referencing the frozen grounding ID. No replacement coordinates or replay are accepted. Read the original execution receipt and images; a subsequent status query links to that execution rather than falsely claiming no input. The Agent still judges effects. A candidate is not target-hit proof.

## 实际检查 / Executed checks

维护工作树 `.venv\Scripts\python.exe -X utf8 -m pytest -q`，以下 28 个文件合跑 **637 passed in 26.46s**（包含启动显示等待、API 协议与轻量依赖检查）：

```text
tests/test_recognition_source.py
tests/test_vision_grounding_contract.py
tests/test_grounding_handoff.py
tests/test_instant_grounding.py
tests/test_form_tab_sequence.py
tests/test_windows_form_control_reader.py
tests/test_instant_run.py
tests/test_instant_form_fill.py
tests/test_instant_read_text.py
tests/test_local_step_observation.py
tests/test_agent_grounding_target.py
tests/test_agent_grounding_execution.py
tests/test_instant_agent_startup.py
tests/test_local_step_timings.py
tests/test_local_recognition_policy.py
tests/test_local_control_target.py
tests/test_local_text_focus.py
tests/test_local_keyboard_target.py
tests/test_recognition_click_kind.py
tests/test_instant_mcp.py
tests/test_instant_desktop.py
tests/test_instant_start_cleanup_rejection.py
tests/test_post_action_recovery.py
tests/test_post_action_window_transition.py
tests/test_application_launch_discovery.py
tests/test_launched_window_close.py
tests/test_external_grounding_api.py
tests/test_agent_dependency_manifest.py
```

采用先红后绿：新模块缺失、MCP 新命令未注册，以及空配置意外回退、回执重复读取依赖变化、歧义候选不失效、缺少输出 schema、不可用路线仍截图等测试先失败，再修复通过。独立代码审查指出其中三处问题，主代理复现后修复。

Tests first failed for missing implementation and concrete regressions, then passed after repairs. A bounded independent review identified three reproducible defects. The MCP test invokes the real server/tool wrapper in-process with generated image evidence; it is not a real desktop or stdio-process acceptance test.

本批另补先红后绿：公共路由缺适配、模型预热未跳过、执行占用/重复派发、状态误报零输入、计划后画面改变、会话识别来源串用。动作测试替换系统窗口与输入边界，不点击桌面。独立审查发现后两项，主代理复现修复。

New red/green regressions cover routing, preparation, durable execution claims, misleading no-input status, post-plan scene changes and source mismatch. Action tests substitute native input/window boundaries; they do not click the desktop. Independent review identified the last two issues.

真实独立 stdio 检查：`agent_current` 4.657s、`agent_delegate` 4.250s，均初始化→ready→prepare_models 返回 model_not_required→stop，`cleanup_verified=true`、无存活宿主、无 pending。不配置模型目录，不截图、不输入、不调用委派模型。仅证明两种来源的宿主启动/协议/清理，不证明 Luna 接入、轻量依赖安装或点击准确率。首次驱动因 SDK snake_case 字段读错失败，已保存并修正；不是产品启动失败。

Two real stdio process checks passed startup/readiness/no-op model preparation/cleanup (4.657s and 4.250s). No configured model directory, screenshot, input or delegated inference. This is not live grounding or clean-environment dependency acceptance. The first driver failed on an SDK field name and was corrected with the failure retained. Evidence: `D:\AgentReviewAcceptance\20260926-agent-vision-source-02\`.

开发环境最初缺少声明依赖 `mcp==2.1.1`，造成 16 项环境失败；仅在维护虚拟环境安装该依赖后重跑。未更改发布依赖版本，未把初次环境失败改记为通过。

The declared MCP dependency was missing; 16 environment failures preceded installation into the development environment and a successful rerun. No release dependency version was changed.

## 本轮真实证据 / Live evidence

- `20260926-agent-vision-live-01`：当前 Agent 看原图，经框架完成记事本输入/撤销/关闭及 Google→地图→博物馆→换 Sky Tower→滚动/简介。6 个候选执行返回成功，另有 absent 与重复执行拒绝负例；35 份回执、24 张返回原图。不是总体准确率统计。
- `20260926-agent-vision-live-02`：Luna 首次看到新 Edge 启动过渡帧，正确返回 absent；没有点击。失败样本保留，不能把后续通过改记成首次成功。
- `20260926-agent-vision-live-03`：真实 gpt-6-luna 读原图返回三个候选；框架完成 Google 搜索框→输入搜索→地图链接→地图输入框→搜索 Auckland Museum。15 份回执、10 张返回原图，三次候选执行分别 2989.505 / 2802.172 / 2956.158ms。此耗时包含本地执行/观察，不包含 Luna 推理和调用方空档，不能称为端到端模型速度。
- 三次会话均关闭本轮窗口、`cleanup_verified=true`、宿主停止；返回图片有声明摘要的均核对一致。路径位于本机 `D:\AgentReviewAcceptance\`，各目录 `verified-summary.json` 由原始回执生成。截图不上传仓库。

Current-agent live samples cover Notepad and two Maps searches; the first delegated attempt correctly reported absent on an unusable startup frame. A subsequent real Luna-delegated session completed three grounded targets and a Museum search. Keep the first failure separately. All three sessions closed owned windows and verified host cleanup; returned-image digests were checked. These are limited source-runtime samples, not frozen-package/AionUi acceptance or population accuracy estimates. Model inference time is unmeasured.

### 首帧问题 / Startup-frame incident

1. **失败 / Failure:** 新窗口句柄可见、处于前台，但 MSS 首帧仍含启动过渡中透出的底层内容。
2. **契约 / Invariant:** 窗口身份存在不等于像素已经呈现；不能把 launch ready 当网页就绪。
3. **位置 / Fix:** 公共 `window_preparation.py` 对新启动窗口等待 500ms，等待可取消，之后重新绑定并核对完整进程身份。保留启动归属以便清理；新增 `presentation_wait_ms`、`content_ready=null` 和下一步截图提示。`grounding_handoff.py` 保留允许列表内的截图可见性、耗时和尺寸诊断。
4. **通用性 / Generality:** 所有新启动应用共享路径，不按 Google 标题或网址硬编码；不改变已有窗口和每次截图的等待。
5. **回归 / Regression:** 修复前探针首帧异常、约 323ms 有浏览器外壳、约 695ms 有页面；修复后 `20260926-capture-startup-probe-02/03/04` 三次新启动首帧均由主 Agent 看图确认目标页面，关闭/清理成功。单元覆盖等待、取消、身份变化、诊断持久化。
6. **边界 / Limitation:** 500ms 是本机复现验证的缓解，不是任意机器、应用、动画或加载完成的保证。未重写截图后端、未新增或放宽自动风险策略；不得省略看图或在空白/过渡帧上猜坐标。

The common launch path now has a cancellable 500ms presentation delay and identity recheck. Three fresh-launch probes passed after an original reproducible early-frame failure. This is an empirical mitigation, not universal readiness proof. Content readiness remains unknown, capture inspection is mandatory, and no risk-policy change was made. Handoff preserves allowlisted capture diagnostics rather than silently discarding them.

`live-01` 一次候选执行 14.177s；分项显示浏览器准备约 6.250s、截图绑定约 4.950s。该次瓶颈在浏览器准备路径，不应写成识别模型推理耗时；尚未优化。 / One earlier click took 14.177s, dominated by browser preparation/binding, not measured model inference; optimization remains pending.

## 仍须完成 / Remaining requirements

1. 扩展真实视觉样本、异常恢复、组合填写及连续验收；已有低风险样本不能代替完整范围。
2. 轻量部署脚本已通过实际安装和 stdio 验证；仍须冻结包功能闭合，不以已有单项证据代替完整验收。
3. 当前 Agent/Luna 已有实测交互；仍须冻结候选的客户端部署及独立兼容性验收。
4. 独立 API 按用户最新要求仅保留适配器、配置与 mock 协议检查；宿主路由保持禁用，不读取或要求密钥，不要求本版 live-provider/付费服务验收，也不宣称服务商兼容。
5. Codex 已完成冻结候选连续实测与清理；AionUi 同候选已回报 PARTIAL。先复核 `focus_input_not_confirmed` 原始证据并修复，再补相关验收；Agent 视觉正向因测试者无多模态能力仍未覆盖。
6. 文档/配置脚本、交付依赖闭合复核、新版本推送；完整交付核验后才执行用户要求的关机。

candidate03 验收已闭合；最终交付非文档源文件保持一致，详细证据和限制见 [本版验收](../verification/TEST8_CANDIDATE_ACCEPTANCE.md)。 / Candidate03 acceptance is complete; delivered non-document sources are unchanged. See acceptance for evidence and limitations.



## 轻量依赖实证 / Isolated lightweight evidence

`requirements/agent-runtime-win311.txt` 为 Windows/Python 3.11 的 Agent 视觉环境，不安装 PySide6、Torch、Paddle、OpenCV、NumPy 或本地 OCR/VISTA。不要用 `uv sync` 覆盖它，否则会装回项目的本地模型依赖。`setup_instant.ps1 -RecognitionSource agent_current|agent_delegate` 已接通独立 `.venv-agent` 安装与配置，local 默认行为保留。该清单不承诺本地 `read_text` OCR 或桌面审核面板可用；Agent 可以直接读取返回原图。

The manifest creates an Agent-vision environment without Qt or local model/OCR stacks. Do not overwrite it with normal `uv sync`. Source-aware setup now installs `.venv-agent` separately while preserving the local default. Local OCR/read_text and the desktop review panel are not included; the connected Agent reads image evidence.

实证目录 `D:\AgentReviewAcceptance\20260926-agent-lightweight-01`：独立 source 快照、新建 venv、`-I` 隔离启动、无原工作树导入。43 个实际安装分发，venv 文件总长 78,131,209 字节（约 74.5 MiB，不含基础 Python、源码、数据和模型；不是最终安装包大小）。Agent-current/delegate 零输入 stdio 检查分别 6.750s / 5.079s，model_not_required，清理通过。

Isolated source/venv with `-I` passed current/delegate stdio startup and cleanup (6.750s/5.079s). Its 43 installed distributions total about 74.5 MiB of venv files, excluding base Python, source and data; this is not a release-size claim.

同一干净环境通过框架完成新记事本：原图定位→点击→输入固定测试句→撤销→确认空白→关闭本轮窗口→宿主清理。点击 2880.186ms、输入 223.846ms、撤销 68.720ms、关窗 61.468ms，均为回执 `command_wall_ms`，不含 Agent 看图/调度时间。8 份回执、5 张返回原图；摘要核对一致，`cleanup_verified=true`、`host_alive=false`、pending 为空。第一份定位截图因文档读取期间过期，主动新建定位请求，不复用旧候选。未触及已有文件。

The same isolated environment completed a real framework-driven Notepad click/type/undo/close journey, with inspected images and cleanup. Executor timings exclude Agent review/scheduling. Eight receipts and five returned originals are retained with digest checks. An initial capture expired while documentation was read; a new request replaced it rather than using stale coordinates. No existing files were changed.

`verified-summary.json` 保存依赖清单、逐步耗时和清理核验；当前只覆盖这个轻量输入路径，不替代表单、滚动、异常恢复、委派客户端和同包 AionUi 验收。API 的 24 项测试使用模拟 HTTP transport；配置与限制见 [预留 API](EXTERNAL_VISION_API.md)。

The summary records package inventory, per-step timings and cleanup. This sample does not replace full forms/recovery/delegation or same-package AionUi acceptance. The reserved API's 24 protocol tests use mock HTTP transport, not a real provider.

## 安装闭环与批次缺口 / Setup closure and batching gap

2026-09-26 最新全套 `.venv\Scripts\python.exe -X utf8 -m pytest -q`：**1951 passed in 38.75s**。安装/配置测试先因缺 RecognitionSource 失败，再修复；交付清单先因漏开发文档失败，再修复。包仍只收录文档，不夹带同目录截图或本机 JSON。

Latest complete source suite: **1951 passed in 38.75s**. Red/green checks proved missing setup routing and omitted linked docs before repair. Delivery retains Markdown docs without colocated images/private JSON.

`20260926-agent-setup-01` 使用隔离源码、真实 uv 安装 Python 3.11.15 和 43 个轻量依赖，生成管理员入口配置，不改客户端全局配置。来源 agent_current/agent_delegate 的真实 stdio 自检均覆盖工具发现、非法参数后同会话恢复、查询、重复请求回执、停止和重新连接读取原回执，清理通过；不调用视觉模型、不进行输入、不自动确认 UAC。`--delegate-profile vision-luna` 只是本轮客户端配置名，不证明在自检中调用了 Luna。

The isolated setup installed Python 3.11.15 and 43 lightweight dependencies via real uv, then generated elevated-entry configuration without changing client registration. Both sources passed real stdio discovery, validation recovery, deduplication, cleanup and receipt recovery on reconnect. These checks made no GUI input/model calls and did not approve UAC.

首次安装的 uv 尝试创建全局 Python 命令并报告既有非托管文件冲突；没有强制覆盖。公共脚本已改 `uv python install 3.11 --no-bin --no-registry`，重跑成功；原脚本和前后状态保留于验收目录，避免把首次告警抹去。文档注明直接依赖固定、传递依赖未完整锁定。

Initial setup warned about an existing unmanaged global Python command; no force replacement occurred. Setup now skips global executable/registry registration and reran successfully. The initial script is retained. Direct dependencies are pinned; transitive dependencies are not fully locked.

**新确认的未闭合项：** 当前 `form_fill` 文本聚焦进入 `input_sequence`，再调用 `execute_local_step`；后者除 grounding_target 外仍准备本地识别。控件操作也使用此路径，`read_text` 明确调用本地 OCR。当前 Agent 的独立 grounding 命令不会自动替换这些内部调用。具名字段已有 UIA 主路径和读回，但不能据此断言完全无模型。需要公共来源路由和可恢复的识别交接，保留现有组合执行、UIA 读回和单次输入语义；不能用只支持单击的轻量包冒充完整交付。

**Confirmed integration gap:** form input/control operations still reach the old local-recognition preparation path; read_text explicitly invokes local OCR. Standalone grounding does not automatically replace these nested calls. Existing UIA fast paths/readback do not prove model-free batching. Complete common source routing and resumable grounding while retaining batch behavior and one-shot input semantics before full delivery.
