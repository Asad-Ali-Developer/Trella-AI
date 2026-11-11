"""Google Gemini LLM provider implementation."""

import asyncio
import json
import re
from typing import Any, TypeVar, cast

import httpx
from fastapi import HTTPException, status
from pydantic import BaseModel, ValidationError
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt

from app.core.config import settings
from app.core.logging import get_logger
from app.modules.context.gemini import (
    _get_loop_client,
    _get_loop_semaphore,
    _parse_retry_after,
    _wait_for_retry,
)
from app.modules.llm.base import LLMProvider, LLMResult

logger = get_logger("app.modules.llm.gemini")
T = TypeVar("T", bound=BaseModel)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Standard pricing for Gemini Flash per million tokens
FLASH_INPUT_PRICE_PER_M = 0.075
FLASH_OUTPUT_PRICE_PER_M = 0.30

# Map retired or overloaded model aliases to active fast Flash models
MODEL_ALIASES: dict[str, str] = {
    "gemini-3.5-flash": "gemini-3-flash-preview",
    "gemini-2.5-flash": "gemini-3-flash-preview",
    "gemini-2.5-flash-lite": "gemini-3.1-flash-lite",
    "gemini-2.0-flash": "gemini-3-flash-preview",
    "gemini-1.5-flash": "gemini-3-flash-preview",
}

FALLBACK_MODELS: tuple[str, ...] = (
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
)


class GeminiRateLimited(Exception):
    """Raised when Gemini returns HTTP 429."""

    def __init__(self, detail: str, retry_after: float | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.retry_after = retry_after


class GeminiTransientError(Exception):
    """Raised when Gemini encounters transient network or 5xx errors."""

    def __init__(self, detail: str, retry_after: float | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.retry_after = retry_after


def sanitize_gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Sanitize Pydantic JSON schema for Gemini responseSchema:
    - Recursively inlines $ref pointers from $defs / definitions.
    - Strips unsupported keys: $defs, definitions, title, default, examples, $schema.
    """
    defs: dict[str, Any] = {}
    defs.update(schema.get("$defs", {}))
    defs.update(schema.get("definitions", {}))

    def _resolve(node: Any) -> Any:
        if isinstance(node, list):
            return [_resolve(item) for item in node]
        if not isinstance(node, dict):
            return node

        if "$ref" in node:
            ref_path = str(node["$ref"])
            ref_name = ref_path.split("/")[-1]
            if ref_name in defs:
                resolved = _resolve(defs[ref_name])
                merged = dict(resolved) if isinstance(resolved, dict) else {}
                for k, v in node.items():
                    if k != "$ref":
                        merged[k] = _resolve(v)
                return merged

        cleaned: dict[str, Any] = {}
        drop_keys = {"$defs", "definitions", "title", "default", "examples", "$schema"}
        for k, v in node.items():
            if k in drop_keys:
                continue
            cleaned[k] = _resolve(v)
        return cleaned

    sanitized = _resolve(schema)
    if isinstance(sanitized, dict):
        sanitized.pop("$defs", None)
        sanitized.pop("definitions", None)
        sanitized.pop("title", None)
        return sanitized
    return {}


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
        raw_default = default_model or settings.GEMINI_CONTEXT_MODEL
        self.default_model = MODEL_ALIASES.get(raw_default, raw_default)

    def _calculate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate estimated cost in USD based on Gemini Flash pricing."""
        prompt_cost = (prompt_tokens / 1_000_000.0) * FLASH_INPUT_PRICE_PER_M
        completion_cost = (completion_tokens / 1_000_000.0) * FLASH_OUTPUT_PRICE_PER_M
        return round(prompt_cost + completion_cost, 6)

    async def _call_single_model(self, model: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute a single model request to Gemini API with bounded retries honoring Retry-After."""
        url = f"{GEMINI_API_BASE}/{model}:generateContent"
        semaphore = _get_loop_semaphore()
        client = _get_loop_client()

        max_attempts = max(1, int(settings.GEMINI_MAX_ATTEMPTS))
        retrying = AsyncRetrying(
            stop=stop_after_attempt(max_attempts),
            wait=_wait_for_retry,
            retry=retry_if_exception_type((GeminiRateLimited, GeminiTransientError, httpx.RequestError)),
            reraise=True,
        )

        async for attempt in retrying:
            with attempt:
                async with semaphore:
                    try:
                        response = await client.post(
                            url,
                            json=payload,
                            headers={
                                "Content-Type": "application/json",
                                "x-goog-api-key": self.api_key,
                            },
                        )
                    except httpx.RequestError as exc:
                        raise GeminiTransientError(f"Network error on {model}: {exc}") from exc

                if response.status_code == 429:
                    retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                    logger.warning(
                        "gemini_rate_limited",
                        model=model,
                        retry_after=retry_after,
                    )
                    raise GeminiRateLimited(
                        f"Gemini 429 rate limit on {model}",
                        retry_after=retry_after,
                    )
                if response.status_code >= 500:
                    retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                    logger.warning(
                        "gemini_server_error",
                        model=model,
                        status_code=response.status_code,
                    )
                    raise GeminiTransientError(
                        f"Gemini server error {response.status_code} on {model}",
                        retry_after=retry_after,
                    )
                if response.status_code == 404:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Gemini model {model} not found.",
                    )
                if response.status_code != 200:
                    logger.error(
                        "gemini_api_error",
                        model=model,
                        status_code=response.status_code,
                        body=response.text,
                    )
                    raise HTTPException(
                        status_code=response.status_code,
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

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Gemini request failed on {model} after retries.",
        )

    async def _call_api(self, model: str, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        """Execute request against primary Gemini model, falling back on 404/429/5xx/timeout."""
        normalized = MODEL_ALIASES.get(model, model)
        candidates: list[str] = [normalized]
        for fb in FALLBACK_MODELS:
            if fb not in candidates:
                candidates.append(fb)

        last_exc: Exception | None = None
        for idx, candidate_model in enumerate(candidates):
            try:
                data = await self._call_single_model(candidate_model, payload)
                return data, candidate_model
            except Exception as exc:
                if isinstance(exc, HTTPException) and exc.status_code == 400:
                    raise
                last_exc = exc
                retry_after = getattr(exc, "retry_after", None)
                if retry_after is not None and retry_after > 0:
                    logger.info("gemini_429_waiting_retry_after_before_fallback", retry_after=retry_after)
                    await asyncio.sleep(retry_after)

                if idx + 1 < len(candidates):
                    logger.warning(
                        "gemini_falling_back_to_next_model",
                        failed_model=candidate_model,
                        next_model=candidates[idx + 1],
                        error=str(exc),
                    )
                    continue

        if isinstance(last_exc, httpx.TimeoutException):
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Gemini API timed out across models {candidates}.",
            ) from last_exc
        if isinstance(last_exc, HTTPException):
            raise last_exc
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gemini API is temporarily unavailable (503). Please retry in a moment.",
        ) from last_exc

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

        data, used_model = await self._call_api(target_model, payload)

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
            model=used_model,
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

        using_native_schema = settings.GEMINI_NATIVE_SCHEMA
        if using_native_schema:
            sanitized = sanitize_gemini_schema(response_schema.model_json_schema())
            payload["generationConfig"]["responseSchema"] = sanitized

        try:
            data, used_model = await self._call_api(target_model, payload)
        except HTTPException as exc:
            if using_native_schema and exc.status_code == 400:
                logger.warning(
                    "gemini_native_schema_rejected_400_retrying_without_schema",
                    model=target_model,
                    error=exc.detail,
                )
                payload["generationConfig"].pop("responseSchema", None)
                data, used_model = await self._call_api(target_model, payload)
            else:
                raise

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
            model=used_model,
            provider=self.provider_name,
            raw_response=data,
        )
        return parsed, result
