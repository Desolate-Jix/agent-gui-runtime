# 普通外部视觉 API 单次评估 / Ordinary external vision API benchmark

`scripts/benchmark_external_vision.py` 复用 `ChatCompletionsGrounder`，只对给定 PNG 做图像定位。它不采集桌面、不执行动作、不启动本地模型或修改生产识别配置。正常识别继续使用既有 `local` 配置；外部 API 只用于这次显式评估。 / The script reuses the existing adapter to ground supplied PNGs. It does not capture the desktop, dispatch input, start models, or change production configuration. Normal recognition retains its existing local configuration.

普通图像定位使用 Chat Completions，并非 Decisions API。官方 [GPT-6 Luna 文档](https://developers.openai.com/api/docs/models/gpt-6-luna) 支持图像输入和 Chat Completions。[配置示例](../../configs/vision-api-openai-luna.example.json) 明确使用 `gpt-6-luna` 和 `OPENAI_API_KEY`，不指定 `reasoning_effort`，因此沿用供应商默认级别；结果将该字段记为 `null`，不能视为 `none` 或 `low`。 / Ordinary grounding uses Chat Completions, separately from Decisions. The example selects the requested model and key environment variable while leaving reasoning effort unspecified; recorded `null` means the provider default, not a reduced effort.

密钥只从当前进程环境读取，沿用 Decisions 的 `api_key_env` 机制。不要把密钥放在 profile、manifest、命令参数或报告中。脚本不寻找或修改凭据文件。 / Credentials come only from the named process environment variable, using the same mechanism as Decisions. Do not put secrets in profiles, manifests, arguments, or reports. The script does not locate or modify credential files.

## 输入 / Input

每案必须有本轮新采集的安全截图，以及由模型以外的来源独立提供的目标真值。`truth_source` 说明来源；截图时间由采集者提供，脚本只校验 UTC 格式，不证明采集过程或真实性。真实 PNG、sha256、尺寸及 capture ID 冲突在任何请求前检查。 / Supply fresh safe captures and independently established truth. The collector supplies provenance and timestamps; validation establishes file integrity, not collection authenticity.

```json
{
  "schema_version": "external_vision_benchmark.v1",
  "suite_id": "luna-fresh-20261008",
  "truth_source": "Independent Qt widget geometry mapped to captured client pixels",
  "cases": [
    {
      "case_id": "default-inspect-button",
      "goal": "Locate the Inspect button.",
      "capture": {
        "capture_id": "fresh-default-1",
        "image_path": "C:/fresh-captures/default.png",
        "sha256": "REPLACE_WITH_64_LOWERCASE_HEX_CHARACTERS",
        "image_size": {"width": 1000, "height": 800},
        "captured_at_utc": "2026-10-08T00:00:00Z"
      },
      "truth": {
        "status": "found",
        "bboxes": [{"x": 100, "y": 200, "width": 120, "height": 40}]
      }
    }
  ]
}
```

`found` 必须有 1 个 bbox；`absent` 使用空列表；`ambiguous` 必须有至少 2 个不同 bbox。坐标均为原始 PNG 像素，目标须在图内。相对图片路径按 manifest 所在目录解析。同一个 capture ID 可供不同问题复用，但其 hash、尺寸和采集时间必须一致。`truth`、`truth_source`、bbox 和 case ID 不会作为真值提示发送给模型。 / Found requires one box, absent none, and ambiguous at least two distinct boxes. Coordinates use original PNG pixels. Relative image paths resolve against the manifest directory; reused capture identities must agree. Independent truth never enters the model request.

## 运行 / Run

默认仅离线预检，不读取密钥、不创建结果文件、不联网： / Default preflight is offline and does not read credentials, create results, or call the network:

```powershell
python scripts/benchmark_external_vision.py --manifest C:/fresh-captures/manifest.json --profile configs/vision-api-openai-luna.example.json --max-calls 12
```

显式执行每案 1 次请求，串行且无自动重试；`--max-calls` 默认 12，允许 1–32，超出限制先拒绝。已有输出文件会在请求前拒绝，避免覆盖首次结果。每案结果立即保存，中断不会把之前的首次失败改记为成功。 / Explicit execution makes one serial request per case without retry. The cap defaults to 12 and permits 1–32. Existing output files are rejected before requests; each completed case is persisted immediately.

```powershell
python scripts/benchmark_external_vision.py --manifest C:/fresh-captures/manifest.json --profile configs/vision-api-openai-luna.example.json --output C:/fresh-captures/benchmark-first.json --max-calls 12 --execute
```

退出码 0 表示离线预检通过或所有执行案例通过；1 表示已完成评估但有失败；2 表示输入、配置、凭据或输出错误。重跑使用新文件，并保留原始报告。 / Exit 0 means valid preflight or all cases passed, 1 means completed with failures, and 2 means input, profile, credential, or output errors. Reruns require new outputs and retain the original report.

## 结果边界 / Result interpretation

- `classification_accuracy` 包含所有已完成案例，网络/协议失败计为错误。唯一目标同时报告选中 bbox 的 IoU 与点击点是否落在独立真值中；默认 IoU ≥ 0.5 才通过 bbox。`found_bbox_accuracy` 和 `found_click_accuracy` 的分母含唯一目标案例的请求失败。 / Classification includes request failures. Found reports selected-box IoU and independent click containment, using a 0.5 IoU threshold; failed found requests remain in the denominators.
- `ambiguous` 只有状态正确且候选 bbox 与真值一一匹配才通过，不能用重复候选补满数量。此状态没有选中点击；任何案例均不执行点击。 / Ambiguity requires matching classification and one-to-one box coverage, without duplicate counting or a selected click. No case executes input.
- `end_to_end_ms` 包含适配器本地校验、请求和解析；`http_elapsed_ms` 只覆盖实际 HTTP 请求/响应读取；`server_processing_ms` 仅在供应商提供有效 `openai-processing-ms` 时存在。缺失 timing 或 usage 保持 `null`，不可用端到端耗时冒充服务器推理时间。p50 使用中位数，p95 使用最近秩。 / End-to-end includes local validation and parsing; HTTP timing covers transport; server timing depends on a valid provider header. Unknown values remain null. Percentiles use median and nearest rank.
- 报告保留供应商返回的允许 token 计数及 cached/reasoning 明细，并保留请求身份。原始模型文本、UTF-8 prompt、解析 JSON 和解析错误仅由 benchmark 显式启用诊断 trace；截图以路径/hash 绑定，不在 trace 重复嵌入 base64。已知密钥精确脱敏；生产适配器默认关闭该 trace。 / Reports retain available token details and request identity. The benchmark alone opts into UTF-8 prompt, raw model text, parsed JSON, and parse-error traces, with known credentials redacted and images bound by path/hash.
- 单轮受控布局评估只能说明该组截图/目标的表现。它不是连续执行验收、真实网页泛化、提速、费用或日常稳定性证明；API 网络及图像服务可用性也不改变输入授权门禁。 / Controlled fixtures establish only this sample's performance, not continuous execution, web generalization, speedup, cost, or daily-use stability. API availability grants no input authorization.

## 2026-10-08 本轮受控结果 / Controlled result for this run

Main 使用全新原生 RecordDesk 窗口的 3 张布局截图，每张提出 2 个唯一目标、1 个不存在目标、1 个重复按钮歧义问题，共 12 次普通 `gpt-6-luna` 请求，推理级别未显式指定。独立真值由 Qt 控件几何映射到项目 `ScreenshotService` 的原图像素取得，不传给模型。 / Main evaluated three fresh native RecordDesk layout captures with two unique targets, one absent target, and one ambiguous duplicate-button target each. Independent Qt geometry was mapped into maintained screenshot pixels and withheld from the model; reasoning effort remained unspecified.

该受控集合的 12 例均满足分类和对应几何标准：6 个唯一目标的选中 bbox 达到 IoU ≥ 0.5，点击点都落在真值内；3 个不存在目标和 3 个歧义案例均正确。端到端 p50 为 **2937.394 ms**、p95 为 **5118.273 ms**（n=12）；供应商处理时间 p50 为 **2537 ms**。返回模型均为 `gpt-6-luna`，合计 **15873 输入 / 3214 输出 token**。这是该组小样本的通过记录，不是通用识别准确率结论。 / All twelve cases met this controlled set's classification and geometry criteria. Six unique targets met the IoU threshold and click containment; three absent and three ambiguous cases classified correctly. End-to-end p50/p95 were 2937.394/5118.273 ms, provider p50 was 2537 ms, and usage totaled 15873 input/3214 output tokens. These are small-sample results, not a universal accuracy claim.

证据保存在 `D:/AgentReviewAcceptance/ordinary-luna-vision-20261008-01/summary.json`；`probe-first.json` 和 `remaining-first.json` 保留各案首次结果，无自动重试或覆盖。第一案 probe 在可选诊断 trace 补丁前执行，只有结构化定位、耗时和 usage，没有 raw model trace；之后的 11 案有 trace，不追溯补造第一案原文。所有定位点击点仅作离线几何评估，未真实执行。Main 已核对本地宿主 `recognition_source=local`、`api_profile=null`；此次没有修改生产默认配置。 / Original first-attempt reports remain beside the summary. The first probe predates optional raw tracing and retains only structured output and measurements; its missing raw text is not reconstructed. The remaining eleven cases include traces. No API-selected click was executed. Main verified the host remains local with no API profile, without a production configuration change.
