"""Factory function to get appropriate LLM provider instance."""

from app.modules.llm.base import LLMProvider
from app.modules.llm.gemini import GeminiProvider
from app.modules.llm.openai import OpenAIProvider


def get_llm_provider(
    provider_name: str | None = None,
    model: str | None = None,
) -> LLMProvider:
    """Instantiate and return the requested LLMProvider (defaults to Gemini)."""
    name = (provider_name or "gemini").lower().strip()
    if name == "gemini":
        return GeminiProvider(default_model=model)
    elif name == "openai":
        return OpenAIProvider(model=model or "gpt-4o-mini")
    else:
        # Default fallback to Gemini
        return GeminiProvider(default_model=model)
