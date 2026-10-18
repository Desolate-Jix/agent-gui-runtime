# 2026-10-07 当前release-ready状态 / Current release-ready status

第三批source14/GUI12已完成匹配冻结与实装限定验收，状态为release-ready。Main与独立Sol各记录2个教学事件、6个预期连续场景（5个正例完成，负例一次点击后判失败，无重复输入）；GUI Save原job为completed并返回captured状态的动作后截图，关闭重开后图像关闭选项保持，最终cleanup完成。第一批终态JSON读取失败及第二批空标题清除绑定失败原记录保留；旧便携candidate02未知退出未宣称修复，stablev0.1.1保持原发布。网络发布与下载核对单独记录在对应发行页。 / The matched third source14/GUI12 pair is release-ready after bounded installed acceptance. Main and independent Sol each recorded two teaching events and six expected continuous cases: five positive completions and one negative failure after a single click without replay. The original GUI Save job completed with captured post-action evidence; image disablement persisted across close/reopen and cleanup completed. Both earlier failures and the unexplained excluded portable exit remain historical. Stablev0.1.1 is unchanged; publication and download verification are recorded separately on the release page.

当前安装包含默认图像规则提议、人工区域编辑及可关闭图像核验；不确定保留原请求交Agent审核，不重放输入。流程图引用图钉固定的界面版本，附加成员不自动创建跳转。GUI页签为“结果与读取”。本地模型权重可选；本轮没有新增真实API供应商测试，不宣称通用准确率、速度或模型用量收益。 / Current installers include default image proposals, editable regions and persistent disablement. Uncertain evidence retains the original request for Agent review without replay. Graphs pin interface versions and membership does not create transitions. The GUI tab is Results and readback. Local weights are optional; no new real API-provider tests or general accuracy, speed or usage claims.

| 组件 / Component | 版本 / Version | 冻结批次 / Frozen pair | Setup SHA256 |
|---|---|---|---|
| 执行 / Execution | `0.1.2-preview.1` | source14 / installers-execution-13 | `fc8e343549d84d3deceb3d116451bc739729402fdefc2b5a1ba5a097e96ea5e7` |
| 可选学习 / Optional learning | `0.1.0-preview.1` | GUI12 / installers-learning-12 | `d67443fdb9c77d60db4063a66b501e1be1ae45baf9c2af2b2a8cbecad86728b9` |

[最终限定验收 / Final bounded acceptance](LEARNING_PREVIEW_RELEASE_ACCEPTANCE_20261007.md)。下方原段落为原冻结时点历史记录；版本与限制以本节及最终验收为准，不覆盖首次失败。 / Original sections below describe historical freezes; use this section and final acceptance for current scope while preserving first failures.

---

# 可选学习候选实装验收 / Optional learning installed acceptance

## 当前结论 / Current conclusion

本页描述候选的安装、使用与限定验收；[预定发行地址](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/learning-v0.1.0-preview.1)尚未发布，当前安装器不含最新图像改动。 / This page describes prior candidate installation and bounded acceptance. The planned release URL is unpublished; those installers lack the latest image changes.

## 精确候选 / Exact candidates

| 组件 / Component | 版本 / Version | 安装器 SHA256 / Installer SHA256 |
|---|---|---|
| 执行 `execution-source-11 / Setup10` | `0.1.2-preview.1` | `f867c5f26c815177abed9786f300bb0c5707c243e4e885fd17db65021e5ca025` |
| 学习 `learning-candidate-09 / Setup09` | `0.1.0-preview.1` | `2e261338a875f7f71f0c610bd8033f27792de9ebac54d8d8876025b81ab42e88` |

学习 GUI09 EXE SHA256：`3b5d22f337c1058140e84b8e01c67192620e5f14da790f553cf995086e21fcfc`。两个组件已普通升级，实装执行516项和学习330项逐文件 size/SHA 核对一致。 / Both current components were installed through ordinary upgrades; all 516 execution and 330 learning payload entries match.

## 历史 N10 Main 新内容旅程 / Historical N10 Main journey

本轮采用新的数据根、执行会话和 Record Desk 测试夹具，不读取旧学习资产。公开教学请求记录实际填写与原图读取；审核使用 `input_binding={kind:variable,name:value}`，整理生成两步参数工作流。随后通过普通工作台修改步骤名称、审核两步、保存 revision2，并正常关闭重开核对保留内容。 / A fresh data root/session/fixture supplied original teaching evidence. Public variable review and synthesis produced a two-step parameter workflow; ordinary UI editing, review/save and reopening preserve revision2.

保存程序：`task-program-cc5eadd5ec02b3e9c4fa5411cbebe55cbf436ae35307974615b65b100a306de7`。其输入为必填文本 `value`，第一步填写，第二步声明读取输出 `value_read`；定位、读取与结果审核均由 Agent 完成。 / The immutable program has required text input value and declared read output value_read.

| 原请求 / Original requests | 观察与结论 / Evidence |
|---|---|
| `127`、`169` | 正式接口回读同一程序及SHA，revision2未变 / Public reads retain the same program/SHA/revision |
| `128–138` | 原填写请求完成并审核后直接取消，runner立即cancelled、wait/active/pending为空；第二步未派发，原三份文件哈希及输入队列一致，后续capture可准入 / Reviewed cancellation releases ownership without next dispatch or receipt/queue mutation |
| `139–153` | 参数“native10-参数甲”两步completed，原读取图及声明输出匹配 / Run A completes with matching original read image/output |
| `154–168` | 同程序参数“native10-参数乙”两步completed，原读取图及输出匹配 / Run B reuses the same program with its own matching result |
| `175` | 普通工作台刷新显示两步通过及乙参数输出 / Ordinary UI displays both passed steps and Run B's output |
| `179–183` | 测试窗口已消失，host stopped、cleanup_verified=true、pending_ids=[]、cleanup_errors=[]，SDK exit0 / Windows absent, verified host cleanup and normal SDK exit |

首次与重开GUI PID40784/39924均有独立正常退出记录exit0；夹具46348通过其专属测试控制接口正常关闭，exit0。输入未按Enter、未点击Verify value或提交。 / Both GUI processes and the fixture close normally. Inputs did not press Enter, Verify value or submission.

## 历史 N11 Sol 独立新内容复验 / Historical N11 independent retest

独立N11实际安装516/330项再次逐文件核对；以新库和新会话生成两步参数草稿，通过普通GUI修改、审核保存revision2，切换English再切回中文，正常关闭重开保留语言与审核内容。程序 `task-program-14e47fa3248d41eea0adf1b1ef9780ac7ef9789c2b6edf3928a8d0cfc55df4a4` 在两次参数运行前后完整对象一致。130审核后131直接取消立即终态，原三文件与工作流队列不变，132后续capture准入；146/159甲乙两轮完整成功并分别读回原图及声明输出。166宿主清理核验、两个GUI、夹具和SDK均正常exit0。 / A separate fresh journey verifies the same installed pair, ordinary editing/review/save/reopen and Chinese persistence after language switching, immediate reviewed cancellation, two parameter runs and normal cleanup.

Main实际回读原终态回执和取消审计，重新核对1223份已归档原件的size/SHA，并查看甲乙原读取PNG。三份公共read PNG均保留；101个内部临时capture/artifacts引用已回收，其中74未独立归档字节，因此不称全部内部诊断图档案完整。SDK没有返回binary image块，图像是从正式image_path读取原PNG；不称binary图协议已验收。N11未复测GUI最终结果表刷新或恢复takeover，Main N10结果表显示证据另列。 / Main rehashed 1,223 retained originals and inspected the original A/B read images. All three public read PNGs remain; expired internal scratch references and incomplete scratch-image archival are explicit limits. There was no SDK binary-image response, independent final-table refresh or recovery-takeover test.

独立020缺嵌套身份、142额外启动冲突等调用错误均保留，零输入拒绝后续接原请求；不改记首次通过，不以新任务替代原输入。 / Preserve caller identity/start-conflict failures and continuation of original requests.

## 历史首次失败与修复记录 / Historical first failures and corrections

N7 首次独立取消失败保留：Trial结束而runner残留已审核旧票据，后续动作被 `workflow_run_active` 拒绝。共同修复仅结算同一匹配已审核票据；未审核、未知和不匹配仍受原门禁。Main源码五文件60项及独立源包副本60项通过，本轮N10实装原场景通过；不把旧首次失败改记为成功。 / The original stale-ticket failure remains recorded. The shared fix settles only the matching reviewed ticket; source and isolated-bundle regressions each pass 60 checks, followed by this native reproduction. See [取消合同](LEARNING_CANCEL_LIFECYCLE.md).

N10 第一次教学给只读事件指定了错误前图，合同拒绝；提前停止后不可变handoff仅含一步。Main用新学习段按正确顺序重新采集、审核后再停止与整理；失败原件保留，不称首次通过。选窗schema与过早观察请求的调用错误也保留，拒绝发生在派发前。 / Preserve the caller's first incorrect read-frame review and prematurely sealed one-step handoff; a new segment corrected the order. Caller schema/premature-observation rejections remain distinct from product defects.

最早取消审计 `history_unchanged=false` 比较的是未排序JSON键顺序；后续规范化比较为true，原审计文件不改。原命令、原回执和Agent状态文件的字节SHA前后相同。 / The initial key-order comparison is preserved; canonical history comparison matches, as do the original command/receipt/Agent-state byte hashes.

## 验证边界 / Validation boundaries

当前路径为 `learned`：填写由已学 UIA 规则解析，读取使用 `agent_read`，结果由 Agent judgment 审核。`steps_only` 保留为可选策略及其恢复边界；不承诺模型调用、费用、速度或准确率收益。 / Current validation uses learned UIA input rules, agent_read and Agent judgment. Steps-only remains optional with its recovery boundaries; no model-call, cost, speed or accuracy benefit is claimed. 原等待续接使用原请求，不重放未知输入，不保证自动跨宿主或重开自动继续。 / Resume original requests without replaying unknown input; automatic cross-host or UI-restart continuation is not guaranteed.

发布辅助脚本的离线23项通过，只覆盖fake transport的草稿、tag、资产字节与未知结果对账；不证明实网发布权限或公开下载。正式 `instant-v0.1.1` 未修改或替换。 / Publisher tests are offline and do not prove real publication or public downloads. Stable v0.1.1 remains unchanged.

原始请求、回执、PNG、退出日志和哈希索引保留在本地验收证据目录。公开源码只包含维护实现和合同测试，不上传用户学习库、截图缓存、模型或凭据。 / Original evidence remains in the local acceptance root; public source excludes user libraries, screenshots, models and secrets.
