# 2026-10-07 当前release-ready状态 / Current release-ready status

第三批source14/GUI12已完成匹配冻结与实装限定验收，状态为release-ready。Main与独立Sol各记录2个教学事件、6个预期连续场景（5个正例完成，负例一次点击后判失败，无重复输入）；GUI Save原job为completed并返回captured状态的动作后截图，关闭重开后图像关闭选项保持，最终cleanup完成。第一批终态JSON读取失败及第二批空标题清除绑定失败原记录保留；旧便携candidate02未知退出未宣称修复，stablev0.1.1保持原发布。网络发布与下载核对单独记录在对应发行页。 / The matched third source14/GUI12 pair is release-ready after bounded installed acceptance. Main and independent Sol each recorded two teaching events and six expected continuous cases: five positive completions and one negative failure after a single click without replay. The original GUI Save job completed with captured post-action evidence; image disablement persisted across close/reopen and cleanup completed. Both earlier failures and the unexplained excluded portable exit remain historical. Stablev0.1.1 is unchanged; publication and download verification are recorded separately on the release page.

当前安装包含默认图像规则提议、人工区域编辑及可关闭图像核验；不确定保留原请求交Agent审核，不重放输入。流程图引用图钉固定的界面版本，附加成员不自动创建跳转。GUI页签为“结果与读取”。本地模型权重可选；本轮没有新增真实API供应商测试，不宣称通用准确率、速度或模型用量收益。 / Current installers include default image proposals, editable regions and persistent disablement. Uncertain evidence retains the original request for Agent review without replay. Graphs pin interface versions and membership does not create transitions. The GUI tab is Results and readback. Local weights are optional; no new real API-provider tests or general accuracy, speed or usage claims.

| 组件 / Component | 版本 / Version | 冻结批次 / Frozen pair | Setup SHA256 |
|---|---|---|---|
| 执行 / Execution | `0.1.2-preview.1` | source14 / installers-execution-13 | `fc8e343549d84d3deceb3d116451bc739729402fdefc2b5a1ba5a097e96ea5e7` |
| 可选学习 / Optional learning | `0.1.0-preview.1` | GUI12 / installers-learning-12 | `d67443fdb9c77d60db4063a66b501e1be1ae45baf9c2af2b2a8cbecad86728b9` |

[最终限定验收 / Final bounded acceptance](LEARNING_PREVIEW_RELEASE_ACCEPTANCE_20261007.md)。下方原段落为原冻结时点历史记录；版本与限制以本节及最终验收为准，不覆盖首次失败。 / Original sections below describe historical freezes; use this section and final acceptance for current scope while preserving first failures.

---

# 学习测试版发布缺口 / Learning preview release readiness

2026-10-07。用户要求保留当前等待设置，准备发布并核对缺项；本轮不再增加速度优化。目标是可选学习独立安装器及兼容执行独立安装器，正式执行v0.1.1保持原发布。现有预览标识为学习0.1.0-preview.1、执行0.1.2-preview.1；最终资产冻结前核对组件版本、MCP标识、安装器及更新兼容关系。 / Preserve current waits and prepare the optional independently installed preview pair, leaving stablev0.1.1 unchanged. Verify component/MCP/installer versions and compatibility at the final freeze.

## 已有证据 / Completed evidence

- 独立安装、可选学习、离线库编辑、人工审核修改、参数化不可变工作流、中英文切换、分安装根连接已有source11/Setup10及GUI09/Setup09的Main N17和Sol N18限定证据。
- 最新默认图像规则、区域编辑、图像核验及等待共同编译在维护源码中；本轮最终269项相关回归、c05连续正/延迟/Agent/负例及正常清理完成，独立原件审计通过。见[最新源码证据](LEARNING_IMAGE_WAIT_EARLY_EXIT_20261007.md)。
- GitHub实际Release读取显示最近公开版为[instant-v0.1.1](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.1)，远端refs没有学习preview标签。第一批最终候选已构建并安装；实装教学暴露终态回执读取故障，待新候选复测，尚未提交或公开发布。CLI gh不可用；只读GitHub连接已完成远端核对，不构成发布权限证明。

English: prior installed journeys and current source journeys are separate evidence. The public stable release is unchanged; current source changes are not new published installer assets.

## 必须收尾 / Required closeout

| 顺序 / Order | 缺口 / Gap | 完成条件 / Exit |
|---|---|---|
| 1 | 旧包缺最新实现 / Installers lag source | 一次集中冻结并构建匹配的执行与学习候选；最新image_verification及编译/编辑依赖进入实际载荷，生成新manifest、版本和SHA |
| 2 | 新包功能依赖未闭合 / Functional closure | 独立包目录、隔离解释器及树外cwd检查真实入口；参考PNG读入/匹配、图像编辑开关保存重开、共同编译及恢复消费可用。核实GUI的cv2/numpy实际冻结；MCP握手不代替功能 |
| 3 | 新包安装与输入未验收 / Installed regression | 全新安装/普通升级、快捷方式/版本/库保留/分根连接；新数据连续验证默认图像、关闭后Agent、延迟、拒绝后原请求审核、保存重开及正常清理。Main完成修复复测后，独立Agent验同一冻结 |
| 4 | 发布源码和资产未闭合 / Release closure | 从大量未提交改动中确定维护源码与测试/文档清单，保留无关改动；不上传库/截图/模型/密钥/本地证据；精确commit/tag、prerelease资产与SHA，公开下载字节核对 |

English: freeze/build once, verify isolated functional dependencies, validate the installed pair continuously and independently, then close scoped source/tag/assets and public download checks. Old installed tests cannot certify changed production bytes.

README和当前状态说明已同步第一批安装失败及源码读取修复；预定发行链接标明未发布。最终候选产生后仍须回填其名称、版本、manifest/SHA及实际安装验收，不能沿用旧516/330清单冒充新包。 / Documentation distinguishes the first failed installed batch and the source read repair; final candidate identifiers/hashes and acceptance must still be filled in.

## 本次范围 / Scope

旧便携candidate02已由独立安装路线接替，不作为资产发布；其首次自行退出根因未知，保留原说明，不宣称已修。学习非必需，本地模型非必需；API或图像Agent路线按配置使用。未来决策API、广泛benchmark、真实服务商准确率、任意应用保证及进一步性能优化不扩成此次发布前置。 / Exclude the superseded portable candidate while preserving its unexplained exit. Learning and local weights remain optional; future decision APIs and broad benefit claims are outside this closeout.

第二批实装已完整记录教学事件并完成六个预期连续场景，工作台保存后观察仍因空标题导致既有绑定被清除而失败。公共窗口刷新修复经Main55项及独立审查通过；第三批实装复测与独立验收待完成，前两批失败均保留。未公开发布。详见[终态读取故障](LEARNING_TERMINAL_READ_LOCK_20261007.md)与[已绑定窗口标题刷新](LEARNING_BOUND_TITLE_REFRESH_20261007.md)。 / The second installed pair recorded both events and handled all six expected continuous cases, but Save observation failed after an empty title cleared the known binding. The common repair passed Main55 checks and independent review; third-pair installed retest and independent acceptance remain pending. Both original failures stay recorded; no public release yet.
