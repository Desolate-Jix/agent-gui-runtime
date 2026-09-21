# test.4 发布范围 / Release scope

分支 `codex/release-instant-test-4` 用于第四批即时执行测试版；从 test.3 的干净发布分支增量更新，不提交完整开发工作树的其他修改。 / This branch contains the fourth instant-execution test release, incrementally based on test.3, not unrelated development-worktree changes.

运行代码、测试、配置模板和依赖锁定文件逐字节来自已经 Codex 与 AionUi 实机验证的冻结候选 10。冻结清单 SHA-256：`21ffdf6cf5e5100559d706d3c34f52a7da43412701fb73002cd471e25f2aec7d`。发布后处理仅更新公开文档和验证摘要；不重新生成或修改运行代码。 / Runtime, tests, configuration templates and dependency locks match the live-tested frozen candidate byte for byte; only public documentation and verification metadata change.

本批增加选区按键并修复通用定位、原生菜单、剪贴板、窗口观察等问题。不包含学习模式交付，也不新增安全策略。 / Selection keys and common targeting, native-menu, clipboard and window-observation repairs; no learning-mode delivery or new safety policy.

验收是有人看护的 operator 模式：源码及包内测试集合重叠；同包连续实测和独立复测均通过限定任务，客户端失败保留。自动策略、跨设备和无人值守可靠性并未认证。 / Bounded supervised operator-mode acceptance only; overlapping test counts are not additive and tester failures remain recorded.

模型和环境另行安装；ZIP 不含账号、凭据、私人截图、运行会话或模型权重。详见 FRIEND_SETUP.md、AGENT_GUIDE.md、FIXES.md 与 release-verification.json。 / Models/environments are separate; no private operational data is shipped.
