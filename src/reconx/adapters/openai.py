from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MAX_RESPONSE_BYTES = 1_048_576


class OpenAIProviderError(RuntimeError):
    """A deliberately sanitised hosted-model boundary error."""


Transport = Callable[[Request, float], bytes]


def _default_transport(request: Request, timeout_seconds: float) -> bytes:
    with urlopen(request, timeout=timeout_seconds) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise OpenAIProviderError("model response exceeds the configured size limit")
    return body


class OpenAIResponsesProvider:
    """Minimal Responses API adapter with strict JSON Schema output."""

    name = "openai_responses"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "gpt-5.4-mini",
        endpoint: str = "https://api.openai.com/v1/responses",
        transport: Transport = _default_transport,
    ) -> None:
        if not api_key.strip():
            raise ValueError("OPENAI_API_KEY is required when ENABLE_LLM=true")
        if not endpoint.startswith("https://"):
            raise ValueError("OPENAI_RESPONSES_URL must use HTTPS")
        self._api_key = api_key
        self.model = model
        self.endpoint = endpoint
        self._transport = transport

    def analyse(self, prompt: str, output_schema: dict[str, Any], timeout_seconds: float) -> str:
        payload = {
            "model": self.model,
            "instructions": (
                "Classify the finance exception as an advisory system. Never claim authority "
                "to post, approve, mutate, or close a financial record."
            ),
            "input": prompt,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "reconx_exception_analysis",
                    "strict": True,
                    "schema": output_schema,
                }
            },
            "max_output_tokens": 800,
            "store": False,
        }
        request = Request(
            self.endpoint,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            raw = self._transport(request, timeout_seconds)
            response = json.loads(raw)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise OpenAIProviderError(f"model request failed: {type(exc).__name__}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OpenAIProviderError("model response was not valid JSON") from exc

        output_text = response.get("output_text") if isinstance(response, dict) else None
        if isinstance(output_text, str) and output_text.strip():
            return output_text
        if isinstance(response, dict):
            for item in response.get("output", []):
                if not isinstance(item, dict) or item.get("type") != "message":
                    continue
                for content in item.get("content", []):
                    if isinstance(content, dict) and content.get("type") == "output_text":
                        text = content.get("text")
                        if isinstance(text, str) and text.strip():
                            return text
        raise OpenAIProviderError("model response did not contain output text")
