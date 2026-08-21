---
name: small-step-git-checkpoints
description: Use when a Git-backed implementation has independently verifiable slices and automatic per-slice commits or rollback checkpoints are authorized.
---

# Small-Step Git Checkpoints

## Core principle

一次 commit 只证明一个独立 implementation slice：**实现、对应测试、必要文档同步**。每个 checkpoint 必须可检查、可定位、可 `git revert`；不能为了制造“干净历史”而破坏尚未提交的工作。

本 Skill 只在用户或仓库规则已经授权自动 commit 时执行 commit。**自动 commit 不等于自动 push**；没有单独明确授权时不得 push。

## Define the slice

一个 slice 应同时满足：

- 只有一个主要行为、合同、不变量或修复目标；
- 能通过 focused test / validation 独立证明；
- 依赖的测试、schema、fixture 和必要文档与实现一起提交；
- 删除这个 commit 时，不会连带删除另一个无关功能。

不要把 schema、helper、adapter、测试和文档机械拆成多个相互不能工作的 commit。也不要把两个无关功能塞进同一个 commit。

## Per-slice loop

1. **记录边界**
   - 查看 `git status --short --branch` 和当前 `HEAD`。
   - 明确本 slice 的文件/hunk allowlist，以及开始前已经存在的 unrelated dirty files。
2. **小步实现与验证**
   - 遵循仓库的 TDD / implementation loop。
   - 运行能直接证明该 slice 的最窄 focused tests；失败时修复并重跑。
   - 测试失败不得创建声称完成的 commit。
3. **显式暂存**
   - 使用 `git add -- <explicit paths>`；混合文件使用 `git add -p`。
   - 如果同一 hunk/同一行混入继承改动，先安全拆分 hunk；无法无歧义拆分时停止自动 commit，不能猜测所有权。
   - 在 dirty worktree 中禁止用 `git add .`、`git add -A` 或 `git commit -a` 代替边界判断。
4. **Commit gate**
   - 检查 `git diff --cached --name-status` 和完整 staged diff。
   - 运行 `git diff --cached --check`。
   - 对 staged text 做 credential/private-path/personal-data 检查；对 GIF、截图、trace、fixture 等媒体或证据做人工隐私检查。
   - 再次确认 staged paths 只属于本 slice；不得顺手带入继承的 dirty changes。
   - 测试默认运行整个 working tree。若 inherited unstaged changes 会进入同一 import、build、fixture、configuration 或 runtime path，focused test 不能独立证明 staged snapshot；此时必须隔离验证 staged patch，或停止 commit 并报告依赖。
   - 如果暂存后内容可能影响验证结果，重新运行 focused tests。
5. **创建 checkpoint**
   - 使用简洁 conventional message，例如：
     - `feat(runtime): add agent intent contract`
     - `test(runtime): reject coordinate injection`
     - `fix(gate): block stale observation`
     - `docs(runtime): record verified contract boundary`
   - 不使用 `--no-verify`，不自动 amend 已有 checkpoint。
6. **验证 checkpoint**
   - 记录 `git rev-parse HEAD`、message、功能和实际测试结果。
   - 用 `git show --check --stat HEAD` 检查提交。
   - 确认 unrelated dirty work 仍在 worktree 中且未进入 commit。
7. **继续或停止**
   - 如果下一 slice 已批准，直接继续；不要为每次 commit 重新询问。
   - 遇到冻结公共 API、安全权限、不可逆迁移或测试无法变绿时才停止。

## Baseline checkpoint exception

用户明确要求为继承的 dirty tree 建立回退点时，可以创建一个非原子但范围明确的 baseline commit，例如：

```text
chore(repo): checkpoint <scope> baseline
```

创建前仍必须：

- 完整 inventory tracked/untracked/ignored 状态；
- 记录用户要求纳入 baseline 的明确范围；范围不清时不能借 baseline 名义吸收所有 dirty files；
- 排除缓存、模型、日志、临时输出和未批准的个人数据；
- 运行覆盖 baseline 实际内容的 focused/combined tests；
- 检查 staged diff 和敏感数据；
- 在报告中明确它是历史基线，而不是单功能 feature commit。

Baseline 是显式例外；后续立即恢复 per-slice atomic commits。

不要默认创建 stash/tag/bundle/额外分支来“增强安全”。只有用户要求额外备份，或当前 Git 状态确实无法安全形成 commit 时才增加这些机制。流程本身不应比改动更复杂。

Focused tests 可以证明单个 checkpoint，但不能自动证明整个 release。仓库 DoD、多个 slice 的 integration gate、merge/push 前检查或用户明确要求 full regression 时，仍应运行对应 combined/full suite；最终报告必须区分“checkpoint verified”和“repository/release verified”。

## Rollback boundary

每个 commit hash 本身就是回退点。默认只报告安全选项，不自动执行回退：

```text
Inspect:  git show <commit>
Compare:  git diff <commit>..HEAD
Undo:     git revert <commit>
Branch:   git branch recovery/<name> <commit>
```

执行 `git revert`、切换分支或创建恢复 worktree 前，重新检查 dirty state；发生冲突时停止并报告，不覆盖用户文件。

## Forbidden shortcuts

在本 Skill 的自动 checkpoint 流程中绝不执行下列 destructive 或 history-rewriting 操作。若用户另行要求其中任一操作，停止 checkpoint 流程并将其作为独立任务处理；不得把它作为 checkpoint 的实现细节：

- `git reset --hard`
- `git clean`
- 强制 checkout/restore 覆盖工作树
- rebase/history rewrite
- `git push --force`
- `git push --force-with-lease`
- 自动 push

不要用 WIP commit 冒充测试通过的完成 checkpoint。用户明确要求保存失败现场时，可以创建清楚标记的 WIP commit，但它不能计入已完成 slice。

## Final report ledger

最终报告至少列出：

| Commit | Message | Slice | Verification |
|---|---|---|---|

并补充：

- 未 push 的事实；
- 当前 worktree 是否干净；
- remaining dirty files 属于什么；
- 下一 slice；
- 从哪个 commit 恢复或使用 `git revert` 的方法。
