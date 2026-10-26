# Amadeus connector 0.0.5 — author validation

[简体中文](#简体中文) · [Setup](../../integrations/amadeus/agent-review-instant/README.md) · [Review feedback](https://github.com/Desolate-Jix/agent-gui-runtime/issues/4)

Date: 2026-10-26, Pacific/Auckland. This is the author's submission evidence,
not independent store approval. The Runtime remains **0.1.8**; connector releases
are separate. No Runtime installer or existing 0.0.4 artifact is replaced.

## Exact artifacts

[Release and all reports](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/amadeus-extension-v0.0.5)

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `amadeus_agent_gui_runtime-0.0.5-py3-none-any.whl` | 24,635 | `9727889c378354ee6b24648c94b2276b8ed30d986b49d1dd4b0f5c3c188774dd` |
| `extension-source-0.0.5.zip` | 48,737 | `93e78d5a008df6d4c5fbb35a237fc9517269d5ebbc6c461beabdc667095cd53f` |

The release also supplies `preflight.json`, `wheel-inventory.json`,
`candidate-diff-from-0.0.4.json`, `BUILD_VERIFICATION.json`,
`AUTHOR_VALIDATION.json` and `SHA256SUMS.txt`.

## Changes and reproducible static checks

0.0.5 adds the connector identity, external deployment/configuration/lifecycle
disclosure, homepage/repository links and synchronized package README/METADATA,
English/Chinese guides and Skill reference. Configuration keys, permission
declarations, HTTP transport and execution authority are unchanged. Runtime code,
thresholds and model defaults are unchanged. No 0.0.3/0.0.4 connection-setting
migration is needed. The 0.0.4 comparison is against a retained candidate,
**not a previously approved catalog package**.

Two offline builds used CPython **3.12.10**, setuptools **83.0.0** and wheel
**0.47.0**, with a fixed `SOURCE_DATE_EPOCH`; their wheel bytes matched.
Wheel RECORD hashes, purelib/`py3-none-any`, empty effective dependencies,
packaged-resource/source equality, UTF-8 README content in METADATA (with
normalized line endings), and source ZIP contents passed readback.

The author preflight used the unchanged catalog tools at
`3c739e1a5c177d585db3ed63868725dae5cadc32`, fixed Host
`1840c8e4f646992ddaebea3139c8895f29743a8f`, Windows and CPython **3.12.10**.
Its minimal dependency lock SHA-256 is
`eca122787362dc7d39b309b931c5e17ce7fb0507f79524589f2978bb018c17e7`.
Package format, target Host and curated policy passed; the original report
correctly retains `review_status: not_reviewed` and human/runtime review pending.
The checker reads package bytes without installing or importing the connector.

```powershell
python tools/preflight_submission.py --wheel <exact-0.0.5-wheel> --host <fixed-1840c8e-checkout> --python <minimal-3.12.10-python> --output preflight.json
python tools/check_catalog.py --wheel <exact-0.0.5-wheel> --previous-wheel <retained-0.0.4-wheel> --output candidate-diff-from-0.0.4.json
```

The two existing package contract checks passed separately against the fixed
Host and current Amadeus main `b6616a166925963ad6de4ab0a02f4eef2dccd657`:
installed manifest/Skill validation and native HTTP projection with a synthetic
secret. Each Host passed **2 checks, 0 skipped**. The same two cases are not
reported as four distinct coverage areas. These are static/projection checks,
not a new native Pi installation.

## Source Runtime 0.1.8 HTTP check

Production `InstantSession` and the SDK HTTP server were exercised on Windows /
CPython 3.12.10, using Runtime source base
`654fe148c0492feed2b01ec643597ea006b6a8c6`. Only connector/documentation changes
were present. This was a source run, not a fresh installed Runtime/Pi GUI run.

- Initialize reported Runtime **0.1.8**; nine tools and their generic
  action-review, visual-field-evidence and original-command continuation surfaces
  were discovered. Dedicated review-packet generation was **not exercised**.
- Seven authentication/Host/Origin negative cases were rejected before an owner
  was created. Failed initialization, competing/wrong/missing owners and an
  unsupported sessionless protocol did not bypass ownership checks.
- Two actual child-host rounds completed start → ready → stop →
  `cleanup_verified=true` → HTTP DELETE/release → reconnect. Deleting a live
  host's session was refused without stopping it; old owner IDs were refused
  after release. Both hosts exited and both listeners closed.
- The explicit lifecycle-only test authorization satisfied the existing
  local-input startup gate. A separate test without it returned
  `local_input_not_enabled` without launching a host. No GUI commands,
  screenshots or model-triggering commands were submitted; each queue contained
  only `close`. The API profile used a dummy credential and a closed loopback
  endpoint, and Decision remained off. No real model-service request was made
  by this harness; this establishes no accuracy, latency or token-saving result.

### Maintenance-registration observation

After the two rounds and service shutdown, the first stopped session's
maintenance registration remained, even though the host had exited and its
cleanup/input proof was settled. Only the exact test-owned sessions were later
checked with the production ledger API; the retained registration was cleared
after proof validation. No unrelated registration or user configuration changed.
This does not prove immediate automatic retirement of every stopped record.

Maintenance independently calls `assert_settled(clear_settled=True)` and can
retire records after validating original evidence. Maintenance admission and an
update attempt were **not run**, and a blocked update was **not reproduced**.
Different Windows venv wrapper/runner identities are a source-based explanation,
not a captured child-side error. HTTP/host-exit checks passed within their scope;
complete lifecycle or maintenance qualification is not claimed. Do not delete
locks or registrations to work around a maintenance refusal.

## Retained nonpasses and pending work

The first HTTP attempt stopped because its closed-port probe handled
`ConnectError` but Windows returned `ConnectTimeout`; the corrected probe also
checked actual listener/thread termination. The first host-contract attempt used
an API environment missing PyYAML; reruns used the qualified minimal checker.
An initial build readback compared unnormalized METADATA line endings; a fresh
two-build run verified UTF-8 and normalized README equality. These initial results
are retained locally and are not counted as successful qualification runs.

The [installed Runtime 0.1.6 + connector 0.0.4 evidence](https://github.com/Desolate-Jix/agent-gui-runtime/blob/instant-v0.1.6/docs/verification/MAIN_PRE_ACTION_REVIEW_20261023.md)
remains a bounded, assisted TEST double-refusal/Main continuation demonstration.
It is not new 0.0.5/0.1.8 acceptance. The exact new Host/Pi/connector/Runtime
combination still needs independent installation, minimum GUI task,
missing/unreachable/incompatible service, credentials, cancellation/disconnection,
disable/uninstall and reconnection review. Physical reboot/power loss and
arbitrary third-party data migrations were not tested here.

The maintainer supplies independent approval and `catalog/packages` facts in the
submission PR, then prepares and verifies the separate publication PR. The author
does not self-approve or populate the live catalog index.

## 简体中文

本记录是 **0.0.5 作者侧投稿证据**，不代表独立商店批准。Runtime 仍为 **0.1.8**，连接器单独发行；不替换 Runtime 安装包或旧 0.0.4 产物。

- **修改范围：** 补齐连接器身份、外部部署／配置／生命周期披露、安装指南和源码链接，统一包内 README／METADATA、双语指南及 Skill 参考。配置键、权限、HTTP 传输和执行授权不变；Runtime 代码、阈值、模型默认值不变。0.0.3／0.0.4 的连接配置无需迁移。与 0.0.4 的对比是候选包之间的差异，不代表旧包已获商店批准。
- **构建与固定预检：** Python 3.12.10、setuptools 83.0.0、wheel 0.47.0 的两次离线构建字节一致；RECORD、纯 Python wheel、空依赖、源码资源、METADATA 内 README 和源码 ZIP 均核对通过。固定 Host `1840c8e`、Windows／Python 3.12.10 预检的包格式、Host 和目录政策通过，独立人工／运行审核仍 pending，原报告保留 `not_reviewed`。该检查不安装或导入连接器。
- **Host 静态合同：** 固定 Host 和 Amadeus main `b6616a1` 各通过相同的两项检查，均无跳过：manifest／Skill 资源校验，以及带合成密钥的原生 HTTP 投影。不将重叠用例相加为不同覆盖领域，也不冒充新 Pi 安装态验收。
- **源码 HTTP 联调：** Runtime 0.1.8 源码基线 `654fe148`，使用生产会话和 SDK HTTP 服务。初始化版本、九个工具、通用审核／继续入口、七项鉴权／Host／Origin 反例及所有者隔离通过。两个真实子宿主完成启动、就绪、停止、清理、DELETE 释放和重连；活动宿主的直接 DELETE 被拒绝，释放后的旧 owner 失效，宿主和监听器均退出。没有触发两类专用审核 packet。
- **输入及模型边界：** 本轮明确授权的测试开关只用于宿主生命周期；未授权反例在启动前被拒绝。队列只有 `close`，未提交 GUI、截图或模型触发命令；API 使用无效的合成凭据和已关闭本机端点，Decision 关闭。这不是新模型准确率、延迟或 token 收益结果。
- **维护登记观察：** 两轮后第一轮已停止会话的登记未立即核销，但无存活宿主或未结算输入。本轮仅用生产 API 核对并清理确切测试自有登记，没有修改其他登记或用户配置。更新器会按原证据验证并可核销已结算登记；本轮未执行维护准入或更新，未复现更新被阻止。Windows 包装进程／runner 身份差异只是源码推断，未捕获原异常。不能把人工清理算成即时自动核销或完整生命周期验收通过，不能删除锁／登记绕过拒绝。
- **保留的非通过结果：** 首轮 HTTP 探针未处理 Windows 的拒连超时；初次 Host 检查缺少 PyYAML；初次构建核对未规范化 METADATA 换行。修正各自工具／环境后重跑，原记录保留，不计作通过。
- **仍待独立审核：** 旧 0.0.4／0.1.6 的带协助恢复证据单独保留。新组合的 Pi 安装、最小 GUI 任务、未启动／不可达／不兼容服务、凭据、取消／断线、停用／卸载与重连需维护者独立验收。本轮未测物理重启／断电、任意第三方数据迁移。收录批准和 `catalog/packages` 事实由维护者在投稿 PR 中填写，索引发布另走 publication PR；作者不自批、不写正式索引。
