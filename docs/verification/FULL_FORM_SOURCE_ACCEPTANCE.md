# Full-form source acceptance / 整表填写源码验收

2026-09-23. Unreleased source; test.6 downloads are unchanged. / 未发布源码，test.6 下载包未更新。

## Scope / 范围

Framework MCP on real public Selenium, Quill and Select2 pages; no DOM writes, locally invented test UI, private CV or final submission. Selenium is an official component demonstration, not the original BDO/JobAdder application. These results do not prove every recruitment site or widget.

通过框架 MCP 在真实公开 Selenium、Quill、Select2 页面操作。没有 DOM 写入、自建假界面、私人简历或最终提交。Selenium 是官方组件演示，不是原 BDO/JobAdder 求职表，结论不代表全部招聘网站或控件。

## Shared fixes / 公共修复

| Failure / 失败 | Invariant and fix / 不变量与修复 | Regression and impact / 回归及影响 |
|---|---|---|
| Native select expansion falsely changed tree scope. / 展开原生下拉误报跨窗口。 | Preserve GA_ROOT facts; admit popup through stable same-process native ownership; recheck after complete traversal. / 保留原生事实，仅按稳定同进程 owner 纳入读取范围，完整遍历后复核。 | test_form_owned_popup_tree.py; foreign/wrong-PID/changing owners remain rejected. / 异窗、错误 PID、变化 owner 仍拒绝。 |
| Editor focus can reflow layout, invalidating the old point. / 聚焦重排后旧坐标失效。 | Bind writable identity before gated click; match focused runtime ID, process creation time and window after click; use current geometry. / 点击前绑定可写身份，之后核对焦点身份并使用新几何。 | test_local_text_focus.py; Group/Document needs explicit whole-range writable TextPattern. Mixed/unknown stays blocked. / 全范围明确可写才接受。 |
| Blank multi-select confused with unrelated table-of-contents link. / 空白多选框受目录干扰。 | Reconcile model point only with one current actionable ComboBox, never override explicit conflicting labels. / 仅与当帧唯一真实 ComboBox 互证，不覆盖明确冲突标签。 | test_select2_point_form_identity.py; actual bounds required. / 不造框、不松坐标。 |
| Wide thin fields/options downscaled to tiny text. / 细长控件缩图丢失文字。 | Preserve pixels and bounded upscale in primary ROI; original candidate bounds and inverse transform unchanged. / 主 ROI 保留像素并有界放大，原框及逆变换不变。 | test_wide_form_control_roi.py; did NOT eliminate the Select2 model miss below. / 未消除下述模型误定位。 |

These are shared runtime changes, not site-coordinate patches. No new authorization or automatic input replay. / 均为公共运行时改动，无网站坐标补丁、额外授权或自动重放。

## Live evidence / 实机证据

Private evidence roots / 本机原始证据：`D:\AgentReviewAcceptance\20260923-full-form-01`, `-02`, `-03`. Commands, receipts, PNGs and first failures are retained locally, not uploaded. / 命令、回执、原图和首次失败保留本机，不对外上传。

| Run / 轮次 | Request / 请求 | Seconds / 秒 | Result / 结果 |
|---|---|---:|---|
| root02 native dropdown | adv-1790128711290 | 20.042 | Two selected/read back / 原生选项读回通过 |
| root02 eight-field batch | adv-1790128744545 | 107.186 | 8/8 matched / 八项全部一致 |
| root02 filename + choose | adv-1790129172730; adv-1790129197721; capture adv-1790129209870 | 14.890 + ~11.3 | Test attachment visible in original form / 附件出现在原表单 |
| root02 Quill type + replace | adv-1790129108071; adv-1790129127319 | 9.179; 9.087 | Chinese multiline and replacement matched / 中文多行及替换读回一致 |
| root02 repeated selected values | Same-session receipts / 同会话回执 | 4.901 | Three already satisfied, zero input / 三项零输入 |
| root02 missing option | adv-1790129233450 | 10.217 | Menu opened, then interrupted at field 0; later text untouched / 展开后中断，未执行后续字段 |
| root02 recovery | adv-1790129253786 | 31.302 | Choose One, replace text, leap date; all matched / 三项恢复成功，附件保留 |
| root03 final-source eight-field batch | adv-1790129953042 | 107.442 | 8/8 matched again / 最终源码再次全部一致 |
| root03 open, filename, choose | adv-1790130069763; adv-1790130099516; adv-1790130122503 | 9.036; 14.537; 9.944 | Filename exact readback then dialog closes / 精确读回后选定文件 |
| root03 final screenshot | adv-1790130133442 | 0.098 | Tested values and form-upload-test.txt coexist; Submit untouched / 值与附件同时保留，未提交 |

Eight fields cover text, Chinese multiline, datalist text, explicit-format date, native dropdown, two checkboxes and radio. Password, disabled/readonly, color and slider were excluded. Datalist entry is not proof of suggestion selection. File evidence proves UI selection, not completed network upload or accepted application.

八项涵盖文本、中文多行、datalist 文本、显式格式日期、原生下拉、两项复选和单选。未覆盖密码、禁用/只读、颜色和滑块；datalist 输入不等于建议项选择。附件仅证明界面已选文件，不证明网络上传或求职提交。

## Select2 boundary / 多选限制

- `adv-1790129751152`: broad goal produced an out-of-control model point; no input. More precise reviewed goal `adv-1790129790418` opened the correct control (13.600 s). / 宽泛描述误定位拒绝，复核后精确描述展开正确控件。
- `adv-1790129811990`: exact Alaska bbox `(860,967,810,28)`, model point `(931,944)` hit the group header instead. Rejected (10.792 s), no input. Wording change `adv-1790129868845` also failed. Pixel preservation is NOT claimed to fix it. / 精确选项存在，但模型点落在分组标题；保留失败，不称已修。
- Agent inspected highlighted Alaska and focus, then explicitly used the existing keyboard route: Enter `adv-1790129893127` (2.245 s), type Hawaii `adv-1790129903382` (0.393 s), inspect filtered highlight, Enter `adv-1790129910849` (2.238 s). Original screenshot shows both chips. / Agent 核对高亮后主动改用现有键盘路径，截图确认两项均保留。
- This is keyboard recovery, not automatic retry or a passing visual option-click test. Set-valued batch add/remove is not implemented. / 这是键盘恢复，不是自动重试或视觉点击通过；集合式批量增删尚未实现。

## Verification and limits / 验证与限制

- Clean desktop Python `python -m pytest -q`: **1633 passed in 34.57 s**; `git diff --check` clean. / 源码回归及差异检查通过。
- Source only; no packaging, commit, push or AionUi delegation. Resolve visual option reliability and set-valued multi-select before claiming full advanced-form support, then independently verify the same frozen candidate. / 未打包、提交或派独立验收；多选完善后才冻结同包复测。
- Quote exact native filename labels containing parentheses, e.g. `文件名(N):`. The earlier unquoted goal failed exact identification; no encoding corruption was found. / 带括号标签需完整加引号；先前失败并非乱码。
- Formatting toolbars, mixed readonly/editable media, calendar navigation, drag/drop and custom canvas widgets remain unverified. / 富文本格式工具、混合只读内容、日历导航、拖拽和画布控件未验收。

- All full-form roots 01/02/03 ended with cleanup_verified=true, host_alive=false, pending_ids=[]; framework-created test windows closed. / 三轮均清理完成，宿主退出、pending 清空，本轮测试窗口已关闭。


## 2026-09-23 用户当前求职表实测 / User-opened application test

通过框架 MCP 填写真实 NZX Software Developer / JobAdder 表格并滚动至页底：18 个文本项、10 个下拉项、1 个无隐私测试附件。上中下截图复核；性别、年龄、族裔均不透露；其他族裔说明不适用留空，真实性声明未勾选，Apply Now 未点击。顶部 resume 自动填充捷径未使用，测试文件选在 Cover note 附件栏，不代表服务器已接收上传。用户原浏览器及填写结果保留。

Framework-only input filled 18 text fields, 10 dropdowns and selected one synthetic attachment across the real page. No final submission or truthfulness attestation. The original browser remains open. This is completed filling with agent-directed keyboard recovery, NOT a passing full visual/batch acceptance.

本轮未修改运行时代码。Preferred Name 模型误定位、文件按钮候选歧义、自有原生下拉被误报遮挡、可见 Gender 选项报 form_option_not_visible 均保留首次失败；键盘恢复不算修复。后者根因尚未确定，不推断仅为大小写。跨应用应修候选与可写控件关联、同进程 owner 弹层身份及选项读取公共契约，而非硬编码网站坐标；修复前须建对应失败回放回归，本轮未关闭这些缺陷。没有降低闸门或自动重放，也未点击提交。

Open shared contracts: candidate-to-writable identity, owned popup identity, and visible option inventory. Root causes and regressions remain pending; keyboard recovery does not close those defects. Client-only unsupported Space and oversized wheel-count requests were rejected before dispatch.

证据 / Evidence: D:\AgentReviewAcceptance\20260923-user-form-01\TEST_SUMMARY.json; top adv-1790138626135, middle adv-1790138655989, bottom adv-1790138604122. Raw receipts/screenshots stay local (the application URL contains a token). Cleanup verified: host_alive=false, pending_ids=[], cleanup_verified=true. No package, publish or external-agent handoff.
