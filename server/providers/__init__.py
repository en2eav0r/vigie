"""One adapter layer: the same agent runs on Anthropic, OpenAI, Google, DeepSeek or any
OpenAI-compatible endpoint (S08). One model per investigation, never a vote."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..config import Settings
from ..tools import ToolSpec


def redact(text: str, *secrets: str) -> str:
    """Remove API keys from any text that may reach a log or a client."""
    for secret in secrets:
        if secret and len(secret) > 8:
            text = text.replace(secret, "[redacted]")
    return text


class ProviderError(Exception):
    """The model did not answer (network, quota, timeout or authentication)."""


class ProviderRefusal(ProviderError):
    """The model declined the request."""


class ProviderNotConfigured(ProviderError):
    """No key or model is configured for this provider."""


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class ServerEvent:
    """A step the provider ran on its own side, such as its built-in web search."""
    kind: str
    detail: str


@dataclass
class Turn:
    calls: list[ToolCall] = field(default_factory=list)
    server_events: list[ServerEvent] = field(default_factory=list)
    text: str = ""
    cost_usd: float = 0.0
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0

    def bill(self, model: str, input_tokens: int, cached_tokens: int, output_tokens: int) -> None:
        from .pricing import cost
        self.input_tokens += input_tokens
        self.cached_tokens += cached_tokens
        self.output_tokens += output_tokens
        self.cost_usd += cost(model, input_tokens, cached_tokens, output_tokens)


class Conversation(Protocol):
    async def next(self) -> Turn: ...

    def add_results(self, results: list[tuple[str, str, bool]]) -> None: ...

    def remind(self, text: str) -> None: ...


class Provider(Protocol):
    name: str
    model: str
    builtin_search: bool
    vision: bool

    def start(self, system: str, user: str, tools: list[ToolSpec]) -> Conversation: ...


@dataclass(frozen=True)
class ProviderChoice:
    name: str
    model: str = ""
    key: str = ""        # the user's own key (S11): used in memory, never stored or logged
    base_url: str = ""


DEFAULT_MODELS = {"anthropic": "claude-opus-5-5", "gemini": "gemini-3.5-flash-lite", "openai": "gpt-4.1-mini",
                  "deepseek": "deepseek-flash"}
# OpenAI-compatible providers: environment variable holding the key, and the API address.
COMPAT = {
    "openai": ("OPENAI_API_KEY", "https://api.openai.com/v1"),
    "deepseek": ("DEEPSEEK_API_KEY", "https://api.deepseek.com"),
    "mistral": ("MISTRAL_API_KEY", "https://api.mistral.ai/v1"),
    "groq": ("GROQ_API_KEY", "https://api.groq.com/openai/v1"),
    "openrouter": ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1"),
    "xai": ("XAI_API_KEY", "https://api.x.ai/v1"),
    "ollama": ("", "OLLAMA_BASE_URL"),            # local models, no key; address from OLLAMA_BASE_URL
    "openai_compat": ("VIGIE_COMPAT_API_KEY", "VIGIE_BASE_URL"),
}
SUPPORTED = ("anthropic", "gemini", "scripted", *COMPAT)
# Shown to the operator, and to a user choosing DeepSeek with their own key (section 5.2).
NOTICES = {"deepseek": "DeepSeek processes data in China."}


def make_provider(settings: Settings, choice: ProviderChoice) -> Provider:
    name = choice.name or settings.provider
    if name not in SUPPORTED:
        raise ProviderNotConfigured(f"Unknown AI provider: {name}")
    model = choice.model or (settings.model if name == settings.provider else "") or DEFAULT_MODELS.get(name, "")
    if name == "scripted":
        if not settings.allow_test_provider:
            raise ProviderNotConfigured("The scripted provider is only available to the test suite.")
        from .scripted import ScriptedProvider
        return ScriptedProvider()
    if name == "anthropic":
        key = choice.key or settings.anthropic_key
        if not key:
            raise ProviderNotConfigured("No AI key is configured on this server.")
        from .anthropic import AnthropicProvider
        base_url = choice.base_url or (settings.base_url if name == settings.provider else "")
        return AnthropicProvider(key=key, model=model, effort=settings.effort, base_url=base_url)
    if name == "gemini":
        key = choice.key or settings.gemini_key
        if not key:
            raise ProviderNotConfigured("No AI key is configured on this server.")
        from .gemini import GeminiProvider
        return GeminiProvider(key=key, model=model, effort=settings.effort)
    import os
    key_env, address = COMPAT[name]
    key = choice.key or (os.environ.get(key_env, "").strip() if key_env else "local")
    base_url = choice.base_url or (os.environ.get(address, "").strip() if not address.startswith("http") else address)
    if name == "ollama" and not base_url:
        base_url = "http://localhost:11434/v1"
    if name == settings.provider and settings.base_url and not choice.base_url:
        base_url = settings.base_url
    if not key:
        raise ProviderNotConfigured("No AI key is configured on this server.")
    if not model:
        raise ProviderNotConfigured(f"No model is configured for {name}.")
    if not base_url:
        raise ProviderNotConfigured(f"No API address is configured for {name}.")
    from .openai_compat import OpenAICompatProvider
    return OpenAICompatProvider(name=name, key=key, model=model, base_url=base_url)
