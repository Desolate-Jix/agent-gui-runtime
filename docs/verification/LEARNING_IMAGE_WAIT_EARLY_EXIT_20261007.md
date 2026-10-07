# 图像等待优化证据 / Image wait evidence

2026-10-07，维护源码 `codex/dev-workflow-editor`。本轮保持项目截图、共同动作门禁、原请求与不可变程序；没有使用原生Computer Use、构建安装器或发布。用户随后要求保留当前等待设置并准备发布，停止进一步速度优化。 / Maintained source only; preserve project capture, gated actions, original tickets and immutable programs. No native Computer Use, installer build or publication. Further speed tuning is deferred at the user's request.

已审核图像步骤通过共同 `_command` 编译 `observation_wait_ms=0`。图像检查约100ms间隔轮询，两秒是发起新截图的预算，成功立即退出；歧义、身份/SHA/几何错误立即交原Agent审核。普通执行、无图像规则及steps_only保留原等待；已开始的同步截图可能超过预算。 / Reviewed image steps use shared compilation and bounded early completion; failures retain the original review route. Other wait defaults remain, and synchronous captures already started may finish after the budget.

## 实测 / Live cases

| 同一新会话中的案例 / Case | 完整两步流程 / Full flow | 结果 / Result |
|---|---:|---|
| 正常图像1 / Image1 | 5.475s | completed、Open/Back各一次 / one each |
| 正常图像2 / Image2 | 5.651s | completed、Open/Back各一次 / one each |
| 正常图像3 / Image3 | 5.775s | completed、Open/Back各一次 / one each |
| 延迟配置1200ms / Delayed | 6.910s | 两步各6次观察，前5次不匹配、末次匹配 / six polls per step |
| Agent审核对照 / Agent control | 68.301s | 两次Sol审核；含调用方和外部审核等待 / includes orchestration and review waiting |
| 点击不跳转 / Blocked transition | 28.256s | 仅一次Open，17次观察均拒绝；原pending交Sol判失败，无重放 / one click, rejected then original-ticket review |

五个正例共10次真实输入，均返回HOME，pending/wait/active_command为空；负例失败是预期结果。四个图像正例无需Agent结果审核。正常图像观察13.35–16.46ms，动作后的零额外等待截图约8–14ms；延迟观察634–637ms。延迟1200ms是夹具配置，没有独立状态转换时间戳，不能称全部1200ms发生在图像观察内。 / Five positives close cleanly; the negative fails as expected. Normal image observations take13.35–16.46ms; delayed observations take634–637ms. The configured delay has no independent transition timestamp.

正常流程中位5.6506744s，比此前另一全新批次图像流程中位9.883916s下降42.8296%。这是同类自有Qt窗口的小样本前后诊断，非同冻结配对因果证明、通用准确率或安装版收益。Agent68s不能当纯推理耗时；完整模型调用/token未知。 / Limited fresh-cohort before/after evidence shows42.8% shorter wall time. It is not a general benchmark, accuracy claim, installer result or pure model-inference measurement.

## 首次失败与修复 / First failure and correction

1. **失败 / Failure:** c04首轮在任何输入前以 `workflow_target_compiled_command_mismatch` 拒绝，事件为空，不能把1.724s计为速度成功。
2. **根合同 / Invariant:** 票据、目标绑定、恢复和benchmark必须从同一有效步骤重编完整且一致的命令。prepare单独追加等待字段破坏一致性。
3. **共同修复 / Shared fix:** 等待字段移到 `_command`；steps_only只在复制体移除图像配置，原程序不变；benchmark除客户端视觉能力外逐字段核对，篡改/删除等待字段拒绝。
4. **通用性 / Generality:** 修复所有该工作流命令消费者，不添加测试应用特例或fallback。
5. **回归 / Regression:** 真实MemoryWorkspace/recipe的绑定、selection、recovery和benchmark RED拒绝记录保留；相关最终15文件 **269 passed in23.78s，Exit0**，覆盖点击、填写及滚动的策略编译和只读轮询、取消、错误拒绝。中间运行与子Agent范围重叠，不相加计数。
6. **安全 / Safety:** 输入门禁、窗口身份、当前截图和单次派发保留；旧失败请求未重派，不新增最终提交权限。

English: the first candidate rejected before input because prepare appended a field outside shared compilation. Moving the field into the common compiler restored exact binding/recovery/measurement contracts; tampering remains rejected. Preserve the first failure and original requests.

## 原件与边界 / Originals and limits

本地证据根：`.superpowers/sdd/2026-10-07-image-wait-early-exit`。新教学库由本轮真实Open/Back生成；source-freeze02固定14个生产/计量文件，c05使用新连接复用本轮库。原c04、训练调用方错误、RED及中间失败不改写。 / Fresh teaching produced this round's library; a new connection tested the14-source freeze. Earlier failures remain unchanged.

- `backend/main-regression03-final.txt`：最终269项命令与完整输出。
- `c05-*-result.json`、`bridge-02/{requests,responses}`及新session原回执、图像观察：六项结果。
- `main-timing-summary.json`：分层计时复算。
- `independent-audit/c05-independent-audit.json`及supplement：独立只读审计，8个成功图像证明从留存PNG重算；中间轮询图按实际留存范围核对，未宣称全图独立复验。
- `bridge-02/closed.json`：cleanup_verified=true、host_alive=false、pending_ids=[]；`fixture-01/closed.json`：exit0。

尚未验证最新安装包、外部软件、跨设备、真实API服务商识别准确率或每次稳定。下一步按[发布缺口清单](LEARNING_PREVIEW_RELEASE_READINESS_20261007.md)收尾。 / Latest installers, external apps, other devices, provider accuracy and universal reliability remain unverified.
