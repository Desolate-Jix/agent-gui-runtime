# Universal Evidence Interface v1（UEI v1）批准设计规范

## 1. 决议、范围与非目标

UEI v1 是 provider-agnostic 的 screen parse 证据边界：将既有 provider 输出投影成可验证、已脱敏、内容寻址的安全结果，并固定 capture artifact、source ID 与坐标来源。UEI 不是执行接口；provider、mode、证据、任何未来候选或审核资产均不能授权点击。

Milestone 1 仅实现：
1. 八类实际 JSON Schema：trusted registration、artifact ref、capture lineage、affine coordinate transform、provider manifest、screen parse request、provider safe result、provider error；
2. 采用 RFC 8785 JSON Canonicalization Scheme（JCS）内容寻址的 immutable object store 规则；
3. 三种既有静态 fixture 的纯投影：OCRResult、UIA snapshot、screen_parser_result_v1；
4. schema 与静态 projection 的离线 conformance。

Milestone 1 does not invoke a vendor runtime, add a vendor runtime dependency, or create a vendor runtime adapter. It permits only pure projection adapters that read a caller-supplied static fixture and never call a provider. It does not read or migrate historical artifacts, capture a new screen, or perform GUI, network, grounding, replay, click, or action execution.

normalization、claims、fusion、dedupe、human review、reviewed asset、health、calibration、benchmark、panel projection 均为后续里程碑，当前不得实现，也不得成为本里程碑 acceptance。

## 2. 权威边界

Provider 是 trusted local deployment registry 注册的本地实现，ID 不由协议枚举。Provider profile 是能力形状，不是质量、信任、授权或生产可用性承诺。Trusted policy authority 是本机受控配置与签名或文件权限边界，是 registration、egress、privacy、mode、payload 限额和 conformance allowlist 的唯一权威来源。

Manifest 是 provider 自述能力；request 是针对一个 capture 的受限调用。有效能力严格为：

~~~text
trusted deployment policy ∩ provider manifest ∩ screen parse request
~~~

Projection entry preconditions are a valid, already-stored immutable screen_parse_request_v1 reference and a valid, already-resolved capture_lineage_ref from that request. An unhashable or invalid request, a missing or invalid capture lineage, or an unresolved capture artifact is rejected by the caller/schema boundary as a structured outer boundary error before any provider_error_v1 or provider_safe_result_v1 exists. After these preconditions resolve, an empty capability intersection, provider fixture/result/projection schema violation, payload/privacy violation, or supplied-transform coordinate violation stores provider_error_v1 first and then stores a failed provider_safe_result_v1 that references that error. No post-precondition failure is represented as an empty success.

provider_safe_result_v1 是 UEI 内第一个可持久化的 provider 输出。真实 wire payload 不属于 UEI：若因受控调试保存，必须位于 UEI 外部的 restricted store，不能被 UEI ref、hash、面板或 error 泄露。

## 3. 内容寻址、引用与严格字段

所有 UEI JSON 均为 UTF-8；时间采用 RFC 3339 UTC。每个 immutable UEI object 必须有 content_sha256。该值必须先删除对象自身 content_sha256 字段，再对剩余 JSON 执行 RFC 8785/JCS UTF-8 canonicalization，最后计算 SHA-256 小写十六进制。

所有 immutable object reference 必须精确为：

~~~json
{"id":"non-empty stable identifier","content_sha256":"64 lowercase hexadecimal characters"}
~~~

不得只引用 ID、路径、显示名、数据库主键或标签。artifact_sha256 只表示外部 artifact bytes 的 SHA-256，不能用于 UEI JSON 内容 hash，也不能代替 immutable object reference。

All schema top-level and nested objects use additionalProperties:false, except opaque_attributes in provider_safe_result_v1. opaque_attributes is the single bounded JSON escape hatch and is recursively constrained by trusted registration limits for JSON types, total bytes, depth, array items, object properties, and string characters. Unknown fields, x_ extensions, spelling variants, and unversioned contracts are rejected everywhere else.

## 4. Provider-agnostic registration

provider_id 和 profile_id 都是 namespaced opaque string。示例：

~~~text
provider_id = local.acme.accessibility/uia
profile_id  = local.acme.accessibility/uia/screen-parse-default
provider_id = local.acme.vision/ocr
profile_id  = local.acme.vision/ocr/latin-desktop
~~~

协议没有 provider enum、vendor enum 或供应商特判。初始 UIA/OCR/OmniParser 适配器与未来 Qwen adapter 的启用，只能在受信任的本地 deployment registry 示例中表达；它们全部遵循同一个 policy、manifest、request 交集，无协议级信任、回退或授权例外。

### 4.1 trusted_provider_registration_v1

这是 local policy authority 持有的 immutable object，网页、panel、provider wire data 或普通 request 无权写入。

~~~json
{
  "contract_version": "trusted_provider_registration_v1",
  "registration_id": "registry.local/screen-parse/uia-default",
  "provider_id": "local.acme.accessibility/uia",
  "profile_ids": ["local.acme.accessibility/uia/screen-parse-default"],
  "enabled": true,
  "allowed_modes": ["Primary", "Shadow", "Assist", "Advisory", "Disabled"],
  "allowed_privacy_policies": ["minimal", "redacted_for_review", "restricted"],
  "egress_policy": "local_only",
  "wire_payload_policy": "restricted_store_only",
  "safe_payload_limits": {
    "max_json_bytes": 65536,
    "max_depth": 8,
    "max_array_items": 256,
    "max_object_properties": 64,
    "max_string_chars": 4096,
    "allowed_json_types": ["object", "array", "string", "number", "boolean", "null"]
  },
  "required_conformance_suite": "uei-v1-static-projection",
  "content_sha256": "64 lowercase hexadecimal characters"
}
~~~

profile_ids is a closed array: minimum 1, maximum 32, unique namespaced opaque profile IDs. allowed_modes is a generic mode enum and cannot alter trust, score, or authorization. egress_policy is a closed enum of local_only, disabled, and remote_allowed. remote_allowed is future-only: Milestone 1 trusted registry and rollout permit only local_only or disabled and make no network call. wire_payload_policy is restricted_store_only. A request cannot register, enable, disable, or override this object.

### 4.2 Trusted local deployment registry example（信息性）

可信 registry 可并列注册：

~~~text
local.acme.accessibility/uia
local.acme.vision/ocr
local.acme.vision/omniparser
local.acme.advisory/qwen
~~~

每个 registration 独立声明 profile、egress、privacy、mode、payload 与 conformance policy。未注册 namespaced ID 不能被 request 使用。

## 5. Artifact、capture lineage 与 affine transform

### 5.1 artifact_ref_v1

~~~json
{
  "contract_version": "artifact_ref_v1",
  "artifact_id": "artifact.capture/2026-08-21/001",
  "artifact_sha256": "64 lowercase hexadecimal characters",
  "media_type": "image/png",
  "byte_length": 481923,
  "restricted": false,
  "content_sha256": "64 lowercase hexadecimal characters"
}
~~~

artifact ref 自身是 immutable UEI object，因此有 JCS content_sha256；artifact_sha256 仅 hash 外部媒体 bytes。restricted artifact 不能将字节、路径或内容泄露至普通 error、safe result 或未来 panel。

### 5.2 capture_lineage_v1

~~~json
{
  "contract_version": "capture_lineage_v1",
  "capture_id": "capture/2026-08-21/001",
  "artifact_ref": {"id": "artifact.capture/2026-08-21/001", "content_sha256": "64 lowercase hexadecimal characters"},
  "artifact_sha256": "64 lowercase hexadecimal characters",
  "image_size": {"width": 1920, "height": 1080},
  "capture_coordinate_space": "capture_pixel_xyxy",
  "captured_at": "2026-08-21T03:14:15Z",
  "content_sha256": "64 lowercase hexadecimal characters"
}
~~~

image size 是受 policy 限制的正整数。artifact_ref 必须解析到同一 artifact object，且该 artifact 的 artifact_sha256 必须与 lineage 相同。

### 5.3 affine_coordinate_transform_v1

~~~json
{
  "contract_version": "affine_coordinate_transform_v1",
  "source_space": "image_pixel_xyxy",
  "target_space": "capture_pixel_xyxy",
  "source_size": {"width": 960, "height": 540},
  "target_size": {"width": 1920, "height": 1080},
  "scale": {"x": 2.0, "y": 2.0},
  "offset": {"x": 0.0, "y": 0.0},
  "rounding": "outward",
  "clipping": "reject_if_outside",
  "source_capture_artifact_sha256": "64 lowercase hexadecimal characters",
  "target_capture_artifact_sha256": "64 lowercase hexadecimal characters",
  "content_sha256": "64 lowercase hexadecimal characters"
}
~~~

space 仅为 screen_pixel_xyxy、window_outer_pixel_xyxy、window_client_pixel_xyxy、capture_pixel_xyxy、image_pixel_xyxy、image_normalized_xyxy。bbox 是半开 [left, top, right, bottom]，要求 left<right、top<bottom；pixel 为非负整数，normalized 为 0–1 有限数。

transform 表示 axis-aligned affine mapping：

~~~text
target_x = source_x * scale.x + offset.x
target_y = source_y * scale.y + offset.y
~~~

source/target size are positive integers; scale/offset are finite numbers. rounding is outward, nearest, or none; clipping is reject_if_outside or clip_to_target. Outward means floor(left) and floor(top), then ceil(right) and ceil(bottom). Nearest means round-half-away-from-zero independently for every edge. none is allowed only if every transformed edge is already an integer; otherwise the supplied transform is invalid and causes a coordinate error. Every resulting pixel bbox is integer-valued. A supplied transform whose hashes, lineage, dimensions, bounds, or claimed proof fail validation is a coordinate error and stores provider_error_v1 plus a failed safe result. The two artifact hashes must be equal and equal the request capture artifact_sha256 to prove the same capture mapping. Invalid size, hash, numeric value, bbox, or transformed boundary is rejected.

Identity projection exception: if source_coordinate_space is capture_pixel_xyxy and the adapter proves the source fixture is bound to the exact request capture artifact_sha256 and image_size, source_bbox may be copied byte-for-byte to capture_bbox with coordinate_transform_ref=null. For every other source space, a missing transform or non-conflicting unproven mapping returns a successful provider_safe_result_v1 with review_only=true, source_bbox when safe, capture_bbox=null, and coordinate_transform_ref=null. Absence of a transform is not an error. Only a supplied malformed, lineage-conflicting, out-of-bounds, or falsely proof-claiming transform is a coordinate error.

## 6. Milestone 1 schemas

### 6.1 provider_manifest_v1

~~~json
{
  "contract_version": "provider_manifest_v1",
  "manifest_id": "manifest.local.acme.accessibility.uia/1.0.0",
  "provider_id": "local.acme.accessibility/uia",
  "provider_version": "1.0.0",
  "profiles": [{
    "profile_id": "local.acme.accessibility/uia/screen-parse-default",
    "operation": "screen_parse",
    "input_contract": "screen_parse_request_v1",
    "output_contract": "provider_safe_result_v1",
    "declared_output_kinds": ["element", "text", "role", "state"],
    "supported_coordinate_spaces": ["window_client_pixel_xyxy", "capture_pixel_xyxy"],
    "supports_capture_artifact": true,
    "privacy_capabilities": ["minimal", "redacted_for_review"],
    "mode_allowlist": ["Primary", "Shadow", "Assist", "Advisory", "Disabled"]
  }],
  "content_sha256": "64 lowercase hexadecimal characters"
}
~~~

profiles 最少 1、最大 32、profile_id 唯一。declared_output_kinds 是 unique closed array，成员为 element、text、role、state、icon、structure。manifest 不得有 score、trust、authorization、click point、action 或 egress 字段。

### 6.2 screen_parse_request_v1

~~~json
{
  "contract_version": "screen_parse_request_v1",
  "request_id": "request/2026-08-21/001",
  "capture_lineage_ref": {"id": "capture/2026-08-21/001", "content_sha256": "64 lowercase hexadecimal characters"},
  "requested_profiles": [{
    "provider_id": "local.acme.accessibility/uia",
    "profile_id": "local.acme.accessibility/uia/screen-parse-default",
    "mode": "Shadow"
  }],
  "privacy_policy": "redacted_for_review",
  "requester_id": "observe_operation_service",
  "content_sha256": "64 lowercase hexadecimal characters"
}
~~~

requested_profiles 是 closed array，最少 1、最大 32，每对 provider_id/profile_id 唯一；元素仅含 provider_id、profile_id、mode。mode 只能是 Primary、Shadow、Assist、Advisory、Disabled。profile 必须同时存在于 registration profile_ids 和 manifest profiles，mode/privacy 必须同时被 registration 与 manifest 允许。request 不能加入 provider options、payload 限额、egress、score、calibration 或 action options。

### 6.3 provider_safe_result_v1

provider_safe_result_v1 是边界 redacted 的第一个 durable provider 输出。

~~~json
{
  "contract_version": "provider_safe_result_v1",
  "result_id": "result/2026-08-21/001",
  "request_ref": {"id": "request/2026-08-21/001", "content_sha256": "64 lowercase hexadecimal characters"},
  "requested_provider_id": "local.acme.accessibility/uia",
  "requested_profile_id": "local.acme.accessibility/uia/screen-parse-default",
  "registration_resolution": "resolved",
  "manifest_resolution": "resolved",
  "registration_ref": {"id": "registry.local/screen-parse/uia-default", "content_sha256": "64 lowercase hexadecimal characters"},
  "manifest_ref": {"id": "manifest.local.acme.accessibility.uia/1.0.0", "content_sha256": "64 lowercase hexadecimal characters"},
  "provider_id": "local.acme.accessibility/uia",
  "profile_id": "local.acme.accessibility/uia/screen-parse-default",
  "provider_version": "1.0.0",
  "capture_lineage_ref": {"id": "capture/2026-08-21/001", "content_sha256": "64 lowercase hexadecimal characters"},
  "status": "success",
  "review_only": false,
  "items": [{
    "source_item_id": "uia-node-runtime-id-17",
    "source_id_origin": "provider",
    "kind": "text",
    "safe_text": "Apply now",
    "safe_role": null,
    "safe_states": [],
    "source_bbox": [100, 200, 310, 246],
    "capture_bbox": [100, 200, 310, 246],
    "source_coordinate_space": "capture_pixel_xyxy",
    "coordinate_transform_ref": null,
    "opaque_attributes": {},
    "provider_confidence": null
  }],
  "redaction_summary": {
    "redacted_item_count": 0,
    "redacted_field_count": 0,
    "secret_detected": false,
    "sensitive_categories": []
  },
  "content_sha256": "64 lowercase hexadecimal characters"
}
~~~

The successful example above uses the identity projection exception: its source_coordinate_space is capture_pixel_xyxy, and the adapter has verified the static source fixture binding against the exact request capture artifact_sha256 and image_size before copying source_bbox to capture_bbox with coordinate_transform_ref=null.

status is success or failed. For status=failed, items is exactly [], review_only is exactly true, and error_ref is required and is an immutable ref to a previously stored provider_error_v1. For status=success, error_ref is forbidden. requested_provider_id and requested_profile_id are required for every result. registration_resolution and manifest_resolution are each required enums: resolved, not_found, invalid, not_reached. registration_ref is required iff registration_resolution=resolved and is forbidden otherwise; manifest_ref is required iff manifest_resolution=resolved and is forbidden otherwise. A failed safe result copies these requested IDs and resolution values from its referenced error and includes only the refs whose resolution is resolved. This is the sole failed-output contract.

source_item_id preserves the provider source ID whenever the source contract supplies one, and source_id_origin is then provider. A source contract without an ID, including OCRTextMatch, must generate source_item_id deterministically from provider_id, profile_id, capture_lineage_ref, zero-based source index, and canonical safe source fields in this exact JCS record: {provider_id, profile_id, capture_lineage_ref, source_index, kind, safe_text, safe_role, safe_states, source_bbox, source_coordinate_space}. Its source_id_origin is uei_deterministic_projection. The generated ID is sha256:<JCS SHA-256>; it must never silently replace an available provider ID. source_item_id is non-empty and unique within a result. kind is element, text, role, state, icon, or structure. safe_text, safe_role, source_bbox, capture_bbox, and provider_confidence may be null; safe_states is a unique string array. source_bbox, when non-null, is always the safe and valid provider bbox in source_coordinate_space. capture_bbox is non-null only after the proven mapping in section 5.3. provider_confidence is null or finite 0-1, is provider-local only, and is never cross-provider comparable, sortable, calibrated, or authorizing.

opaque_attributes is the only exception to additionalProperties:false. It is a recursively bounded JSON escape hatch: every nested value must use allowed_json_types and collectively satisfy max_json_bytes, max_depth, max_array_items, max_object_properties, max_string_chars, and the schema object-property limit, after privacy redaction. A privacy or payload failure never drops an item silently: the adapter stores provider_error_v1 and then a whole failed provider_safe_result_v1 with items=[], review_only=true, and error_ref. Wire payload is never embedded. redaction_summary contains only counts, boolean, and category identifiers, never deleted values, text, hashes, paths, or tokens. review_only is neither mode, trust, score, nor authorization.

### 6.4 provider_error_v1

~~~json
{
  "contract_version": "provider_error_v1",
  "error_id": "error/2026-08-21/001",
  "request_ref": {"id": "request/2026-08-21/001", "content_sha256": "64 lowercase hexadecimal characters"},
  "requested_provider_id": "local.acme.vision/ocr",
  "requested_profile_id": "local.acme.vision/ocr/latin-desktop",
  "registration_resolution": "not_found",
  "manifest_resolution": "not_reached",
  "provider_id": "local.acme.vision/ocr",
  "profile_id": "local.acme.vision/ocr/latin-desktop",
  "stage": "registration",
  "code": "capability_intersection_empty",
  "retryable": false,
  "message": "Requested profile is not permitted by trusted deployment policy",
  "safe_details": {"reason_class": "policy"},
  "capture_lineage_ref": {"id": "capture/2026-08-21/001", "content_sha256": "64 lowercase hexadecimal characters"},
  "content_sha256": "64 lowercase hexadecimal characters"
}
~~~

stage is registration, manifest, request, projection, redaction, coordinate, or store. code is provider_unregistered, profile_unregistered, capability_intersection_empty, egress_disallowed, privacy_disallowed, payload_limit_exceeded, wire_payload_forbidden, fixture_invalid, provider_fixture_schema_invalid, lineage_mismatch, artifact_missing, content_hash_mismatch, coordinate_invalid, or projection_failed. provider_fixture_schema_invalid applies only after projection entry preconditions resolve, and only to the provider fixture, projected safe result, or projection-time schema validation; it never represents an invalid request or capture precondition. requested_provider_id and requested_profile_id are required for every error. registration_resolution and manifest_resolution are required enums: resolved, not_found, invalid, not_reached. registration_ref is required iff registration_resolution=resolved and forbidden otherwise; manifest_ref is required iff manifest_resolution=resolved and forbidden otherwise. safe_details is a closed object containing only reason_class non-empty string; it cannot include raw text, screenshots, paths, cookies, tokens, personal data, or an exception dump.

## 7. Pure projection adapters

Milestone 1 only accepts static OCRResult, UIA snapshot, and screen_parser_result_v1 inputs. Before projection, the caller/schema boundary must validate and resolve the already-stored request_ref and capture_lineage_ref; failure here is a structured outer boundary error and creates neither provider_error_v1 nor provider_safe_result_v1. Only after these preconditions succeed does the adapter process an input. For each input the adapter must:

1. preserve the provider source ID and set source_id_origin=provider; when the source contract has no ID, including OCRTextMatch, create the deterministic ID defined in section 6.3 and set source_id_origin=uei_deterministic_projection;
2. extract only safe public fields without mutating the fixture;
3. validate the trusted registration, manifest, and request intersection, including egress, privacy, mode, payload limits, and conformance suite;
4. apply boundary redaction and recursively validate opaque_attributes;
5. emit source_bbox whenever the source bbox is safe and valid in its declared source coordinate space. Apply the identity projection exception only when source_coordinate_space=capture_pixel_xyxy and the fixture binding exactly matches request artifact_sha256 and image_size; then copy source_bbox to capture_bbox with coordinate_transform_ref=null. For every other source space, missing transform or otherwise non-conflicting unproven mapping yields successful review_only with capture_bbox=null and coordinate_transform_ref=null. A supplied malformed, conflicting, out-of-bounds, or falsely proof-claiming transform is a coordinate failure;
6. after the entry preconditions succeed, on success store provider_safe_result_v1; on any capability, provider-fixture/result/projection-schema, privacy, payload, supplied-transform coordinate, or projection failure, first store provider_error_v1 and then store one failed provider_safe_result_v1 with status=failed, items=[], review_only=true, and required error_ref;
7. record requested_provider_id, requested_profile_id, registration_resolution, and manifest_resolution in both objects. Include registration_ref or manifest_ref only when its matching resolution is resolved, so every completed intersection is reproducible without fabricating a ref for not_found, invalid, or not_reached.

The adapter must not import, start, download, or call a vendor runtime; it must not scan old artifacts; a static fixture is not a live-capture authorization.
## 8. Actual JSON Schema files

实际 schema 文件与 fixture 计划

Milestone 1 的实现必须提交**实际 JSON Schema 文件**作为验证源，本文仅冻结设计，不可把本文示例当作唯一 schema。计划布局：

~~~text
schemas/uei/v1/trusted_provider_registration_v1.schema.json
schemas/uei/v1/artifact_ref_v1.schema.json
schemas/uei/v1/capture_lineage_v1.schema.json
schemas/uei/v1/affine_coordinate_transform_v1.schema.json
schemas/uei/v1/provider_manifest_v1.schema.json
schemas/uei/v1/screen_parse_request_v1.schema.json
schemas/uei/v1/provider_safe_result_v1.schema.json
schemas/uei/v1/provider_error_v1.schema.json
tests/fixtures/uei-v1/ocr-result-static.json
tests/fixtures/uei-v1/uia-snapshot-static.json
tests/fixtures/uei-v1/screen-parser-result-static.json
tests/fixtures/uei-v1/expected-safe-results/
~~~

每个 schema 文件使用 JSON Schema Draft 2020-12、additionalProperties:false、显式 required、枚举、numeric bounds、maxLength、maxItems、maxProperties；跨对象的 hash、lineage、policy intersection 与 payload byte/depth 验证由应用层完成。

## 9. Conformance、rollout 与 acceptance

离线 conformance 必须覆盖：

1. caller/schema boundary rejects invalid or unhashable request_ref, missing or invalid capture_lineage_ref, and unresolved capture artifact as structured outer boundary errors before UEI projection objects; after those preconditions, all planned schemas cover legal minima, unknown/extra field, wrong version/enum, required-null, and depth/bytes/array/string overflow;
2. JCS UTF-8 content hash：删除 self content_sha256 后稳定，任意其余字段改动即改 hash；
3. immutable refs 精确为 id/content_sha256，artifact_sha256 只用于 artifact bytes；
4. registration、manifest、request 的 profile/mode/privacy/egress/payload/conformance 交集；
5. OCRResult, UIA snapshot, and screen_parser_result_v1 static projections; provider source IDs are preserved and OCRTextMatch-style ID-less inputs use the required deterministic source_item_id and origin;
6. local_only and disabled are the only Milestone 1 registry egress policies; remote_allowed is schema-valid future policy but is rejected by the Milestone 1 rollout. Wire payload never enters UEI and redaction_summary has no values;
7. affine source/target space, size, scale, offset, exact outward/nearest/none rounding, clipping, and hash validation; identity projection copies source_bbox only for capture_pixel_xyxy plus exact fixture/request artifact_sha256 and image_size binding. Any other missing transform or non-conflicting unproven mapping is successful review_only with source_bbox when safe, capture_bbox=null, coordinate_transform_ref=null, while a supplied invalid/conflicting/out-of-bounds/falsely-proven transform fails;
8. any mode change leaves provider-confidence interpretation, trust, score, and authorization unchanged; all results/errors have requested IDs and resolution enums, have registration_ref/manifest_ref iff resolved, and have no action field.

rollout 从离线 static fixture 开始，feature flag 默认 Disabled。adapter 必须通过 registration 的 conformance suite 后才能被 trusted registry 启用。旧 artifact、旧 schema、现有运行路径不迁移、不包装、不隐式激活。

Acceptance: the eight schema files exist and load; caller/schema boundary rejects invalid/unhashable requests, missing/invalid capture lineage, and unresolved capture artifacts before creating UEI projection objects; all three static projections pass after valid request/capture preconditions. Every result/error has requested_provider_id, requested_profile_id, registration_resolution, and manifest_resolution, and contains each provenance ref iff that resolution is resolved. Post-precondition failures store provider_error_v1 first and a referenced failed provider_safe_result_v1 second. Unregistered provider, invalid capability intersection, Milestone-1-disallowed remote egress, oversized or unredacted payload, source-ID loss, provider fixture/result/projection schema violation, and supplied invalid/conflicting/out-of-bounds/falsely-proven coordinate transform fail closed. Identity projection copies bbox only for capture_pixel_xyxy plus exact fixture/request artifact SHA and image-size binding; all other missing-transform/non-conflicting-unproven mapping succeeds review_only with no capture bbox. There are no vendor calls, dependency changes, old-data migration, GUI/network/action side effects. UEI v1 is then only a safe screen-parse evidence boundary.

## 10. 后续里程碑（信息性，非 Milestone 1）

后续可设计 normalized_evidence_v1、fused_candidate_snapshot_v1、human_review_patch_v1、provider health、calibration profile、panel projection，但不得作为本切片 acceptance 或实现范围。

若引入 review，patch 必须 append-only、内容寻址、引用 immutable snapshot。每个 patch 指向一个 optimistic head immutable ref；服务端仅当前 head 精确相等时追加，否则返回冲突。operation 必须是 discriminated union：以 op 决定 required value 类型、允许字段和禁止字段。patch 永不得改 raw/safe result、capture lineage、bbox、provider confidence、未来 score 或 authorization。

若引入 calibration，profile 必须是独立 immutable 受控 object，且只在 benchmark scope、provider/profile version、privacy、capture class、有效期均匹配时产生 runtime score。raw provider confidence 始终保留且不可跨 provider 比较。若引入 fusion，必须保留冲突与 supporting refs；若引入 panel，它只能是服务端投影而非权威源。所有后续阶段继续不能授权点击。
