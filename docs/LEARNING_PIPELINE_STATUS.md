# 学习接入状态：Omni + GUIActor

更新：2026-09-06。范围仅为 `codex/omni-guiactor-learning`；不是全项目统一或生产验收完成报告。

**后续主目录状态**：用户已批准收拢工作树，代码现已合入 `D:/agent-gui-runtime` 的 `codex/replay-v2`。主目录新验证、四个原件的取舍及尚未实现的恢复边界见 [工作树合并记录](WORKTREE_INTEGRATION.md)。下文是原实验任务的历史证据；其中相对产物路径归属来源工作树，不能当作主目录已生成同一批结果。

**清理证据补充限定**：主目录普通 Omni provider receipt 为 `clean`，记录的 owned PID 当前已不存在；更严格的 process-scope observation 为 `indeterminate`，旧来源批次抽查也有同一状态。历史“清理通过”不应扩称为完整进程域证明。主目录本次真实运行在 GUIActor 显存准入处停止，审核/保存/重载尚未重新走完；详细阶段与原始失败见上述合并记录。

## 本地合并检查（2026-09-06）

用户已另行要求检查并尝试合并工作树。主目录 `codex/replay-v2@5510e78c` 是本树基线 `499c1beb` 的祖先，合并会包含 310 个既有依赖提交；主目录四个未跟踪同名文件须先核对并保留，不得强制覆盖。合并前源树固定离线集合重新通过 252 Python + 28 JavaScript；这不是对全部历史提交的重新验收。

Git 暂存后检出发现冻结 catalog 被通用 LF 规则改变字节，新增真实文件 SHA 回归先复现失败；采用与旧 gate 相同的精确文件 CRLF 属性，保留原 `bb09975c…` 身份，不修改冻结数据或旧报告。该修复只影响 Git 检出，不放松任何模型、坐标或动作门禁。原 105 条真实推理证据仍留在 `D:/agent-gui-runtime/.worktrees/omni-guiactor-learning/artifacts/learning-selection-acceptance/`，不得当作合并后主目录的新推理或跨根目录恢复。

修复后的暂存快照通过 `git checkout-index` 单独检出，再实际运行固定离线命令，结果为 **253 Python + 28 JavaScript 通过**；新增一项冻结目录字节回归。主目录四个冲突原件与另外一个独有测试已逐字节备份到 `D:/agent-gui-runtime/artifacts/worktree-merge/20260906/target-before/`，清单为同级 `before.json`。两份 benchmark 原件包含不同 runtime-port 接口，未证明与源树等价；不得擅自覆盖或把备份当作已合并。

## 最终交付入口

本轮实验接入回归门槛已通过。最终本地产物为 `artifacts/learning-selection-acceptance/final-r2-delivery/REPORT.md`、`summary.json`、`paired-results.jsonl`（35 个逐例三臂转换）和 `cleanup.json`；全部 105 条原始模型框图在 `artifacts/learning-selection-acceptance/visual-r2-final/index.html`，导出时重新校验 sealed trial 和评分，0 incomplete / 0 invalid。

最后重新核验 105 份 Omni sealed clean receipt，以及 GUIActor/VISTA/面板共 190 个 PID+创建时间身份：无同一 owned 进程残留，8767 无监听。全部 8 个弃权框图和三个既有面板例子已由 Codex 可见审阅；不是用户本人最终确认。文件清理债务单独保留：误建但未使用的本 worktree `.venv` 删除被策略阻止，没有把它算成已删除。下文保留早期失败和 r3/r4 历史，避免覆盖证据。

## 本轮真实闭环

`已验证静态 capture → 真实 Omni → 真实 GUIActor → WorkflowService → 既有审核 API → 模拟修订 → 学习区域消费者 → 保存 → 新 Python 进程重载` 已在一个固定公开样例中运行成功。

- 样例：`screenspot-v2-web-01`，目标 `delete the 'article' tag for searching`。
- 实际 Omni 产生 56 个候选；GUIActor 原始点约 `[486.313,686.009]`，关联唯一候选，未调用精修。
- 原始模型语义仍为 missing，分数仍为 null。不能把定位成功宣传成完整语义学习。
- 未补语义保存返回 `blocked_missing_semantics`，不生成可编译路径。
- 自动化验收模拟了补框/中文语义修订；学习消费者读到了区域事实；新进程重载与保存结果相同，原始 model_proposal 未改变。
- 这次修订不是用户本人确认；证据中明确 `automated_review_simulation=true`、`user_confirmed=false`。没有回填模型准确率。
- 没有制造状态或动作：graph.states/action_templates 仍为空，所有结果非授权。
- 最后通过可见面板实际修改名称、点“仅保存草稿”、刷新并重新加载；新进程再次核对 3 条追加记录和中文语义。仍是自动化模拟审核，不是用户确认。
- 框图已实际导出并目视检查：蓝色为候选，红色为模型选中候选的当前审核框。红框为模拟缩边后的 `[473,666,517,714]`，模型原框 `[472,665,518,715]` 保持不变。

### 真实精修补充：r4

`full-web-01-r4-always` 已实际运行 Omni → GUIActor → VISTA → 既有审核/学习 → 保存 → 新进程重载。仍是同一个固定样例，不扩称为三例或 35 项验收。

- GUIActor 原始点 `[486.31303239627687,686.0091656726725]`；VISTA 原始输出 `[193, 400]`，原框 floor/ceil 裁剪后回映射 `[481,685]`，严格在原框及 ROI 内。没有覆盖原始点，没有填造分数。
- 本次 `always` 明确要求精修；几何触发为 false。`conditional` 初始规则为最近框边距占相应轴长 ≤ 10%，版本 `selection_edge_margin_trigger_v1`，在 35 项验收前冻结，不读取 gold，也不宣称阈值最优或语义置信度。
- VISTA 的真实模型分片、当前源码、原始响应与精确 owned tree 清理均有记录；本次端到端约 92.422 秒，包含冷加载，不是模型温推理延迟。
- r4 `review-roundtrip/verification.json` 确认缺语义拒编译、模拟补框/语义进入区域学习、新进程投影相等。没有虚构状态/动作，没有用户最终确认。
- 可见面板已加载 r4 保存结果，显示原始点与精修点，并确认“候选框数量 56 / 已具备语义的学习区域 1 / 状态 0 / 动作模板 0”。分数为“未提供”，不是低分或补零。
- 旧 manual/precise 摘要现在由复验后的投影重算：manual edits=1、region_count=1、candidate_count=56。旧缓存摘要即使是零也不会覆盖当前审核事实。

r4 原始草稿为 `artifacts/learning-runs/hybrid-selection-review/trial_b82935f763d00a10036bc75c79ef6b80be0e936a24e0e54ecf62d52adecfc60c.json`；模拟审核结果位于 `artifacts/learning-draft-review/trial_b82935f763d00a10036bc75c79ef6b80be0e936a24e0e54ecf62d52adecfc60c_b82935f763/reviewed_template_candidate.json`。

### 完整固定集 actual no-action：`integration-20260906-r2`

已顺序完成已批准既有固定 35 目标的 `never` / `conditional` / `always` 三臂，共 105 条 actual 记录；报告为 `artifacts/learning-selection-acceptance/integration-20260906-r2/acceptance-report-4cf62835eee44a448eeb60f751ba371c.json`。

- 三臂各为 **27 correct / 0 wrong / 8 abstained**；fixed25 各为 19 / 0 / 6，public10 各为 8 / 0 / 2。
- 原有 26 个 correct 全部保留；fixed25 `case-001-target-05` 是唯一记录的 abstained→correct 增益；没有 offset regression。
- VISTA 调用为 never 0、conditional 1、always 27；全部 requested 均 validated。conditional 的实际 public web-03 边距为 `0.0633665 < 0.1`，原点 `[460.558,1157.689]` 映射精修点 `[451,1150]`。
- 105/105 source identity 未变、无 evidence errors、owned cleanup 均为 true。模型存储运行前后均为 30,782,251,353 bytes，低于 32,212,254,720-byte 上限。
- cold p50 秒数分别为 never 68.962、conditional 62.182、always 78.651；p95 分别为 76.087、69.454、86.011。未测 warm/model-only VRAM，且固定臂顺序不支持因果速度结论。
- `review-r2-web01-always/verification.json` 另核验既有 API 的模拟审核→区域消费者→保存→新进程重载；缺语义负例仍阻断、raw proposal 不变、`user_confirmed=false`。可见面板检查了 selected/unbound/reviewed 三例及目标、双点和人工标签显示；面板 PID 36696 已停止。

### 可核验产物

成功运行目录：`artifacts/learning-selection-actual/full-web-01-r3/`。

- `request.json`、`omni-result.json`：实际调用与候选父证据。
- `gui-actor/result.json` 及 raw UTF-8 traces：实际选择、当前源码身份、资源预检及退出证明。
- `selection-result.json`、`result.json`：经过本次 WorkflowService 的选择和草稿路径。
- `review-roundtrip/loaded.json`、`pending-save.json`、`reviewed-save.json`、`reloaded.json`、`fresh-process-projection.json`、`verification.json`：既有 API 和跨进程闭环。
- `overlay-refresh/verification.json`：导出框图像素、新进程与原始投影不变检查。
- `visible-panel-roundtrip/verification.json`、`save-trace.json`、`fresh-process-projection.json`：最终可见面板保存和新进程核对；此前失败响应保留为 `ui-save-failure.json`。
- 原始草稿：`artifacts/learning-runs/hybrid-selection-review/trial_a79c971f837755143d846c66dfe9087f4983e3990e011e6530bdb17b4b126aa3.json`。模型原始提议可单独查看，不受模拟修订覆盖。

## 统一的协议与边界

| 接缝 | 约定 |
|---|---|
| 捕获身份 | capture_id / image SHA / image_size / coordinate_space / run_id / revision 逐层校验 |
| 静态与实时 | static 协议显式无 window_binding、无 UIA/OCR；旧 live v1 仍严格要求真实证据 |
| 选择 | 原生 normalized top-1 转 capture pixels，只接受同 capture 唯一 active 候选；无效 top-1 不试 top-2 |
| 分数与语义 | 定位 source_score 不等于语义置信度；未提供保留 null，不补零、空字符串或假状态 |
| 公开加载 | `hybrid_review_projection` / `hybrid_review_projection_ref`，按 contract_version 区分兼容版本 |
| 公开修订 | `hybrid_review_decisions` / `expected_hybrid_review_projection_ref`；追加 ledger，不覆盖模型提议 |
| 显示与保存 | 框图从同一审核投影派生，不重复存 regions；selection 面板不再夹带旧 manual_edit/operations/bbox_updates |
| 保存竞争 | 版本对比 + 跨进程锁；过期保存明确冲突，不覆盖其他审核者的新修订 |
| 真实来源 | actual_execution 仅由服务器内部真实 runner 持有；客户端 payload 的 actual 标签不自证成功 |
| 大整数 | create_time_ns 持久化为无损十进制字符串，PID 保持整数；不放松全局 JCS 校验 |
| 精修 | original / refined 点分开；精修保留 ROI、原框、坐标变换、模型来源和当前源码清理父证据；失败不回填成功点 |
| 诊断计数 | candidate_count 与语义学习 region_count 分开；公开 UI 和旧摘要均由同一复验投影派生 |
| 学习消费者 | 缺语义拒编译；人工区域事实进入已有消费者；状态、动作与发布仍不能虚构 |

源码按 capture / adapter / task / review / persistence 职责局部整理，复用现有 WorkflowService、UEI、面板和学习消费者；没有大规模搬目录、第二套数据库或通用编排平台。

## 本轮发现并修复的真实问题

1. GUIActor 把 safetensors 分片路径当成 from_pretrained 目录：改为已核验分片所在 checkpoint 目录。
2. Omni 注入的资产路径没传到工作进程：由受信配置传递固定 child 环境变量；不复制模型，不接受客户端路径覆盖。
3. 静态公开截图不满足 live capture 的 UIA/窗口条件：新增有明确区别的静态协议，不制造“空成功”或假 PID。
4. 模型失败/超时/中断、坏 UTF-8 trace 未持久化 cleanup：现在保存失败阶段、原字节 hash、精确进程退出或未启动状态，再报告失败。
5. 真实纳秒整数在 JCS 保存/重载中不兼容：固定十进制字符串并增加大整数跨进程回归。
6. 保存后框图只有原图：导出读取了已去重的 durable regions。修复在共用审核保存层，从当前 selection 投影派生显示框；像素回归证明红框和蓝框存在，原始提议不变。这不是针对 Wikipedia 的特殊规则，其他截图同样走该投影；未引入执行点或授权。
7. 可见面板保存报 `manual edit target region was not found`：前端同发新 ledger 和旧 manual_edit，违反单一修订入口。修复在共用 panel 的版本分派，selection 只发统一 ledger，隐藏不适用的旧表单；旧模式仍显示。Node 执行真实 patch 生成函数 → FastAPI 保存/重载的跨语言回归先复现同一失败后通过，实际面板重试也通过；无站点特化，安全边界未放松。
8. 固定集静态 capture 已支持，但 Omni 候选消费者仍保留仅接受 ScreenSpot 的另一份字段规则：首轮 batch 因此在候选投影阶段停止。消费者现复用同一静态 context schema，不再维护互相漂移的 dataset/revision 规则。原实际 Omni receipt 复验为 clean；同一旧真实输出的修复后回放得到 15 个候选，未重写旧失败或计作新推理。固定字段到消费者的负/正回归已补齐，新的 r2 首目标 never 实际通过。

失败原件保留：`gui-actor-web-01-r1` 加载失败；`full-web-01-r1` 在 Omni 清理后遭 GPU 空闲不足拦截；`full-web-01-r2` 暴露大整数重载失败。不要将 r2 草稿当成当前成功交付。没有重写旧 seal、删除失败或导入旧选型报告冒充推理。

## 运行与验证

在隔离目录执行，使用已有环境，无安装或新 venv：

```powershell
D:/agent-gui-runtime/.venv/Scripts/python.exe scripts/check_learning_integration.py --suite fast
D:/agent-gui-runtime/.venv/Scripts/python.exe scripts/check_learning_integration.py --suite integration
```

最终固定离线命令 `D:/agent-gui-runtime/.venv/Scripts/python.exe scripts/check_learning_integration.py --suite integration` 实际通过 **252 Python + 28 JavaScript**，日志为 `artifacts/learning-selection-acceptance/final-r2-offline.log`。这是明确集合的离线检查，不是全仓测试、CI 或泛化证明。

额外运行 `python -m pytest -q tests/test_learning_selection_roundtrip.py tests/test_learning_selection_save_integrity.py tests/test_learning_selection_public_flow.py tests/test_learning_draft_review.py` 得到 98 passed / 1 failed。失败是 `test_default_learning_draft_demo_artifacts_load` 所需的 `artifacts/learning-draft-review/branch_hub_2584f138b7/` 旧演示资产在隔离树不存在；该用例在 HEAD 基线中已存在，不是本次新增。没有 skip/xfail 或制造演示资产来报绿，固定集合覆盖范围未因此改变。

实际入口：
```powershell
D:/agent-gui-runtime/.venv/Scripts/python.exe scripts/run_learning_selection_actual.py --case-json artifacts/learning-selection-actual/inputs/screenspot-v2-web-01.json --manifest artifacts/static-manifests/9f61e5c6e9b4af27df217c2a8a33d2e650cfc500e94cbede617365ba16cbb32b.json --out artifacts/learning-selection-actual/new-run
```

out 必须是新目录；已知公共十例的 manifest SHA、目标、图像 SHA 和尺寸由 `configs/learning_selection_public_cases.json` 固定。本轮不会借参数引入未知留出集。
模型启动无需再次审批。GUIActor 空闲显存准入仍为 10240 MiB；Omni 完全退出后才启动 GUIActor。CLI 和该 worktree 的面板进程不可同时持有 WorkflowStore；先停止自己启动的面板，再运行 CLI，不能删除锁或结束他人服务。

审阅复现：启动隔离面板 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8767`，在“高级诊断 → 学习结果来源”填上述原始 trial 路径，点“加载学习结果 → Edit boxes”。若要继续编辑，请加载同一输出目录的 `reviewed_template_candidate.json` 最新版本，而非过期 trial；过期保存会报 CAS 冲突。模拟修订脚本 `scripts/verify_learning_selection_review.py` 适用于新 trial 的首次验收；已存在修订不能拿旧版本重复覆盖。

## 尚未完成与边界

- 完整页面/状态/动作语义、正式软件流程编译发布、用户最终确认、真实 Windows 捕获/操作验收均未运行或未证明；区域学习就绪不等于完整工作流就绪。
- 生产 stage start 继续阻断，incumbent 默认不变；原实验验收阶段未 commit、push、合并、默认切换或新增 CI。后续用户另行要求的本地提交/合并检查见上文；离线通过数不等于全仓 clean。
- 未访问 Unique holdout，未新增留出集；固定 35 的结果不能扩称为 unseen generalization。
- 历史失败原件和旧 `integration-20260906-r1` 停止记录保留，不被 r2 覆盖。

批量命令（省略 `--limit` 才运行全部已批准目标；同一输出目录仅在源码/输入身份不变且逐项证据复验通过时恢复）：
```powershell
D:/agent-gui-runtime/.venv/Scripts/python.exe scripts/run_learning_selection_acceptance.py --config configs/benchmarks/learning_selection_acceptance_v1.json --no-action --out artifacts/learning-selection-acceptance/integration-20260906-r2
```
报告采用追加文件，不覆盖失败；source/catalog 漂移或未核验的残缺目录会明确停止。任一已运行模型清理不明确，不继续启动下一模型。固定 25 使用独立 `portfolio_hybrid_v1_1` 静态身份，不能冒充 ScreenSpot 或实时窗口；生成的 capture manifest 仅含图片身份，不含旧预测或 gold。

## 资源与限制

主库与原模型 worktree 未修改。模型测试存储上限为 30 GiB（32,212,254,720 bytes），不是显存大小；实际模型资产复用 E 盘，未下载/复制。

本任务曾误用 uv 创建隔离树内的 .venv，未使用它。对该目录的精确清理请求被工具策略阻止，目录仍保留；没有绕过阻止，也未触碰主环境或他人资源。所有正式命令使用主库已有 Python。

该历史未使用 worktree `.venv` 当前仍为 829,096,142 bytes、18,282 files；路径和无 reparse 已复核，但精确原生 PowerShell 清理再次被策略阻止。它是保留文件清理债务，不是模型进程清理失败。

codegraph 当前可连接，但索引属于主目录，明确提示不是本隔离 worktree；新文件采用有界 rg/直接读取。外部 Chrome 桥不可用，本次本地面板可见验证临时使用内置浏览器；没有对外部 ChatGPT 发送项目数据。模型真实退出和面板状态以产物/实际观察为准，不凭文档标题或测试替身自证。

为运行 CLI 验收，已停止本任务先前保留的面板 PID 33456、36144 和最终可见检查 PID 36696。`127.0.0.1:8767` 当前不作为常驻服务保留；打开的浏览器页面可能仍显示已加载内容。不要删除 WorkflowStore 锁或结束他人的服务来并行运行。
