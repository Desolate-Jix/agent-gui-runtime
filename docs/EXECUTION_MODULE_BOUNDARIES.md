# 执行模块维护边界 / Execution module boundaries

v0.1.1 将既有八个维护实现归入 `app/execution`：input_sequence、form_fill、conditional_observation、local_action_contract、local_keyboard_action、single_step_runtime_owner、local_direct_step、post_action_recovery。旧 desktop_review 路径为同一模块对象的兼容别名，保留异常/请求类身份与 monkeypatch 传播。/ Eight maintained execution implementations have canonical paths in app/execution. Legacy paths alias the same modules, preserving class identity and patch propagation.

本补丁基于正式 v0.1.0 原实现；六个完整模块逐字节迁移。LocalKeyRequest 收拢到动作字段合同，键盘 handler 与校验逻辑保持。协调器、STDIO 和组合命令仍用原 owner 与公共输入 API，消费者增量只更改导入和版本。/ The patch uses the release baseline, with six byte-identical moves and unchanged keyboard/validation semantics. Original owner and gated dispatch remain.

OptionalJudgment 是供未来执行与学习复用的可选建议合同；不生成坐标、不授权输入、不自动重试。见 [判断接口](OPTIONAL_JUDGMENT_AND_MODEL_USAGE.md)。正式工具仍为七个，学习工作台、学习工作流与新学习启动入口没有发布。未来学习实现应接原执行入口与原回执，不另建执行器。/ Optional judgment is an advisory shared contract, with no grounding, authority or retry. The seven-tool execution release does not ship the learning product; future learning should reuse original execution and receipt paths.

历史名称含 learn 的共用依赖仍保留，不按目录名称盲目剔除。host/coordinator 的其他共享职责尚未全部拆清。本补丁的验证、首次失败与范围见 [v0.1.1 验收](verification/V011_RELEASE_ACCEPTANCE.md)。/ Maintained historically named dependencies remain; other host/coordinator coupling is still open. See versioned acceptance for actual coverage.
