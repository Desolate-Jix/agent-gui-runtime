# 分支用途 / Branch purpose

## 用途 / Purpose
多模型评测执行器、恢复与容量门禁。

Multi-model benchmark runner, recovery and capacity gates.

## 状态 / Status
已合入根分支 / Merged into root

这是旧源码归档，不是正式版已验收的声明。
This is an archival source branch, not a claim of formal release acceptance.

## 来源 / Source
- 原分支 / Original branch: `codex/task9-runner`
- 原提交 / Original commit: `29a8bbe83f4a01f33851f2beee93f0a8f2ab79f4`
- 归档日期 / Archive date: 2026-09-08
- 提交历史完整保留；本次仅新增说明，不改旧功能。
  Commit history is retained; this update adds documentation only.

## 测试范围 / Test scope
用途依据来源分支的提交与集成记录。本次只核验 Git 对象和远端可恢复性，没有重新运行旧实验，也不把旧实验结论当正式版验收。
Purpose is based on source commits and integration records. This operation verifies Git object integrity and remote recoverability only; it does not rerun historical experiments or promote them to formal acceptance.

## 开发入口 / Development entry
后续日常开发使用本地 `codex/开发-native-desktop`。原生正式版未提交的代码、模型、当前审核历史和工作副本数据不由本归档新增上传。
Continue day-to-day development on local `codex/开发-native-desktop`. Uncommitted native implementation, models, current review history and working-copy data are not newly uploaded by this archive operation.
