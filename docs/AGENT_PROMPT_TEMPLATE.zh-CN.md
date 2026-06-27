# 发给其他 Agent 的提示词模板

复制下面这一段给其他 agent。把尖括号里的内容替换成你的具体任务。

```text
你现在要使用我的 Windows GUI 自动化框架 `agent-gui-runtime` 完成任务。

项目位置：
D:\agent-gui-runtime

本地运行面板：
http://127.0.0.1:8000/panel

本地 API：
http://127.0.0.1:8000

你的任务：
<在这里写任务，例如：打开 SEEK 首页，找两个适合 Wenqing Ji 的软件/AI/自动化相关岗位，只记录岗位信息和判断，不申请>

候选人/用户资料：
<在这里写资料路径或摘要，例如：D:\资料\CV\candidate_profile_wenqingji_personal.json；D:\资料\CV 目录里的 CV 和签证文件是个人资料来源>

必须先阅读这些文件：
1. D:\agent-gui-runtime\AGENT_ONBOARDING.md
2. D:\agent-gui-runtime\AGENT_API_WORKFLOW.md
3. D:\agent-gui-runtime\docs\AGENT_EXECUTION_PROTOCOL.md
4. D:\agent-gui-runtime\docs\AGENT_LEARN_MODE_TUTORIAL.md
5. D:\agent-gui-runtime\docs\AGENT_TRACE_DEBUG_GUIDE.md

如果任务涉及 SEEK，还必须阅读：
D:\agent-gui-runtime\skills\seek-high-precision\SKILL.md

核心规则：
- 你是上层 agent，负责拆解任务和决定下一步。
- 这个 runtime 是执行内核，只负责截图、识别、定位、Gate、安全执行、验证和 trace。
- Execute Mode 必须一小步一小步调用；每次只执行一个低层动作，然后根据返回结果决定下一步。
- 不允许直接用模型坐标或旧坐标点击。
- 不允许绕过 `pre_click_decision_v1`。
- 不允许点击最终提交、购买、删除、发送、保存更改等不可逆动作，除非用户明确批准那个具体 live action。
- 失败时先看 trace / screenshot / OCR / candidate / gate / verification，先修主路径，不要先加兜底。
- 每次真实点击、滚动、输入都要留下 trace。

推荐执行循环：
1. 确认 runtime 健康状态。
2. 打开或绑定目标外部窗口。优先用 `/apps/open` 打开新测试窗口；默认保持 `maximize_after_open=true`，让首张截图覆盖更多页面信息。
3. 截图并确认窗口正确。
4. 如果已有 PathGraph，调用 `/execute/available_actions` 获取可用动作。
5. 如果没有 PathGraph，先走 Learn Fast / Learn Deep 或当前页面 observe。
6. 选择一个安全动作。
7. 如果你已经从 Observe / PathGraph / 专用 skill 得到目标卡片或结果行的 bbox/click point，必须作为 `metadata.seeded_candidate_v1` 传给 Execute，让 VISTA 只校验小 ROI；不要让模型重新看整屏。
8. 先 dry-run / preview，检查 overlay、bbox、click point、OCR、VISTA ROI policy 和 Gate。
9. 通过后只执行一个动作。
10. 读取 post-action verification 和 trace。
11. 记录结果，再决定下一步。
12. 遇到歧义、错窗口、滚错容器、重复无进展、登录/captcha/权限、最终提交风险时停止并报告。

任务完成时，请返回：
- 你绑定了哪个窗口/页面。
- 你执行了哪些步骤。
- 每一步的重要 trace / screenshot 路径。
- 抽取到的记录、判断和证据。
- 哪些动作没有执行以及原因。
- 安全计数，特别是 `final_submissions=0`。
- 如果失败，指出失败层：窗口、截图、OCR、模型 JSON、候选、Gate、坐标、滚动容器、验证或权限。

不要声称完成，除非 trace 或验证能证明完成。
```

## Trace 摘要要求

如果你需要把 trace 发给 ChatGPT、Codex、Claude 或其他上层 agent 分析，不要直接粘贴完整 JSON。先在 `D:\agent-gui-runtime` 运行：

```powershell
uv run python scripts\agent_trace_digest.py "TRACE_JSON_PATH" --format text
```

需要机器可读交接时运行：

```powershell
uv run python scripts\agent_trace_digest.py "TRACE_JSON_PATH" --format json
```

把 `agent_trace_digest_v1`、关键截图路径、overlay 路径和你的下一步判断发给上层 agent。只有当 digest 指向某个具体 raw section 时，才打开完整 trace 的对应片段。
