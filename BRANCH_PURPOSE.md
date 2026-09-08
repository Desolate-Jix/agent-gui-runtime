# 分支用途 / Branch purpose

## 用途 / Purpose
模型接入协议、GUIActor 运行环境及存储约束。

Provider protocol, GUIActor runtime and model storage constraints.

## 状态 / Status
已合入；旧验收输入路径尚需解除 / Merged; legacy acceptance input paths still need decoupling

这是旧源码归档，不是正式版已验收的声明。
This is an archival source branch, not a claim of formal release acceptance.

## 来源 / Source
- 原分支 / Original branch: `codex/simple-provider-protocol-v1`
- 原提交 / Original commit: `499c1beb857e64363fd94f066ba6c4789c4da1b5`
- 归档日期 / Archive date: 2026-09-08
- 提交历史完整保留；本次仅新增说明，不改旧功能。
  Commit history is retained; this update adds documentation only.

## 测试范围 / Test scope
用途依据来源分支的提交与集成记录。本次只核验 Git 对象和远端可恢复性，没有重新运行旧实验，也不把旧实验结论当正式版验收。
Purpose is based on source commits and integration records. This operation verifies Git object integrity and remote recoverability only; it does not rerun historical experiments or promote them to formal acceptance.

## 开发入口 / Development entry
后续日常开发使用本地 `codex/开发-native-desktop`。原生正式版未提交的代码、模型、当前审核历史和工作副本数据不由本归档新增上传。
Continue day-to-day development on local `codex/开发-native-desktop`. Uncommitted native implementation, models, current review history and working-copy data are not newly uploaded by this archive operation.
