# OCR 字段裁剪：原型与接入记录 / OCR field crops: probe and integration

2026-10-12，未发布。源码接入已完成，Main最终22个相关模块536项离线回归通过（18.99s，0失败/跳过），包含44项OCR检查。另完成一次保留截图的正式provider真实API诊断，0桌面动作、0浏览器缓存修改。本增量之后已追加一次完整浏览器3/3通过，详见文末；之前同会话双轮失败仍保留，单轮不等于连续通过。 / Unreleased source integration passed Main's final 536 checks across 22 modules, including 44 OCR checks. One production-provider API replay used a retained frame with no desktop actions or cache mutations. One subsequent full browser run passed3/3 (see below); this does not replace the earlier failed continuous acceptance.

## 当前行为 / Current behavior

- 新视觉Choice `after_click` 使用本地RapidOCR检查未标注原图中的完整字段及四周16px padding裁剪；Decision只审核实际点击标记处是否为可输入目标，不再发送 `field_content` 问题。 / Local OCR checks the unmarked full field with 16px padding; Decision checks target usability without a field-content question.
- 字段审核每帧只上传一张带实际点击标记的字段裁剪图；完整原图、source SHA、原窗口/进程身份、点击坐标与裁剪映射本地保留。候选和无字段结果仍使用各自图像合同，标记不证明当前焦点。 / Each field frame uploads one marked crop; full source bytes, hashes, identity and coordinate transforms remain local. Candidate/outcome contracts remain separate; a marker is not focus proof.
- 检出文字保守记 `nonempty`，可能是占位符、按钮或图标，不冒称真实输入值。无检测不直接空：仅剔字段2px边框后，完整内侧每像素同色且非透明才记 `empty`；其余 `uncertain`，不裁掉两端可能内容。引擎/解析/绑定错误不能证明空。 / Detected text is nonempty conservatively and may be a placeholder/control/icon. No detection proves empty only when the complete interior, excluding a 2px border, is one opaque color; otherwise uncertain. Errors never prove empty.
- 严格空框跳过Ctrl+A；nonempty/uncertain且原 `clear_existing=true` 使用既有授权替换，仍检查selection与输入后value。False未证明空时不得直接输入。 / Proven empty skips Ctrl+A. Nonempty/uncertain may use originally authorized replacement with selection/value checks; no-clear cannot type without empty proof.
- 新 `visual_typing_strategy.v2` 绑定本地OCR与原请求/实际策略；field_content v1仅保留历史认证兼容。输入后仍由Decision只比较目标显示与expected_text，不检查焦点。阈值、身份/窗口、输入门禁、取消/期限和不重放规则未放宽。 / Strategy v2 binds OCR and the original/effective behavior; v1 remains historical authentication. Post-input Decision compares expected text only. Thresholds, bindings, input gates, stops and no-replay remain unchanged.

## 本地原型 / Local probe

使用现有OCRService与已安装RapidOCR，没有安装依赖、联网或GUI动作。最终21个真实裁剪对照及6个合成案例各运行两次；合成案例不是实机验收。保留原图在裁剪前核对hash。 / Existing OCRService/RapidOCR ran 21 real crops and 6 synthetic cases twice each without installation, networking or GUI actions; synthetic cases are not live acceptance.

| 保留案例 / Retained case | 实际识别 / Observed result | 限制 / Limit |
| --- | --- | --- |
| 地址栏原框 `(77,43,986,33)`，padding4px | `https://www.java.com/zh-CN/`，confidence0.9714 | 本例读对不代表通用精确读值 / Correct here only |
| 同轮真实空Google搜索框 `(281,456,688,53)` | 图标`+一`及按钮`AI模式` / Icon and button text | 空值可能被保守记nonempty / Empty values can look nonempty |
| 同框真实java输入后 | `+javal`；手工文字内区仍为`javal`，confidence0.9956 | 光标可能成为字符，高confidence不等于精确OCR / Caret confusion despite high confidence |
| 合成小字符`i`、`.`、8px `x` | 无检测 / No detection | 无检测不能单独证明空 / No detection alone is insufficient |
| 合成占位`Search` | 高confidence检出 / High-confidence detection | OCR不识别实际值与占位语义 / Placeholder semantics unresolved |

手工文字内区裁剪仅用于诊断；不能裁掉字段两端潜在内容来制造empty。原型首进程引擎准备1109.648ms，第二进程502.939ms（系统模型缓存可能影响）；复用获取0.001/0.002ms不等于OCR识别耗时。复用识别通常约200–330ms，场景并非严格对照。 / Manual text interiors are diagnostic only. Engine preparation was1109.648/502.939ms in two processes; reused getter timings are not recognition latency. Typical reused recognition was about 200–330ms without controlled benchmarking.

证据 / Evidence：[原型报告](../../.superpowers/sdd/2026-10-12-ocr-field-content/REPORT.md)、[脚本](../../.superpowers/sdd/2026-10-12-ocr-field-content/probe_rapidocr_fields.py)、[完整结果](../../.superpowers/sdd/2026-10-12-ocr-field-content/results.json)、[首批结果](../../.superpowers/sdd/2026-10-12-ocr-field-content/results-initial.json)。

## 正式单请求诊断 / One production-provider replay

同一旧误拒网址截图（source SHA `6ef62d4dd7ce977d5865131b68dde7abd2f7254aa396ecee63a83275feb3ac05`）从1249×1372整图裁至1018×65，crop `(61,27,1018,65)`。正式helper本地OCR读出 `https://www.java.com/zh-CN/`、状态nonempty，冷调用1171.168ms。 / The same retained failure frame was cropped to1018×65 at(61,27), with its full source hash retained. Local OCR read the correct URL as nonempty in1171.168ms on this cold call.

实际API共1次：`current_step=condition_met`，confidence 0.96，三选项概率依次为0.97/0.01/0.02（met/not_met/insufficient）；1031 tokens。HTTP总5567.8646ms，server_processing4118.0ms；旧误拒请求314.7928ms，不能声称提速。裁剪、移除空框问题与选项语义收窄同时发生，不能证明裁剪是结果变化的单一原因。 / One API call returned met with confidence 0.96 and probabilities 0.97/0.01/0.02, using 1031 tokens. Total HTTP time 5567.8646ms exceeded the earlier 314.7928ms; server processing was 4118.0ms. Crop and question/choice changes occurred together, so neither speed gains nor crop-only causality are established.

诊断在最后新增 `error_detail` 成功值null字段之前运行，该字段不改变图像或请求语义；不得把此API结果称为完整最终候选实机验收。 / The replay preceded the final successful-null error_detail field, which does not change images/request semantics; it is not full live acceptance of the final candidate.

证据 / Evidence：[formal-summary.json](../../.superpowers/sdd/2026-10-12-ocr-field-content/formal-summary.json)、[single-live-response.json](../../.superpowers/sdd/2026-10-12-ocr-field-content/single-live-response.json)、[正式请求导出](../../.superpowers/sdd/2026-10-12-ocr-field-content/formal-request-export/)。

## 最终离线检查与未完成项 / Final offline checks and limits

Main记录最终22模块536 passed in18.99s，0skip/0fail；XML含44项OCR检查，源码mtime早于suite启动。[最终读回](../../.superpowers/sdd/2026-10-12-ocr-field-content/final-verification-readback.json)与[源码hash](../../.superpowers/sdd/2026-10-12-ocr-field-content/final-source-hashes.json)保留。该结果是离线回归，不转换为浏览器实机通过。 / Main recorded the final 536 passing checks, including 44 OCR checks, with source timestamps preceding suite start. Readback and source hashes are retained; these are offline results.

下一步覆盖同会话连续使用；文末已追加一次完整Google网址→java搜索→首个普通链接及正常收尾，尚不能证明连续稳定。之前[两轮失败与清理](EXECUTION_TWO_ROUNDS_20261012.md)不改记成功。源码未发布、安装器未更新；资料目录与缓存未清理。 / A subsequent full run and cleanup are recorded below. Next validate continuous use of the retained isolated profile; the prior failure remains. Source is unreleased, the installer unchanged and profile/cache retained.

## 追加完整流程：单轮3/3通过 / Subsequent complete flow: one run passed3/3

用户于2026-10-12要求再次完整流程后，使用同一冻结源码及原独立Edge profile，新宿主单会话自动完成Google网址输入→java搜索→首个普通链接，抵达 https://www.java.com/zh-CN/，主内容可见。每步verdict=success、original_input_status=completed，未请求Main接管；翻译提示弹窗没有妨碍最终结果判定。维护接口截图已由Main查看。 / On the renewed user request, the frozen source and retained isolated profile completed all three steps automatically in one new host session, reaching the visible Java homepage. Each step succeeded with completed original input and no Main intervention. A translation prompt did not prevent final result validation; Main viewed the maintained-interface capture.

原请求阈值配置逐字节保持一致。地址栏OCR为about:blank；Google框OCR检出图标及AI模式文字，因此两次都是visual_typing_strategy.v2/nonempty/replace_existing，均经过原有选区和值检查。不能把本轮成功计为空框直接输入已验证。 / The threshold profile remained byte-identical. OCR read about:blank and detected Google controls/icons; both inputs used nonempty/replacement with existing selection/value checks. The empty-field fast path was not used.

宿主cleanup_verified=true；只正常关闭本轮身份一致的Edge窗口，window_closed=true/profile_preserved=true，无强杀或删除缓存。记录：D:/AgentReviewAcceptance/native-focus-geometry-20261012-ocr-crop-08/flow-result.json、final-summary.json、host-cleanup.json、isolated-browser-cleanup.json、source-freeze.json。本轮只运行一次；此前双轮失败保留，连续稳定性仍未通过。 / Host and owned-window cleanup succeeded without forced termination or profile/cache deletion. This was one run; the historical two-round failure remains and continuous reliability is unproven.
