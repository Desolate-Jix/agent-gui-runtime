请审核这三张 Learning Mode 页面详情/只读 PathGraph 预览图。目标不是评估真实点击，也不是证明准确率，而是只看显示层和结构层是否适合进入下一步 demo。

背景：
- 这次只改了页面详情候选生成层的 display-only overlap cleanup。
- 修复目标：同一个栏/section 内，没有父子包含关系的 Hero sibling panel 不应该互相遮挡；如果只是相邻内容被模型框重叠，页面详情输出前要裁剪分开。
- 这不是 Runtime PathGraph，不授权 Execute，不做 live click/fill/submit。

请分别审核三张图：
1. Python page-detail preview
2. AppleMusic page-detail preview
3. QQ page-detail preview

请按下面格式回答：

1. 总体结论：PASS / CONDITIONAL PASS / FAIL
2. Python：
   - Hero code panel 和 Hero text panel 是否已经不再互相遮挡？
   - 页面详情的内容位置是否基本对应原栏位置？
   - 还剩哪些具体问题？
3. AppleMusic：
   - 这次规则是否把原本较完整的主栏卡片/侧栏/顶栏弄乱？
   - 是否存在明显应该过滤或降级的空白背景框？
   - 还剩哪些具体问题？
4. QQ：
   - 右侧群友栏是否比之前更完整，是否仍存在截断或错位？
   - 主聊天区、左侧会话栏、右侧栏之间是否有明显越界？
   - 还剩哪些具体问题？
5. 下一步建议：
   - 只允许建议通用规则，不要建议针对某一个软件硬编码。
   - 如果你认为可以进入“内容精修 + 界面详情/只读 PathGraph 接入”，请明确写出允许条件。

请不要使用 accuracy、E2E success、可执行、已稳定 等结论。
