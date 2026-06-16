from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.model_server import check_model_server, ensure_model_server, load_model_profiles, stop_model_server
from app.vision.local_provider import LocalVisionProvider


DEFAULT_PROMPT = """Return JSON only.
Describe this GUI screenshot for an automation agent.
Use this exact shape:
{
  "screen_summary": "short purpose",
  "actions": [
    {"label": "visible label", "role": "button|input|link|tab|menu|card|other", "reason": "why it looks actionable"}
  ],
  "visible_text": ["important visible words"]
}
Rules:
- List only visible controls or clearly clickable cards.
- Keep labels exactly as visible when possible.
- Prefer concise output over explanation.
- Do not invent coordinates.
"""


def _load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Benchmark cases must be a JSON list: {path}")
    cases: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        image_path = ROOT_DIR / str(item.get("image_path") or "")
        if not image_path.exists():
            raise FileNotFoundError(f"Benchmark image not found: {image_path}")
        cases.append(
            {
                "case_id": str(item.get("case_id") or image_path.stem),
                "image_path": image_path,
                "expected_terms": [
                    [str(term) for term in group] if isinstance(group, list) else [str(group)]
                    for group in item.get("expected_terms") or []
                ],
            }
        )
    if not cases:
        raise ValueError(f"No benchmark cases found in {path}")
    return cases


def _profile_by_id(profile_id: str) -> dict[str, Any]:
    for profile in load_model_profiles():
        if profile.get("profile_id") == profile_id:
            return profile
    raise ValueError(f"Model profile not found: {profile_id}")


def _extract_text(raw_response: dict[str, Any]) -> str:
    choices = raw_response.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else {}
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
    return json.dumps(raw_response, ensure_ascii=False)


def _parse_json(raw_text: str) -> tuple[dict[str, Any] | None, str | None]:
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.casefold().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, str(exc)
    return payload if isinstance(payload, dict) else None, None


def _score_terms(raw_text: str, parsed: dict[str, Any] | None, expected_terms: list[list[str]]) -> dict[str, Any]:
    haystack = raw_text.casefold()
    if parsed is not None:
        haystack += "\n" + json.dumps(parsed, ensure_ascii=False).casefold()
    matched_groups = []
    missing_groups = []
    for group in expected_terms:
        matched = next((term for term in group if term.casefold() in haystack), None)
        if matched is None:
            missing_groups.append(group)
        else:
            matched_groups.append({"matched": matched, "variants": group})
    return {
        "expected_count": len(expected_terms),
        "matched_count": len(matched_groups),
        "matched_terms": matched_groups,
        "missing_terms": missing_groups,
        "recall": round(len(matched_groups) / len(expected_terms), 4) if expected_terms else None,
    }


class TransformersDirectMiniCPM:
    def __init__(self, model_path: Path) -> None:
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor

        self.torch = torch
        self.processor = AutoProcessor.from_pretrained(str(model_path), local_files_only=True)
        self.model = AutoModelForImageTextToText.from_pretrained(
            str(model_path),
            torch_dtype="auto",
            device_map="auto",
            local_files_only=True,
        )

    def generate(self, image_path: Path, prompt: str, *, max_tokens: int) -> str:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "url": str(image_path.resolve())},
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        inputs = self.processor.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
            downsample_mode="16x",
            max_slice_nums=9,
        ).to(self.model.device)
        with self.torch.inference_mode():
            output_ids = self.model.generate(
                **inputs,
                downsample_mode="16x",
                max_new_tokens=max_tokens,
            )
        trimmed = [out_ids[len(in_ids) :] for in_ids, out_ids in zip(inputs.input_ids, output_ids)]
        return self.processor.batch_decode(trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]

    def close(self) -> None:
        del self.model
        del self.processor
        gc.collect()
        if self.torch.cuda.is_available():
            self.torch.cuda.empty_cache()


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    cases = _load_cases(ROOT_DIR / args.cases)
    profile_ids = [item.strip() for item in args.profiles.split(",") if item.strip()]
    results: list[dict[str, Any]] = []
    for profile_id in profile_ids:
        profile = _profile_by_id(profile_id)
        print(f"### profile {profile_id}", flush=True)
        start_ms = time.perf_counter()
        direct_transformers = str(profile.get("runtime") or "").casefold() == "transformers_direct"
        ensure_result: dict[str, Any]
        direct_runner: TransformersDirectMiniCPM | None = None
        if direct_transformers:
            direct_runner = TransformersDirectMiniCPM(ROOT_DIR / str(profile.get("model_path")))
            ensure_result = {"status": "loaded_direct_transformers", "started": False}
        else:
            ensure_result = ensure_model_server(
                stage="observe",
                profile_id=profile_id,
                wait_until_ready=True,
                wait_seconds=float(args.wait_seconds),
            )
        load_ms = round((time.perf_counter() - start_ms) * 1000, 3)
        status = {"status": "direct_transformers"} if direct_transformers else check_model_server(profile, timeout=2.0)
        provider = None if direct_transformers else LocalVisionProvider(
            endpoint=str(profile.get("endpoint")),
            model_name=str(profile.get("model_name")),
            timeout_seconds=float(args.timeout_seconds),
        )
        profile_result = {
            "profile_id": profile_id,
            "label": profile.get("label"),
            "model_name": profile.get("model_name"),
            "endpoint": profile.get("endpoint"),
            "ensure_model_server": ensure_result,
            "server_status": status,
            "load_ms": load_ms,
            "cases": [],
        }
        for case in cases:
            print(f"- {case['case_id']}", flush=True)
            case_start = time.perf_counter()
            error = None
            raw_response: dict[str, Any] | None = None
            raw_text = ""
            parsed = None
            parse_error = None
            try:
                if direct_runner is not None:
                    raw_text = direct_runner.generate(case["image_path"], DEFAULT_PROMPT, max_tokens=int(args.max_tokens))
                    raw_response = {"choices": [{"message": {"content": raw_text}}]}
                else:
                    assert provider is not None
                    raw_response = provider._call_openai_compatible_endpoint(
                        case["image_path"],
                        DEFAULT_PROMPT,
                        max_tokens=int(args.max_tokens),
                    )
                    raw_text = _extract_text(raw_response)
                parsed, parse_error = _parse_json(raw_text)
            except Exception as exc:  # surfaced in report; benchmark must continue.
                error = str(exc)
            elapsed_ms = round((time.perf_counter() - case_start) * 1000, 3)
            score = _score_terms(raw_text, parsed, case["expected_terms"]) if error is None else None
            profile_result["cases"].append(
                {
                    "case_id": case["case_id"],
                    "image_path": str(case["image_path"]),
                    "elapsed_ms": elapsed_ms,
                    "success": error is None,
                    "error": error,
                    "json_ok": parsed is not None,
                    "parse_error": parse_error,
                    "score": score,
                    "raw_text_preview": " ".join(raw_text.split())[:1000],
                    "parsed": parsed,
                }
            )
        if direct_runner is not None:
            direct_runner.close()
        if args.stop_after_profile and not direct_transformers:
            profile_result["stop_model_server"] = stop_model_server(profile)
        results.append(profile_result)
    summary = []
    for profile_result in results:
        successful = [case for case in profile_result["cases"] if case.get("success")]
        recalls = [
            float(case["score"]["recall"])
            for case in successful
            if isinstance(case.get("score"), dict) and case["score"].get("recall") is not None
        ]
        summary.append(
            {
                "profile_id": profile_result["profile_id"],
                "success_count": len(successful),
                "case_count": len(profile_result["cases"]),
                "avg_case_ms": round(sum(float(case["elapsed_ms"]) for case in successful) / len(successful), 3) if successful else None,
                "avg_recall": round(sum(recalls) / len(recalls), 4) if recalls else None,
                "load_ms": profile_result["load_ms"],
            }
        )
    return {
        "contract_version": "understanding_model_benchmark_v1",
        "cases_path": args.cases,
        "profiles": profile_ids,
        "summary": summary,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark local GUI understanding model profiles on saved screenshots.")
    parser.add_argument("--profiles", default="qwen3_vl_4b_q4_k_m,qwen3_vl_8b_q4_k_m,minicpm_v_4_6_transformers")
    parser.add_argument("--cases", default="configs/understanding_model_benchmark_cases.json")
    parser.add_argument("--output", default="artifacts/accuracy-checks/understanding_model_benchmark_report.json")
    parser.add_argument("--wait-seconds", type=float, default=180.0)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--stop-after-profile", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()
    report = run_benchmark(args)
    output_path = ROOT_DIR / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output_path), "summary": report["summary"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
