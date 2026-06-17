# AI Trading OS - LLM Adapter (Unified multi-model interface)
"""
LLM Adapter Pattern — allows switching between LLM providers without
changing any agent or application code.

Supported providers:
  - claude   (Anthropic Claude — default for V1)
  - gpt      (OpenAI GPT)
  - deepseek (DeepSeek)
  - glm      (Zhipu GLM)
  - gemini   (Google Gemini)

Usage:
    from backend.llm_adapter import get_llm

    llm = get_llm()                   # uses settings.llm_provider
    reply = await llm.chat(messages)
    async for token in llm.chat_stream(messages):
        yield token
"""

from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional

from backend.config import settings


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class BaseLLM(ABC):
    """Abstract LLM interface. All providers implement this."""

    @abstractmethod
    async def chat(self, messages: list[dict], *, system: str = "", **kwargs) -> str:
        """Non-streaming chat — returns the full response."""
        ...

    @abstractmethod
    async def chat_stream(self, messages: list[dict], *, system: str = "", **kwargs) -> AsyncIterator[str]:
        """Streaming chat — yields text tokens as they arrive."""
        ...


# ---------------------------------------------------------------------------
# Claude adapter (primary for V1)
# ---------------------------------------------------------------------------

class ClaudeAdapter(BaseLLM):
    """Anthropic Claude adapter using the official SDK."""

    def __init__(self, api_key: str = "", model: str = ""):
        self.api_key = api_key or settings.anthropic_api_key
        self.model = model or settings.anthropic_model

    def _get_client(self):
        import anthropic
        return anthropic.AsyncAnthropic(api_key=self.api_key)

    async def chat(self, messages: list[dict], *, system: str = "", **kwargs) -> str:
        client = self._get_client()
        response = await client.messages.create(
            model=self.model,
            max_tokens=kwargs.get("max_tokens", 4096),
            system=system or None,
            messages=messages,
        )
        return response.content[0].text

    async def chat_stream(self, messages: list[dict], *, system: str = "", **kwargs) -> AsyncIterator[str]:
        client = self._get_client()
        async with client.messages.stream(
            model=self.model,
            max_tokens=kwargs.get("max_tokens", 4096),
            system=system or None,
            messages=messages,
        ) as stream:
            async for text_chunk in stream.text_stream:
                yield text_chunk


# ---------------------------------------------------------------------------
# OpenAI-compatible adapter (GPT, DeepSeek, GLM all use OpenAI-compatible API)
# ---------------------------------------------------------------------------

class OpenAICompatibleAdapter(BaseLLM):
    """Adapter for any OpenAI-compatible API (GPT, DeepSeek, GLM, etc.)."""

    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    async def chat(self, messages: list[dict], *, system: str = "", **kwargs) -> str:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)

        api_messages = []
        if system:
            api_messages.append({"role": "system", "content": system})
        api_messages.extend(messages)

        response = await client.chat.completions.create(
            model=self.model,
            messages=api_messages,
            max_tokens=kwargs.get("max_tokens", 4096),
        )
        return response.choices[0].message.content or ""

    async def chat_stream(self, messages: list[dict], *, system: str = "", **kwargs) -> AsyncIterator[str]:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)

        api_messages = []
        if system:
            api_messages.append({"role": "system", "content": system})
        api_messages.extend(messages)

        stream = await client.chat.completions.create(
            model=self.model,
            messages=api_messages,
            max_tokens=kwargs.get("max_tokens", 4096),
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_provider_registry: dict[str, BaseLLM] = {}


def get_llm(provider: Optional[str] = None) -> BaseLLM:
    """Return the configured LLM adapter. Caches adapters after first creation.

    Args:
        provider: Override the configured provider ("claude" | "gpt" | "deepseek" | "glm" | "gemini").
                  If None, uses settings.llm_provider.
    """
    provider = provider or settings.llm_provider

    if provider not in _provider_registry:
        _provider_registry[provider] = _create_adapter(provider)

    return _provider_registry[provider]


def _create_adapter(provider: str) -> BaseLLM:
    if provider == "claude":
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY not set. Create a .env file or export the variable.")
        return ClaudeAdapter()

    elif provider == "gpt":
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY not set.")
        return OpenAICompatibleAdapter(
            api_key=settings.openai_api_key,
            base_url="https://api.openai.com/v1",
            model="gpt-4o",
        )

    elif provider == "deepseek":
        if not settings.deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY not set.")
        return OpenAICompatibleAdapter(
            api_key=settings.deepseek_api_key,
            base_url="https://api.deepseek.com/v1",
            model="deepseek-chat",
        )

    elif provider == "glm":
        return OpenAICompatibleAdapter(
            api_key=settings.openai_api_key or "",
            base_url="https://open.bigmodel.cn/api/paas/v4",
            model="glm-4",
        )

    elif provider == "gemini":
        raise NotImplementedError("Gemini adapter not yet implemented. Use claude or gpt.")

    else:
        raise ValueError(f"Unknown LLM provider: {provider}. Supported: claude, gpt, deepseek, glm, gemini")
