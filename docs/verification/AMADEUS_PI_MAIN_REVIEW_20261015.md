# Amadeus Pi Main review acceptance / Amadeus Pi 主 Agent 续行验收

2026-10-16. Execution 0.1.5 / extension 0.0.2 evidence. Final artifact checksums and independent installed acceptance are tracked in the [release notes](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.5). Older controlled and normal runs below retain their original candidate identities. / 执行版 0.1.5／扩展 0.0.2 证据。最终交付校验值和安装态独立验收见[发布说明](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.5)，下方受控及正常运行保留各自原候选身份。

## Final source and wallpaper follow-up / 最终源码与壁纸补充

The final affected-source regression passed **135 checks** (pytest wall time 117.94 s; JUnit suite time 117.924 s). The earlier 115-check and independent 74-check groups overlap and are not added. All 575 Python files matched the previously installed 0.1.5 candidate before documentation finalization; this is source continuity, not another desktop run.

最终相关源码回归 **135 项通过**（pytest 117.94 秒，JUnit suite 117.924 秒）。此前115项和独立74项有重叠，不相加。文档收拢前，575个Python文件与此前已实测安装候选逐字节一致；这不算另一轮桌面验收。

Lively 2.2.1.0's null display-name mapping was verified by a real intervention: the unchanged copy returned empty wallpaper lists in 7/7 reads; after changing only that mapping, six consecutive post-initialization reads returned the correct scene. Amadeus then completed two mount/stop/restore cycles with the corrected copy. A separate real negative test retained the original mount timeout, `MountUnconfirmed` journal and running host; correcting the copied service then allowed explicit recovery. The Amadeus recovery fix is [PR #228](https://github.com/Code-Amadeus/Amadeus/pull/228), not a repair to Lively's protocol.

Lively 2.2.1.0 的空显示器名称映射已用真实干预验证：原副本7次均返回空壁纸列表；只修正该映射后，初始化后的连续6次返回正确场景。Amadeus随后在修正副本上完成两轮挂载、停止和恢复；单独真实负例保留原挂载超时、`MountUnconfirmed` 日志及宿主，修正副本后显式恢复成功。Amadeus恢复修复见 [PR #228](https://github.com/Code-Amadeus/Amadeus/pull/228)，不把它称为Lively协议修复。

After those tests, the local installed Lively DLL was backed up and patched. Of 613 program files, only `Lively.dll` changed: `ca73583755c8fc381cdda674bfbc3c60fea0bf924dcb06f846083c0b30f354ad` → `2206123045ccbad5b1d21039becba8ed7d673d6c2f20c703d5e02c57dfddd414`. This is a reversible local third-party patch, not an official update, and it is **not distributed** in the Runtime or wheel. Normal-path follow-up is reported with final release acceptance; other users' Lively installations are not automatically repaired. Renderer screenshots establish composer controls only, not the physical desktop or character background. Two earlier observer errors remain recorded and are not counted as complete passes.

上述测试后，本机已备份原DLL并应用修正；613个程序文件中仅 `Lively.dll` 从上述原哈希变为修正哈希。这是可回退的第三方本机补丁，非官方升级，**不随Runtime或wheel分发**。正常启动路径的最终结果由发布验收说明承接，其他用户的Lively安装不会自动修复。renderer截图仅证明composer控件，不证明物理桌面或角色背景；此前两次观察器错误保留，不计完整通过。

## Result / 结果

Two normal synthetic Notepad tasks completed through the installed Execution **0.1.5 candidate + extension 0.0.2**, in run10 and the same Chat session. Each used a fresh fixture, Pi Work, Runtime session and owned window; this is not two tasks in one Pi process or Runtime session. All six steps, exact disk checks, owned-window closes and final Runtime status checks passed, with no Main semantic review/override. Normal Host permission approvals remain separate.

已安装的执行版 **0.1.5 候选＋扩展 0.0.2**，在同一 run10 产品及 Chat 会话完成两项正常合成记事本任务。每项分别使用新 fixture、Pi Work、Runtime session 和自有窗口，不是同一 Pi 进程或 Runtime session 连跑。六步均成功，精确磁盘核对、各自窗口关闭及 Runtime 最终状态均通过，没有 Main 语义审核／override；正式 Host 权限批准仍另行保留。

| Normal task / 正常任务 | turn11 | turn12 |
| --- | --- | --- |
| Plan / 计划 | 3/3 success, completed | 3/3 success, completed |
| Runtime model HTTP / Runtime 模型 HTTP | 7 Decision + 1 ordinary Luna + 3 grounding = 11 | 7 Decision + 0 ordinary + 3 grounding = 10 |
| Main semantic review / Main 语义审核 | 0 | 0 |
| Disk, owned close, final Runtime status / 磁盘、自有窗口、Runtime 终态 | exact match; window_closed; host_alive=false, pending_ids=[], cleanup_verified=true / 精确匹配、窗口关闭、宿主清理通过 | same checks passed / 同项检查通过 |

The two tasks total **21 Runtime model HTTP requests**, excluding Chat/Pi models and TTS. Turn11's primary rejection was accepted by ordinary Luna; final history marked decision does not mean every primary check passed. Turn12 self-corrected a policy-denied bash attempt and an SDK-local missing-request_id error before Runtime input dispatch; it is not an error-free first attempt. The original turn10 was rejected by the harness's 4,000-character preflight (4,834 characters); corrected turn11/12 requests were 3,141/3,260 characters. Preserve the original rejection.

两任务合计 **21 次 Runtime 模型 HTTP**，不含 Chat／Pi 模型和 TTS。turn11 首层拒绝后由普通 Luna 复核通过，最终 history 为 decision 不等于全首层通过。turn12 的 bash 策略拒绝及 SDK 本地缺 request_id 错误均在 Runtime 输入派发前由模型自行纠正，不能称零错误首过。原 turn10 因仪表的 4,000 字符前置限制拒绝（实际 4,834）；修正后 turn11／12 为 3,141／3,260 字符，原拒绝保留。

The extension lifecycle also passed through its formal owner: disable → a controlled reopening retaining this extension store → missing contributions; then remove({deleteData:false}) → restart → missing contributions and installation removal. Main verified all **149 original data files / 4,699,337 bytes**, with every SHA unchanged. The observer used the validated Host Python 3.12 at E:/amadeus/.venv; its frozen SHA is 0873605d93a58b9cdaa4c188c7a3dc69e90028dc56b64df1473e83a0a6ddd86b. Both the old product and observer are settled; the old product exited with code 1, so this proves owned-process settlement, not graceful Electron exit.

扩展生命周期也经正式 owner 通过：disable → 保留本轮 extension store 的受控重开 → 贡献缺失；再 remove({deleteData:false}) → restart → 贡献缺失且安装目录清理。Main 核对原 **149 文件／4,699,337 bytes** 的 SHA 全部不变。observer 使用已验证的 E:/amadeus/.venv 下 Host Python 3.12，冻结 SHA 如上。旧产品与 observer 均已 settled；旧产品退出码为1，只记 owned-process settled，不称 Electron 优雅退出。

## Earlier TEST recovery sample / 旧 TEST 恢复样本

The earlier live04 sample used extension 0.0.1 and an unreleased Runtime candidate. It exercised the original-input review path on a real Notepad window: after two intentional test-service rejections, the original Pi Agent received the bound PNG, approved the typed text and explicitly continued the same command. File-menu and Save completed, the file matched, and the owned window and Runtime were closed. This is separate from the installed 0.1.5/0.0.2 normal tasks above.

旧 live04 使用扩展 0.0.1 与此前未发布 Runtime 候选，在真实记事本窗口验证原输入审核。测试服务有意双拒绝后，原 Pi 收到绑定 PNG，审核已输入文字并明确继续原命令；菜单、保存、磁盘及窗口／Runtime 收尾完成。此旧注入样本与上方已安装 0.1.5／0.0.2 正常任务分开，不能转记为 0.1.5 已重测双拒绝。

This is **controlled fault injection with real GUI execution**, not evidence that the paid models naturally misclassified this image, nor an accuracy or latency benchmark. The injection affected exactly one matching Decision value check and its ordinary review. Original nonpass records remain unchanged.

这是**受控故障注入下的真实 GUI 恢复测试**，不代表付费模型在这张图上自然误判，也不作为准确率或延迟评测。注入仅影响一组匹配的 Decision 输入值核验及普通复核，原非通过记录完整保留。

## Earlier TEST facts / 旧 TEST 已核事实

| Contract / 合同 | Evidence / 证据 |
| --- | --- |
| Original execution / 原执行 | One original input job and one `focus_type` dispatch; selection and typing each started/completed once. / 原输入 Job 和 `focus_type` 派发均只有一次，全选与文字输入各开始、完成一次。 |
| Actual image / 实际图片 | Pi's native tool result contains the original 11,099-byte PNG; SHA256 `4903e3a17e1704ae5876f8aaa87b568ae070f05404053c983ea6eec8e8cbafcf` matches the packet and file. / Pi 原生工具回执中的 PNG 与审核包及原文件哈希一致。 |
| Explicit recovery / 明确续行 | `plan-review-note-001` then `plan-continue-note-001`, on the original run, step, execution and wait ID. / 先审核、再继续，均绑定原运行、步骤、执行和等待 ID。 |
| Model provenance / 判断来源 | Both original choices remain `condition_not_met`; input-value approval is separately recorded as `main_agent`. / 原双模型结论仍为非通过，输入值批准单独记为主 Agent 来源。 |
| Remaining plan / 余下计划 | `first_edit`, `first_menu`, `first_save` all succeeded in the same run. / 同一运行的输入、菜单、保存三步均成功。 |
| Saved data / 保存结果 | UTF-8, 43 bytes, no BOM or trailing newline: `Pi Main review - approved without retyping.` / UTF-8 共 43 字节，无 BOM、无结尾换行。 |
| Cleanup / 收尾 | `window_closed`, then `phase=stopped`, `host_alive=false`, `pending_ids=[]`, `cleanup_verified=true`. / 自有窗口关闭后，宿主停止、待处理列表为空、清理验证通过。 |

The final whole-step verifications are marked `judged_by=decision`; the earlier input-value override remains independently recorded as Main review. These fields describe different checks and must not be summarized as “no Main intervention.”

整步最终核验的 `judged_by=decision` 与此前输入值的 Main 审核是不同记录，不能因此声称本轮没有 Main 介入。

## Pi image fix / Pi 图片适配修复

Pi's pinned catalog did not recognize the configured legacy `deepseek-v4-flash` ID. Its custom-ID fallback inherited text-only metadata and omitted MCP images before making the request. A real API probe using that same legacy name read a random synthetic image correctly; the returned model was `deepseek-flash`.

Pi 固定依赖的模型目录未识别已配置的旧名称 `deepseek-v4-flash`，其自定义 ID 路径继承纯文本元数据，在请求前丢弃 MCP 图片。同名真实 API 探测能够正确读取随机合成图，服务实际返回 `deepseek-flash`。

The final Amadeus-owned fix uses the public session_start / before_agent_start hooks and pi.setModel for the current unregistered legacy Flash selection. It preserves wire IDs, native cache/refresh, authentication, endpoints and explicit user/provider declarations; Pro and unknown IDs do not gain image capability. The earlier Provider-registration overlay was abandoned. Third-party node_modules were not edited. **17 real native SDK checks passed**, including MCP image conversion and zero fetch attempts. PR #225 and the separate cancellation-cleanup PR #226 each passed five CI workflows and are ready, open and unmerged; the approval-policy proposal is filed as issue #224. Official compatibility: [model aliases](https://api-docs.deepseek.com/guides/codex), [vision input](https://api-docs.deepseek.com/guides/vision/).

最终 Amadeus 自有修复使用公开 session_start／before_agent_start 与 pi.setModel，仅修补当前未注册的精确 Flash 旧名称选择；保留 wire ID、原生缓存／refresh、认证、接口及用户／Provider 显式声明，Pro 与未知 ID 不增加图像能力。旧 Provider 注册覆盖方案已弃用，第三方 node_modules 未改。**17 项真实原生 SDK 检查通过**，覆盖 MCP 图片转换且 fetch 尝试为零。PR #225 与独立取消收尾 PR #226 各5项 CI 通过，均 ready、open、未合并；审批策略提案已登记 issue #224。

## Scope and limits / 范围与限制

- Runtime source: `codex/dev-main-review-resume`, based on `e6ed046185dcdc935538d4281a07862e4b739b1c`. The frozen execution candidate is separate from the published 0.1.4 package. / Runtime 源码为该开发分支，冻结执行候选与已发布 0.1.4 安装包分开。
- Amadeus experiment: `codex/dev-amadeus-pi-runtime-extension`, based on `a9a488aecece97b7bcf26429c314c96187321e50`, plus the owned Pi metadata fix. / Amadeus 实验分支在该上游提交上加入自有 Pi 元数据修复。
- Extension identities: earlier live04 TEST used wheel 0.0.1, SHA256 b5f55c4b8768ab4e45acef12c51506d0fb4d6b67351bc676d6e1df996d5167d9; the installed normal/lifecycle candidate uses 0.0.2, SHA256 32d27ed81eab33db05ae2780b98a808205da5057ee98bd71bdad8382e35a6588. Both start the existing Runtime and supply a Skill, without a second executor. / 旧 TEST 与新安装候选身份分开；两者均复用现有 Runtime，不增加执行器。
- Amadeus retains outer `execution=succeeded`, `completion=partial`, `state=review_ready`: its Host does not accept provider self-attestation as explicit business completion. This is separate from the verified Runtime task and cleanup. / Amadeus Host 不把 provider 自述直接视为业务验收，外层保留上述状态；与已核验的 Runtime 任务完成及清理分开记录。
- Normal run10 narration respected the Japanese character-language lock. Two tasks have 38 software playback sentence-end records; generation/cache and playback evidence are recorded, including one cached first sentence. No acoustic recording, listening or ASR acceptance was performed. / 正常 run10 遵守日语角色锁；两任务共38句有软件播放结束记录，保留生成／缓存证据（含一句首句缓存），未作声学录音、听感或 ASR 验收。
- Earlier interfered desktop samples were excluded from functional, speed, stability and accuracy conclusions at the user's instruction. Their raw records and installation/connectivity evidence remain. / 按用户要求排除此前受干扰的桌面业务样本，保留原记录及安装、连通证据。
- run08 mount timeout and run09 45-second readiness failure remain valid unattended failures. Installed Lively service IL and the real proto setter establish a null DisplayName defect, but the live exception was not captured. The original Lively installation is unchanged; third-party repair scope awaits the user, and wallpaper compatibility is not declared complete. / 壁纸两次无人干预失败保留；静态及 setter 反例证明空 DisplayName 缺陷存在，动态异常未捕获、原安装未改，第三方修复范围待用户选择，不称壁纸兼容完成。
- Full independent installed-candidate GUI acceptance, forced-exit recovery, broader stability and formal release remain outside this result. Runtime cleanup comes from each task's original final status; the lifecycle observer does not independently re-prove it. / 完整独立安装候选实机验收、强退恢复、更广稳定性与正式发布仍未完成；Runtime 清理依据各任务原最终 status，不由生命周期 observer 另行证明。

## Local evidence / 本机证据

`D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/`:

- [Earlier live04 TEST acceptance / 旧 live04 TEST 验收](D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/pi-field-review-live04-final.json): eight controlled recovery checks passed, separately scoped to the old candidate/0.0.1. / 旧候选与0.0.1的8项受控恢复检查，独立保留。
- [Installed turn11 audit / 安装态 turn11 核验](D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/pi-product10-normal-acceptance-audit.md) and [turn11–12 continuous audit / 两任务连续核验](D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/pi-product10-continuous-audit.md) ([JSON](D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/pi-product10-continuous-audit.json)): two tasks, six steps, 21 Runtime HTTP; second-Work outer errors retained. / 两任务六步及外层纠错边界。
- [Formal lifecycle result / 正式生命周期结果](D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/extension-lifecycle-product-10/result.json); [data before / 数据前清单](D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/lifecycle-data-before-main-01.json) and [data after / 数据后清单](D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/lifecycle-data-after-main-01.json): all 149 original files and SHA unchanged. / 原149文件及SHA全部不变。
- [Final observer review / 最终 observer 核对](D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/lifecycle-observer-main-review-02.json); [Wallpaper native build/setter audit / 壁纸构件与 setter 审计](D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/wallpaper-native-build-audit-01.md): separate lifecycle and unresolved wallpaper boundaries. / 生命周期与壁纸未闭合范围分列。
- `pi-extension-product-03-core-audit.md` and `.json`: independent read-only verification of original IDs, images, provenance and no replay. / 独立只读核对原 ID、图片、来源与无重放。
- [Final Pi metadata SDK checks / 最终 Pi 元数据 SDK 检查](D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/pr-preparation/main-final-metadata-17.xml): 17 passed; the earlier eight-check Provider-registration result is historical, not the final implementation. / 17项通过，旧8项注册方案记录不代表最终实现。
- `main-field-fault-live02.jsonl`: one primary and one ordinary injected rejection, separately marked from real forwarded API calls. / 一次主判断和一次普通复核注入拒绝，与真实转发请求分开标记。
- `interference-sample-policy-20261015.json`: prior desktop sample exclusions. / 旧桌面样本排除口径。
