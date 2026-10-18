# 学习模式封存 / Learning mode paused

2026-10-18：按用户要求，本地仅保留 `D:/agent-gui-runtime` 的执行开发环境，维护分支为 `codex/dev-execution-maintained`，基于公开的执行 0.1.5（`8d692847`）。执行维护分支及下列源码归档均已推送并回读远端提交。未合并到 `main`，未修改登记安装或发布新版。

The sole local development checkout maintains execution mode on the published 0.1.5 baseline. Its maintenance branch and the source archives below are pushed and verified against the remote. No merge to main, installed application update or new release is included.

## 已推送源码 / Pushed source archives

| Branch / 分支 | Commit / 提交 | Purpose / 用途 |
| --- | --- | --- |
| `codex/archive-learning-source-20261018` | `89dab6b2232f61cccfc072d3767e68e171b93f2b` | 原混合主树的可公开源码 / Public source from the former mixed checkout |
| `codex/archive-learning-workbench-source-20261018` | `dfbe2771408ec53a5a1f8a62cf8a47212c40e83b` | 较新学习工作台 / Later learning workbench |
| `codex/archive-input-focus-source-20261018` | `c907b06ed83a68aa2661e6c11c7d1cd357b5f750` | 旧输入聚焦修改 / Historical input focus changes |
| `codex/archive-instant-test-2-source-20261018` | `f544f3228bd30861d28168cef764531b36152af8` | 旧执行测试 / Historical execution tests |
| `codex/archive-decision-api-source-20261018` | `894e597c632676c59162b88dec9c7402fd3899f2` | 旧决策 API 修改 / Historical decision API changes |

这些是源码归档，不代表历史实现通过当前验收。公开分支隔离了本地文档、私有原始材料及未审核二进制；完整原件另有私有本地备份，公开源码不等于全部数据备份。

These branches preserve reviewed public source. They do not claim current runtime acceptance or include complete local evidence, private documents, model weights or development environments.

## 当前维护边界 / Maintained scope

- 学习工作台启动与打包、执行会话学习录制和控制、HTTP 学习写入入口已移除。`learning_*` 命令和显式启用学习在准入前拒绝。 / Learning launch/build, receipt recording/control and HTTP writes are retired; learning commands are rejected before admission.
- 执行输入、连续计划、识图、原回执与恢复门禁保留。`app/learn`、`app/learning_memory`、`app/desktop_review` 中被执行引用的共享模块继续维护。 / Execution and its shared historically named modules and guards remain maintained.
- 原五个重复开发工作树已备份并通过 Git 注销。旧 `decision-api` 位置仅保留四份浏览器资料、Git 数据占位和恢复说明，不含源码或虚拟环境；不得作为普通旧工作树删除。 / Five duplicate checkouts are retired through Git. The former decision-api location is a data-only retention slot for four browser profiles and recovery metadata, without development source or environment. Do not remove it during routine worktree cleanup.
- 根 `.venv`、模型、当前 llama/OCR 工具、运行状态和唯一原始证据保留。旧 OmniParser、四个旧工具环境、旧候选/构建/发行目录和重复学习备份已逐项核验后清理；最新执行发行目录仅移除下载依赖缓存。浏览器资料均原位保留。 / Current execution dependencies, models, state and unique evidence remain. Verified superseded environments and payloads are retired; only the dependency cache is removed from the latest execution delivery. Browser profiles remain in place.

## 备份与恢复 / Backup and recovery

- 首轮完整封存：`E:/project-archives/agent-gui-runtime/2026-10-18-learning-paused`。原 D 主树和新工作台的私有快照为 `codex/archive-learning-paused-20261018` 与 `codex/archive-learning-workbench-paused-20261018`，仅本地保留，禁止推送。 / Initial full private source and payload archives; raw snapshot branches remain local only.
- 本轮推送与整理：`E:/project-archives/agent-gui-runtime/2026-10-18-push-consolidate`。包含六组工作树普通文件 7z、Git bundles、历史环境及载荷归档、逐文件 SHA-256、独立恢复核验和精确移除记录。四份受保护浏览器资料未复制到这些工作树归档。 / Consolidation backups include regular files, Git bundles, hashes, recovery checks and exact removal records; the four protected browser profiles were excluded and retained in place.
- 恢复源码时从公开归档分支另建开发分支；恢复完整本地原件时依私有备份清单操作。不要将旧学习源码覆盖回执行维护树，也不要用归档内 `.git` 指针充当独立仓库。旧虚拟环境依赖外部基础 Python，不承诺可独立直接运行；按源码依赖重建。OmniParser 的原仓为浅克隆，恢复 Git bundle 时保留其已备份的浅边界。 / Resume on a separate branch, use private manifests for original bytes, restore bundles as real repositories, rebuild old environments, and preserve the archived shallow boundary for OmniParser recovery.
