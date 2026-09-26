# Execution caller scheduling / 执行调用方调度

These instructions supplement, rather than replace, the user's project instructions. / 本文件补充用户项目规则，不替代其权限、测试顺序和数据完整性要求。

- For live GUI tasks, follow `AGENT_GUIDE.md` → `Caller scheduling`: prepare known independent fields together, keep one input owner and one live MCP connection, and read pending results promptly using the original request ID. / 实机任务遵循调用方调度章节：预先整理已知独立字段，同一时间仅一个输入执行者，保持同一 MCP 连接，及时读取原 ID 的 pending 结果。
- Do not insert code searches, full-log dumps, unrelated documentation work or model research between healthy action batches. Interrupt for genuine failures or missing evidence; never skip result inspection. / 正常批次间不插入代码搜索、完整日志输出、无关文档或模型调研；真实失败或证据不足时中断，不省略结果核对。
- Missing personal data blocks only dependent fields. Reuse confirmed values; do not invent them. Prepare future labels/values, not stale coordinates or speculative actions. / 缺失资料只阻塞依赖字段，复用已确认值但不猜填；提前准备标签和值，不预存过期坐标或猜测后续动作。
- Follow the installed server contract, not unreleased source defaults. Never resend input to extend a receipt wait. / 按实际服务端版本调用，不把未发布源码默认值当已生效；不得为延长等待重新提交输入。
- Report executor time, caller gaps and explicitly measured user-wait time separately. Unknown time is unclassified, not model inference. / 分开报告执行耗时、调用方空档和有记录的用户等待；未分类时间不得写成模型推理时间。

- For Codex agent-gui-runtime delegated vision, read `skills/codex-vision-session/SKILL.md`: reuse the existing visual worker ID and continue with `followup_task`; do not spawn per screenshot. / Codex 使用本项目委派识图时，读取上述项目技能，复用已有视觉子 Agent ID，以 `followup_task` 续接，不逐图新建。此规则仅适配 Codex，其他客户端遵循各自委派机制。
