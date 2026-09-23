# 历史源码差异归档 / Historical source-difference archive

## 用途 / Purpose

本归档保存 `D:\AgentReviewCandidates` 中旧的 test6 前后执行模式候选目录里，无法在当前 `origin` 可达 Git 提交中找到的 40 个唯一源码 blob，以及 14 份原始 `MANIFEST.json`。它们是候选打包载荷之间的历史源码差异材料，用于保留和追溯测试候选差异；**不是可直接运行的项目或完整源码树**。

This archive preserves 40 unique source blobs absent from commits reachable from the current `origin`, plus 14 original `MANIFEST.json` files from older execution-mode candidates around test6. They are historical source-difference materials from packaged test candidates, **not a runnable project or a complete source tree**.

## 内容与复原 / Contents and reconstruction

- `blobs/<git-blob-sha1>.py`：按原始字节复制；文件名为 Git blob SHA-1。
- `manifests/`：14 份原始 manifest 的逐字节副本。
- `mapping.json`：每个 blob 的 SHA-1、SHA-256、长度及在候选目录中的相对源路径映射；另列 manifest 映射。路径均相对于 `D:\AgentReviewCandidates`，不含绝对路径或用户名。
- 要重建某个候选快照：按 `mapping.json` 对应源相对路径放置其 blob，并结合对应原始 manifest；其余已由远端 Git 归档的文件应依据 manifest 从 Git 历史恢复并逐项验证。不要将单个 blob 集合当作完整候选包。

`blobs/<git-blob-sha1>.py` contains exact original bytes; its name is the Git blob SHA-1. `manifests/` holds byte-for-byte copies of the 14 original manifests. `mapping.json` maps each blob to its SHA-1, SHA-256, size, and candidate-relative source paths; all paths are relative to `D:\AgentReviewCandidates` and contain no absolute path or username. To reconstruct a candidate snapshot, place each blob at the relative path(s) listed for that candidate and restore all other manifest-listed payloads from Git history, verifying every file. The blob collection alone is not a complete package.

## 边界 / Exclusions

本归档不包含模型、模型权重、用户数据、运行数据或失败证据，也不修改原候选目录；不包含凭证。仅归档源文件差异及原始清单。

No models or model weights, user data, runtime data, failure evidence, or credentials are included. Original candidate directories were not modified. Only source differences and original manifests are archived.
