# Configure Decision and secondary review providers

[简体中文](DECISION_PROVIDERS.zh-CN.md) · [Home](../../README.md)

**Available in execution 0.1.4.** The installed default OpenAI/Luna route passed scoped Main and independent Sol workflows in Notepad and 7-Zip; this does not certify every replacement provider. These settings first shipped in the 2026-10-15 rebuilt 0.1.3 installer; earlier 0.1.3 installers do not include them. Existing installations require an explicit upgrade. The learning component remains **0.1.0-preview.3**, unchanged. See the [current execution guide](../EXECUTION_GUIDE.md).

Decision and secondary review now have independent endpoints, model IDs and credential environment variables. Visual grounding still uses its separate [vision API profile](EXTERNAL_VISION_API.md). Replacing one layer does not change the other layers.

## Configuration

Copy the complete [provider profile example](../../configs/decision-profile.providers.example.json), edit the six connection fields below, and supply its path through the existing `--decision-profile` option. The example retains the visual execution Choice policy and uses two explicit credential variable names; it contains no keys.

| Layer | Endpoint field | Model field | Credential environment variable field |
| --- | --- | --- | --- |
| Decision | `endpoint` | `model` | `api_key_env` |
| Secondary review | `ordinary_review_endpoint` | `ordinary_review_model` | `ordinary_review_api_key_env` |

The example's connection fields are:

```json
{
  "endpoint": "https://api.openai.com/v1/decisions",
  "model": "gpt-6-luna",
  "api_key_env": "DECISION_API_KEY",
  "ordinary_review_endpoint": "https://api.openai.com/v1/responses",
  "ordinary_review_model": "gpt-6-luna",
  "ordinary_review_api_key_env": "REVIEW_API_KEY"
}
```

This excerpt is not a complete execution policy. Use the linked full profile, including `decision_format: "choice"` and `ordinary_review: "on_reject"`. Make the named variables available to the process that launches MCP. Their values may be the same or different; never put actual keys in the JSON profile. The grounding API's key is configured separately in its vision profile.

## Defaults and compatibility

- Existing profiles need no changes. Decision defaults to `https://api.openai.com/v1/decisions`, `gpt-6-luna`, and `OPENAI_API_KEY`. Secondary review defaults to `https://api.openai.com/v1/responses` and `gpt-6-luna`; omitting or setting `ordinary_review_api_key_env` to `null` inherits the Decision profile's `api_key_env`.
- If an explicitly named review credential is missing, the runtime does not substitute the primary key. A successful primary check can still continue. If secondary review is needed, the runtime returns `ordinary_review_unavailable` for main-agent handling without making that second API call.
- Endpoints are complete request URLs; paths are not appended automatically. Remote endpoints require HTTPS. Plain HTTP is supported only for `localhost`, `127.0.0.1` and `::1`. URLs cannot contain credentials, query parameters or fragments. Redirects and automatic retries remain disabled.
- Both layers use `Authorization: Bearer` authentication. Decision requires the existing **Decisions protocol**, including Choice/predicate answers and usage fields. Secondary review requires the **Responses protocol**, image input and the existing single-option output contract. It sends `reasoning.effort: "none"`, `max_output_tokens: 32`, `store: false` and `service_tier: "default"`. A generic Chat Completions endpoint is not a drop-in replacement.
- Responses must report the configured model ID exactly and satisfy the existing response schema. Model aliases that return a different resolved ID need a compatible adapter; malformed or mismatched results are not accepted.
- The flow remains **Decision → one secondary review on nonpass → original main agent if unresolved**. This update does not change prompts, thresholds, image crops, action gates, timeout policy or request budgets. Custom review receipts identify the configured review model.

## Apply a change

Finish or explicitly stop the current task and close its runtime session normally. Start a new session with the edited profile and reconnect the MCP client if its launch configuration changed. Profiles are frozen per session: editing a file does not hot-reload a running host or silently rejudge a saved request. Endpoint, model and credential-variable changes are bound to the new configuration; secret values are not saved in the profile or result.

## Verification boundary

Offline HTTP simulations cover independent routing and credentials, response-model validation, unchanged default request bodies, public CLI configuration, frozen-profile reload and authenticated recovery without duplicate dispatch. No third-party endpoint, live API accuracy, speed or token improvement has been established by these checks. Existing 0.1.3 performance figures describe the original OpenAI configuration only.
