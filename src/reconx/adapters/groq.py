from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MAX_RESPONSE_BYTES = 1_048_576
_UNSUPPORTED_STRICT_SCHEMA_KEYS = {"maxLength", "uniqueItems"}


class GroqProviderError(RuntimeError):
    """A deliberately sanitised hosted-model boundary error."""


Transport = Callable[[Request, float], bytes]


def _default_transport(request: Request, timeout_seconds: float) -> bytes:
    with urlopen(request, timeout=timeout_seconds) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise GroqProviderError("model response exceeds the configured size limit")
    return body


def _strict_schema_subset(value: Any) -> Any:
    """Keep the finance contract while removing unsupported Groq schema keywords.

    ReconX performs its full validation after the response, including uniqueness and
    text-length checks. Removing these two generation-time keywords therefore does not
    weaken the application boundary.
    """

    if isinstance(value, dict):
        return {
            key: _strict_schema_subset(item)
            for key, item in value.items()
            if key not in _UNSUPPORTED_STRICT_SCHEMA_KEYS
        }
    if isinstance(value, list):
        return [_strict_schema_subset(item) for item in value]
    return value


class GroqChatCompletionsProvider:
    """Minimal Groq adapter using strict JSON Schema structured output."""

    name = "groq_chat_completions"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "openai/gpt-oss-20b",
        endpoint: str = "https://api.groq.com/openai/v1/chat/completions",
        transport: Transport = _default_transport,
    ) -> None:
        if not api_key.strip():
            raise ValueError("GROQ_API_KEY is required when the Groq provider is enabled")
        if not endpoint.startswith("https://"):
            raise ValueError("GROQ_CHAT_URL must use HTTPS")
        self._api_key = api_key
        self.model = model
        self.endpoint = endpoint
        self._transport = transport

    def analyse(self, prompt: str, output_schema: dict[str, Any], timeout_seconds: float) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Classify this finance exception as an advisory system. Never claim "
                        "authority to post, approve, mutate, or close a financial record.\n\n"
                        + prompt
                    ),
                }
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "reconx_exception_analysis",
                    "strict": True,
                    "schema": _strict_schema_subset(output_schema),
                },
            },
            "reasoning_effort": "low",
            "include_reasoning": False,
            "temperature": 0.5,
            "max_completion_tokens": 1200,
        }
        request = Request(
            self.endpoint,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": "ReconX/1.0",
            },
            method="POST",
        )
        try:
            raw = self._transport(request, timeout_seconds)
            response = json.loads(raw)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise GroqProviderError(f"model request failed: {type(exc).__name__}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GroqProviderError("model response was not valid JSON") from exc

        if isinstance(response, dict):
            choices = response.get("choices", [])
            if isinstance(choices, list) and choices:
                first = choices[0]
                message = first.get("message", {}) if isinstance(first, dict) else {}
                content = message.get("content") if isinstance(message, dict) else None
                if isinstance(content, str) and content.strip():
                    return content
        raise GroqProviderError("model response did not contain output text")
