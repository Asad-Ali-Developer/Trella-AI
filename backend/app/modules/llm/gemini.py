"""Google Gemini LLM provider implementation."""

import json
import re
from typing import Any, TypeVar, cast

import httpx
from fastapi import HTTPException, status
from pydantic import BaseModel, ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.logging import get_logger
from app.modules.llm.base import LLMProvider, LLMResult

logger = get_logger("app.modules.llm.gemini")
T = TypeVar("T", bound=BaseModel)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Standard pricing for Gemini 2.5 Flash / 1.5 Flash per million tokens
FLASH_INPUT_PRICE_PER_M = 0.075
FLASH_OUTPUT_PRICE_PER_M = 0.30


def _clean_json_markdown(text: str) -> str:
    """Strip markdown code fence blocks if returned by model."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        return match.group(1).strip()
    return text


def _repair_truncated_json(text: str) -> str:
    """Best-effort repair for JSON that was cut off at the model token limit."""
    text = text.strip()
    if not text:
        return "{}"

    in_string = False
    escape = False
    stack: list[str] = []

    for char in text:
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if not in_string:
            if char == "{":
                stack.append("}")
            elif char == "[":
                stack.append("]")
            elif char in ("}", "]"):
                if stack and stack[-1] == char:
                    stack.pop()

    if in_string:
        text += '"'

    text = re.sub(r",\s*$", "", text)
    text = re.sub(r',\s*"[^"]*"\s*:\s*$', "", text)

    while stack:
        text += stack.pop()

    return text


class GeminiProvider(LLMProvider):
    """Google Gemini LLM provider implementing the LLMProvider interface."""

    provider_name = "gemini"

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str | None = None,
    ) -> None:
        self.api_key = api_key or settings.GEMINI_API_KEY
        if not self.api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Gemini API is not configured. Set GEMINI_API_KEY in .env.",
            )
        self.default_model = default_model or settings.GEMINI_CONTEXT_MODEL

    def _calculate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate estimated cost in USD based on Gemini Flash pricing."""
        prompt_cost = (prompt_tokens / 1_000_000.0) * FLASH_INPUT_PRICE_PER_M
        completion_cost = (completion_tokens / 1_000_000.0) * FLASH_OUTPUT_PRICE_PER_M
        return round(prompt_cost + completion_cost, 6)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
        reraise=True,
    )
    async def _call_api(self, model: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute request to Gemini API with retry and backoff."""
        url = f"{GEMINI_API_BASE}/{model}:generateContent"
        async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
            response = await client.post(
                url,
                params={"key": self.api_key},
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            if response.status_code == 429:
                logger.warning("gemini_rate_limited", status_code=response.status_code)
                response.raise_for_status()
            if response.status_code >= 500:
                logger.warning("gemini_server_error", status_code=response.status_code)
                response.raise_for_status()
            if response.status_code != 200:
                logger.error("gemini_api_error", status_code=response.status_code, body=response.text)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Gemini API returned error ({response.status_code}): {response.text}",
                )
            try:
                data = response.json()
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Gemini returned a malformed response.",
                ) from exc
            if not isinstance(data, dict):
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Gemini returned a malformed response.",
                )
            return cast(dict[str, Any], data)

    async def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        system_instruction: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ) -> LLMResult:
        target_model = model or self.default_model
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                "responseMimeType": "text/plain",
            },
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        try:
            data = await self._call_api(target_model, payload)
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Gemini API timed out on model '{target_model}'. Google preview servers may be experiencing high latency.",
            ) from exc

        try:
            candidates = data.get("candidates", [])
            parts = candidates[0]["content"]["parts"] if candidates else []
            content = "\n".join(p["text"] for p in parts if "text" in p).strip()
        except (KeyError, IndexError, TypeError):
            content = ""

        usage = data.get("usageMetadata", {})
        prompt_tokens = usage.get("promptTokenCount", 0)
        completion_tokens = usage.get("candidatesTokenCount", 0)
        total_tokens = usage.get("totalTokenCount", prompt_tokens + completion_tokens)
        cost_usd = self._calculate_cost(prompt_tokens, completion_tokens)

        return LLMResult(
            content=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
            model=target_model,
            provider=self.provider_name,
            raw_response=data,
        )

    async def generate_structured(
        self,
        prompt: str,
        response_schema: type[T],
        *,
        model: str | None = None,
        system_instruction: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 8192,
    ) -> tuple[T, LLMResult]:
        target_model = model or self.default_model
        schema_json = json.dumps(response_schema.model_json_schema(), indent=2)
        format_instruction = (
            f"\nYou MUST respond with valid JSON strictly adhering to this JSON schema:\n{schema_json}\n"
            "Do not include any text before or after the JSON."
        )
        combined_prompt = f"{prompt}\n\n{format_instruction}"

        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": combined_prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json",
            },
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        try:
            data = await self._call_api(target_model, payload)
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Gemini API timed out on model '{target_model}'. Google preview servers may be experiencing high latency.",
            ) from exc

        try:
            candidates = data.get("candidates", [])
            parts = candidates[0]["content"]["parts"] if candidates else []
            content = "\n".join(p["text"] for p in parts if "text" in p).strip()
        except (KeyError, IndexError, TypeError):
            content = "{}"

        cleaned_json = _clean_json_markdown(content)
        parsed: T | None = None
        try:
            parsed = response_schema.model_validate_json(cleaned_json)
        except ValidationError as exc:
            # Attempt best-effort bracket/syntax repair if JSON was truncated
            repaired_json = _repair_truncated_json(cleaned_json)
            try:
                parsed = response_schema.model_validate_json(repaired_json)
                cleaned_json = repaired_json
                logger.info("gemini_json_repaired_successfully")
            except ValidationError:
                logger.error("gemini_schema_validation_failed", error=str(exc), raw_content=content)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Gemini output did not match expected schema: {exc}",
                ) from exc

        usage = data.get("usageMetadata", {})
        prompt_tokens = usage.get("promptTokenCount", 0)
        completion_tokens = usage.get("candidatesTokenCount", 0)
        total_tokens = usage.get("totalTokenCount", prompt_tokens + completion_tokens)
        cost_usd = self._calculate_cost(prompt_tokens, completion_tokens)

        result = LLMResult(
            content=cleaned_json,
            parsed=parsed.model_dump(),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
            model=target_model,
            provider=self.provider_name,
            raw_response=data,
        )
        return parsed, result

