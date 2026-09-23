# 原生助记标签 / Native mnemonic target

## 故障与通用契约 / Failure and common contract

- Failure: test.7 candidate01 独立实测中，`Click the 打开(O) button at the bottom right of the Windows file picker dialog to confirm the selected file` 无唯一推荐，未点击；改用 Enter 选入附件不能证明识别点击通过。/ The original recognition request had no unique recommendation and dispatched no click; Enter recovery did not validate that route.
- Invariant: 动作对象的完整标签不能被后置用途说明替换。原解析未识别裸助记标题，`confirm` 影响动作类别，正确 `打开(O)` 与两个短名 `打开` 箭头并列。/ The action object's complete caption must not be replaced by a trailing purpose. Misclassification tied the actual Open(O) button with two shorter arrow captions.
- Fix: `app/operation/recognition/text_match.py` 接受开头动作宾语、单字母助记后缀、紧邻控件角色；不接受否定、多个备选或连续动作。既有 JSON 转义标签解析保留。/ Recognize anchored native captions with one mnemonic letter and an adjacent role; retain quoted-label parsing and reject ambiguous native-caption syntax.
- Why common: 适用于 Open(O)、Save(&S)、保存（S）等原生控件，不依赖网站、窗口坐标或具体应用名。/ Shared native-label parsing, not a site/profile-specific coordinate fix.
- Regression: `tests/test_native_mnemonic_target.py` 覆盖原目标、用途分离、真实角色、错误点、重叠同名候选和非单步描述。/ Covers the original goal, purpose separation, role, wrong points, duplicate controls and multi-action descriptions.
- Safety impact: 不改候选评分、坐标容差或自动风险模式。诊断推荐不等于许可；框外模型点在本地即时动作选择入口仍拒绝，同名歧义仍拒绝。/ No ranking, coordinate-tolerance or operator-mode changes; diagnostic recommendations still cannot authorize outside points or duplicate identities.

## 验证 / Verification

- 源码全套 1753 passed / 34.59 s；相关 73 passed / 1.40 s。集合重合不可相加。/ Overlapping source and targeted checks, not additive.
- 本方真实 Selenium 网页和 Windows 文件对话框，框架 MCP 全程输入：原始未加引号目标首次确认成功 8.574 s；后续静态附件目录的连续同会话确认两次 13.501 / 8.570 s，中间识别点击取消 8.782 s、重开和重新填写读回成功。最终网页显示测试附件，未最终提交。/ Original-goal click passed; two more confirmations with intervening cancellation/reopen and filename readback passed in one real browser session. Attachment filename appeared without submitting the form.
- 本轮初次连续取消曾因 UIA 文件列表 NULL COM 节点导致扫描不完整而拒绝，未点击。随后同响应的另一轮只读遍历完整。测试驱动当时在文件对话框浏览的目录不断生成文件，存在采集干扰；改用独立静态附件子目录后原取消点击通过。保留首次拒绝，不宣称运行时已修复所有瞬态 UIA 故障。/ First cancellation was refused on an incomplete UIA scan with NULL COM file-list nodes. A later read was complete. The test harness wrote into the directory being browsed; a static fixture directory removed that interference and cancellation passed. The original refusal remains recorded, not relabelled as runtime success.
- 两个本方会话的自建浏览器窗口和宿主均正常清理；`cleanup_verified=true`、`host_alive=false`、pending 为空。原始图片/日志仅本机保留，不入公开包。/ Both owned browsers and hosts cleaned; private raw evidence stays local.
- 此文只证明源码修复后的范围；新冻结候选的同包实机及独立 Agent 复验仍需完成。/ This source evidence does not replace frozen-bundle live and independent acceptance.
