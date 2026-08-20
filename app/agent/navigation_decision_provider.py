from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class OpenAICompatibleNavigationDecisionProvider:
    def __init__(
        self,
        *,
        endpoint: str,
        model_name: str,
        timeout_seconds: float = 30.0,
        temperature: float = 0.0,
        max_tokens: int = 256,
    ) -> None:
        self.endpoint = _required_text(endpoint, "endpoint")
        self.model_name = _required_text(model_name, "model_name")
        self.timeout_seconds = float(timeout_seconds)
        self.temperature = float(temperature)
        self.max_tokens = int(max_tokens)

    def decide(self, context: dict[str, Any]) -> dict[str, Any]:
        prompt = self._build_prompt(context)
        payload = {
            "model": self.model_name,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are the decision layer of a GUI Agent. "
                        "Select exactly one available semantic choice. "
                        "Return one JSON object with choice_id and reason only. "
                        "Never invent a choice and never request final submit, send, "
                        "confirm, complete, payment, or another destructive action."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        }
        request = Request(
            self._chat_completions_url(),
            data=json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                endpoint_response = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Agent decision endpoint returned HTTP {exc.code}: {details}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(
                f"failed to reach Agent decision endpoint: {exc.reason}"
            ) from exc
        except TimeoutError as exc:
            raise RuntimeError(
                f"Agent decision endpoint timed out after {self.timeout_seconds:g} seconds"
            ) from exc

        raw_text = self._message_text(endpoint_response)
        parsed = self._parse_json_object(raw_text)
        choice_id = _required_text(parsed.get("choice_id"), "choice_id")
        reason = _required_text(parsed.get("reason"), "reason")
        available = {
            str(choice.get("choice_id") or "")
            for choice in context.get("choices") or []
            if isinstance(choice, dict)
        }
        if choice_id not in available:
            raise ValueError(f"Agent model choice is not available: {choice_id}")
        prompt_bytes = prompt.encode("utf-8")
        return {
            "choice_id": choice_id,
            "reason": reason,
            "decision_source": "actual_model_call",
            "decision_audit": {
                "contract_version": "navigation_decision_model_audit_v1",
                "model_name": self.model_name,
                "endpoint": self._chat_completions_url(),
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
                "prompt_utf8_length": len(prompt_bytes),
                "raw_model_output": raw_text,
                "parsed_decision": {
                    "choice_id": choice_id,
                    "reason": reason,
                },
                "artifact_is_authorization": False,
            },
        }

    def _build_prompt(self, context: dict[str, Any]) -> str:
        if (
            not isinstance(context, dict)
            or context.get("contract_version")
            != "navigation_reading_agent_context_v1"
        ):
            raise ValueError("navigation_reading_agent_context_v1 is required")
        semantic_context = {
            "goal": context.get("goal"),
            "interface": deepcopy(context.get("interface") or {}),
            "read_state": deepcopy(context.get("read_state") or {}),
            "task_progress": deepcopy(context.get("task_progress") or {}),
            "choices": deepcopy(context.get("choices") or []),
            "verification_rules": deepcopy(
                context.get("verification_rules") or []
            ),
            "blockers": deepcopy(context.get("blockers") or []),
        }
        return (
            "Choose the next safe semantic step from the supplied choices. "
            "Do not repeat a choice listed in completed_choice_ids unless the goal "
            "explicitly requires that loop. "
            "Never claim a scroll budget is exhausted while scrolls_used is lower "
            "than max_scrolls; when the goal requires an exact scroll count, continue "
            "until that count unless verification fails or wrong scope is detected. "
            "Use safe_stop when the evidence is insufficient. "
            "Return JSON only.\n"
            + json.dumps(
                semantic_context,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )

    def _chat_completions_url(self) -> str:
        endpoint = self.endpoint.rstrip("/")
        if endpoint.endswith("/chat/completions"):
            return endpoint
        if endpoint.endswith("/v1"):
            return f"{endpoint}/chat/completions"
        return f"{endpoint}/v1/chat/completions"

    def _message_text(self, response: dict[str, Any]) -> str:
        choices = response.get("choices") if isinstance(response, dict) else None
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("Agent decision endpoint returned no choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            text = "\n".join(
                str(item.get("text") or "")
                for item in content
                if isinstance(item, dict)
            ).strip()
            if text:
                return text
        raise RuntimeError("Agent decision endpoint returned no message text")

    def _parse_json_object(self, text: str) -> dict[str, Any]:
        candidate = text.strip()
        if candidate.startswith("```") and candidate.endswith("```"):
            candidate = candidate[3:-3].strip()
            if candidate.casefold().startswith("json"):
                candidate = candidate[4:].strip()
        parsed = json.loads(candidate)
        if not isinstance(parsed, dict):
            raise ValueError("Agent decision JSON root must be an object")
        return parsed


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text
