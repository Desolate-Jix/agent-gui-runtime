# 默认全选替换验证 / Default replacement verification

**历史首版记录，已由连续点击替换修正方案取代。** 此处保留当时分步点击审核和591项测试证据，不计作新组合路线通过。最新状态见[正式版验收记录](EXECUTION_STABLE_012_20261012.md)。 / Historical first replacement revision, superseded by the continuous click-and-replace change. Its tests do not certify the new route.


2026-10-12，用户明确将“可输入”判断改为“确认点中目标输入框”，删除空框识别。 / The user requested click-in-target confirmation and removal of empty-field classification.

- 新普通视觉输入：项目定位点击 → 一张实际点击标注字段裁剪图 → Decision确认点中输入框 → Ctrl+A → 输入 → Decision只核对规定文字。 / Default visual input confirms the recorded click, selects all, types, and verifies the requested text.
- 不调用空框OCR、不生成内容分类或typing_strategy、不做全选后的截图模型审核。旧证据认证及隔离诊断辅助仅保留历史用途，不由新执行链调用。 / No empty OCR, content classification, generated typing strategy or post-selection model review; historical authentication/diagnostic helpers are not called by the new runtime.
- 原动作门禁、真实全选派发、窗口/前台、剪贴板、取消/截止及输入后拒绝交Main保留。 / Existing action, dispatch, window/foreground, clipboard, stop and post-value Main-handoff contracts remain.
- 纯视觉clear_existing=false点击前明确拒绝；原生插入语义保持。新profile条件已加入视觉执行示例，数值阈值不变，旧冻结profile不改写。 / Visual no-clear is rejected before clicking; native insertion remains. The example profile allows the new condition without changing numeric thresholds or frozen profiles.

## 实际验证 / Checks run

Main使用 `D:/agent-gui-runtime/.venv/Scripts/python.exe -m pytest -q` 运行24个相关模块，**591 passed in 27.71s，0失败、0跳过**。涵盖完整InputController调用边界、正式示例profile与离线HTTP、标注图裁剪坐标、原生兼容、点击/文字拒绝、Ctrl+A后取消与截止、Enter准备失败结算、跨任务与篡改证据拒绝、旧v1/v2回执认证。全部为离线隔离测试，无真实输入或付费API。 / Main ran24 related modules:591passed, no failures/skips. Coverage includes real controller boundaries with isolated input primitives, example-profile HTTP requests, crop mapping, native compatibility, refusals, cancellation, terminal settlement, forged/cross-task evidence and historical receipt validation. No live input or paid API was used.

证据：`.superpowers/sdd/2026-10-12-default-replace/main-final.xml`；最终源码哈希见同目录`source-hashes.json`。 / Evidence and final source hashes are in the task evidence directory.

首次宽回归保留于`main-regression.xml`：402通过、1失败，为失败注入夹具缺少新增点击证据序列化接口；补齐夹具后最终回归通过。另复现并修复删除typing_strategy后Enter准备取消被记为unknown的问题。当前终结状态通过真实点击Decision证据与原回执认证，未把结果未知直接改成成功。 / The initial broad regression retains402passes and one failure caused by an outdated failure-injection proof fixture. A separate reproduced Enter-cancellation settlement defect was repaired with authenticated click evidence, without treating unknown results as success.

源码UTF-8/AST、JSON配置检查通过；按CRLF规则执行`git -c core.whitespace=cr-at-eol diff --check`通过。 / UTF-8/AST, profile JSON and CRLF-aware whitespace checks passed.

## 范围与限制 / Scope and limitations

本批未实机、未调用真实API、未打包/安装/提交/推送。此前OCR版本单轮3/3实测是历史证据，不能算作当前简化版本的实机通过或速度收益。保留原浏览器profile及缓存。 / No live API/desktop run, package, installation, commit or push. The earlier OCR candidate's3/3 live result does not validate this simplified candidate or establish a speed benefit. Browser profile/cache were preserved.

一次子任务误用uv启动生成了532201字节的17文件空虚拟环境，已中止；未修改pyproject.toml/uv.lock。删除被工具策略拦截后，改用可恢复归档移到本目录`aborted-uv-environment`，未删文件，根目录不留`.venv`。所有有效测试均复用D盘既有解释器。 / An aborted worker uv invocation generated a small bootstrap environment; no lock/config changes. After deletion was policy-blocked, it was reversibly archived under the evidence directory. All successful verification used the existing interpreter.
