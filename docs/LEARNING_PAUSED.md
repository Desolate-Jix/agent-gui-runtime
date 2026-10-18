# 学习模式封存 / Learning mode paused

2026-10-18：按用户要求，本地继续维护执行模式，学习模式暂缓开发。维护分支为 `codex/dev-execution-maintained`，执行基线为 `8d692847ac9c05e60cb3b2e07059783cce56f3fa`（0.1.5）。本轮未更新安装版或公开发布。

The maintained checkout keeps execution mode on the published 0.1.5 source baseline. Learning development is paused; this maintenance change does not update an installed application or publish a release.

- 原 D 盘未提交源码保存到 `codex/archive-learning-paused-20261018`；较新的学习工作台源码另存 `codex/archive-learning-workbench-paused-20261018`。归档分支只在本地保存，完整 Git bundle 和原始字节 ZIP 位于 `E:/project-archives/agent-gui-runtime/2026-10-18-learning-paused`。仓库是公开的，本地历史、截图及私有材料未随归档上传。
- 学习工作台启动与打包入口、执行会话中的学习录制和控制、HTTP 学习写入入口均移除。`learning_*` 命令和显式启用学习会在准入前拒绝。
- 保留执行输入、连续计划、识图、原回执与恢复门禁。`app/learn`、`app/learning_memory` 和 `app/desktop_review` 中仍被执行组件引用的共享模块继续保留；目录名不代表学习入口仍开放。
- 浏览器资料、模型、运行环境、历史原始证据及其他 Git 工作树保留。源码归档不等同于全部运行数据备份；已迁走的旧载荷另有逐文件清单和完整性核验。

Original uncommitted source is preserved in the two local archive branches and portable backups on E:. Learning launch/build entrypoints, receipt recording and control, and HTTP learning writes are removed. Shared execution dependencies remain, including historically named modules and admission guards. Browser data, models, environments, original evidence and other worktrees are retained.

恢复学习开发时，应从归档分支另建开发分支，不把旧学习源码覆盖回当前执行主线。原字节 ZIP 可恢复本地换行与被忽略的维护文档；Git bundle 可在没有原仓库的情况下恢复分支和历史。

To resume learning development, create a separate branch from the archive. Restore original local bytes from the ZIP when needed; use the verified bundle to recover Git history independently of the original repository.
