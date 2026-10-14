"""OpenAI and OpenAI-compatible adapter (OpenAI, Gemini's compatible endpoint, DeepSeek, Mistral,
OpenRouter, Groq, local Ollama). Models without built-in search get the Brave `web_search` tool,
and models without vision get the page text instead of a screenshot."""
from __future__ import annotations

import json

import openai

from ..tools import ToolSpec
from . import ProviderError, ProviderNotConfigured, ToolCall, Turn


class OpenAICompatConversation:
    def __init__(self, provider: "OpenAICompatProvider", system: str, user: str, tools: list[ToolSpec]):
        self.p = provider
        self.messages: list[dict] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        self.tools = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                         "parameters": t.parameters}} for t in tools]

    async def next(self) -> Turn:
        try:
            # The verdict and tool calls are short: a low output cap protects the budget.
            limit = {"max_completion_tokens": 1500} if self.p.name == "openai" else {"max_tokens": 1500}
            response = await self.p.client.chat.completions.create(
                model=self.p.model, messages=self.messages, tools=self.tools, tool_choice="auto", **limit,
            )
        except openai.AuthenticationError as exc:
            raise ProviderError("The AI key was rejected.") from exc
        except openai.BadRequestError as exc:
            if "tool" in str(exc).lower():
                # A model without tool calling cannot investigate (section 5.2).
                raise ProviderNotConfigured(
                    "This model does not support tool calling, which the investigation needs.") from exc
            raise ProviderError("The AI provider rejected the request.") from exc
        except openai.APIStatusError as exc:
            raise ProviderError(f"The AI provider returned an error ({exc.status_code}).") from exc
        except openai.APIConnectionError as exc:
            raise ProviderError("The AI provider could not be reached.") from exc
        message = response.choices[0].message
        self.messages.append(message.model_dump(exclude_none=True))
        turn = Turn(text=message.content or "")
        usage = response.usage
        if usage is not None:
            details = getattr(usage, "prompt_tokens_details", None)
            cached = (getattr(details, "cached_tokens", 0) or 0) if details else 0
            cached = cached or (getattr(usage, "prompt_cache_hit_tokens", 0) or 0)   # DeepSeek's field
            turn.bill(self.p.model, usage.prompt_tokens or 0, cached, usage.completion_tokens or 0)
        for call in message.tool_calls or []:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_invalid_json": call.function.arguments}
            turn.calls.append(ToolCall(call.id, call.function.name, args))
        return turn

    def remind(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_results(self, results: list[tuple[str, str, bool]]) -> None:
        for call_id, content, _ in results:
            self.messages.append({"role": "tool", "tool_call_id": call_id, "content": content})


class OpenAICompatProvider:
    builtin_search = False

    def __init__(self, name: str, key: str, model: str, base_url: str):
        self.name = name
        self.model = model
        self.vision = name in ("openai", "openrouter", "xai")
        self.client = openai.AsyncOpenAI(api_key=key, base_url=base_url, timeout=40.0, max_retries=1)

    def start(self, system: str, user: str, tools: list[ToolSpec]) -> OpenAICompatConversation:
        return OpenAICompatConversation(self, system, user, tools)
