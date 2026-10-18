# 安装版终态回执读取占用 / Installed terminal-receipt read lock

2026-10-07。发布前第一批 source12/GUI10 安装成功，实装载荷核对通过；实际教学第二次点击已完成，但学习事件未保存。该批仍记失败，不能以源码检查代替新的实装连续验收。 / The first source12/GUI10 pair installed and matched its payload manifests. Its second teaching click completed, but the learning event was not saved. This installed batch remains failed; source tests cannot certify the replacement installed pair.

1. **失败 / Failure**：`flow-009-back` 的原始 job 为 completed、action_executed=true；learning status 在 async_terminal 阶段记录 PermissionError，随后查询事件为 FileNotFoundError。没有重复点击。 / The original job completed with input executed, while async-terminal learning reported PermissionError and no event. Input was not replayed.
2. **公共约束 / Invariant**：短暂的 Windows 文件读取占用不能让已完成动作的终态回执丢失。真实 CreateFileW 排他占用复现中，Path.read_bytes 返回 errno=13、winerror=None；占用句柄的实际来源尚未知。 / A transient read lock must not lose a completed action receipt. A real exclusive Windows file handle reproduced errno=13 with no winerror; the original holder remains unidentified.
3. **修复 / Fix**：`app/core/json_snapshot.py` 对 Windows sharing/access-denied 读取最多重试 0.5 秒，每次间隔 10 ms，始终读取原路径；解析、缺失文件、其他 I/O 和非 Windows 错误不重试。持续拒绝仍抛原错误。 / The common reader retries only Windows sharing/access-denied reads on the original path for at most 0.5 seconds, at 10 ms intervals. Parsing, missing files, other I/O and non-Windows failures are not retried; persistent denial still raises the original error.
4. **通用性 / Reuse**：修复共同 JSON 快照边界，适用于其他应用的异步回执；未加入应用专属点击或旧快照回退。 / The shared snapshot boundary covers other asynchronous receipts without app-specific actions or stale-snapshot fallback.
5. **回归 / Regression**：实锁 RED 为 3 failed / 7 passed；修复后 Main 重跑 `tests/test_json_snapshot.py tests/test_learning_async_receipts.py` 为 13 passed，独立只读审查单文件 11 passed。新安装版教学、连续使用和正常清理尚待复验。 / Real-lock RED retained 3 failures and 7 passes. Main's repaired snapshot/learning-receipt suite passed 13 checks; independent read-only review passed 11 snapshot checks. Replacement installed teaching, continuous use and cleanup remain pending.
6. **安全 / Safety**：不重放输入、不改等待优化策略、不放宽识图或动作门禁；持续失败仍显式报告。 / No input replay, wait-policy change or weaker grounding/action gates; persistent failure stays visible.

原始 job、learning status、首失败、实锁复现、修复日志及源码 SHA 在本地发布证据目录保存，不上传用户库或原始截图。旧测试安装器和重复 ZIP 已按用户要求删除，manifest 与失败日志保留。 / Original jobs/status, first failure, lock reproduction, repair logs and source hashes remain in local release evidence. Superseded test installers/ZIPs were removed as requested, with manifests and failure logs retained.


## 2026-10-07 第三批实装复验 / Third-pair installed retest

pair03/source14/GUI12 的 Main 教学、连续使用、工作台保存后截图、正常重开与清理通过；Sol 在同一冻结载荷上用独立新数据复验通过，Main 已核对原始回执与图片。详见 [最终安装验收](LEARNING_PREVIEW_RELEASE_ACCEPTANCE_20261007.md)。上面的首次失败及原因未知项仍保留，后续通过不改写原失败。 / Main passed teaching, continuous use, Save post-capture, normal reopening and cleanup on pair03/source14/GUI12. Sol passed independent fresh-data acceptance on the same freeze, and Main audited the original receipts and images. See the final installed-acceptance report. Original failures and unknown causes above remain unchanged.
