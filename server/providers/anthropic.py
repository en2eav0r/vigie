"""Anthropic (Claude) adapter: tool calling, vision and built-in web search."""
from __future__ import annotations

import anthropic

from ..tools import ToolSpec
from . import ProviderError, ProviderRefusal, ServerEvent, ToolCall, Turn

WEB_SEARCH_USD = 0.01
MAX_PAUSE_RESUMES = 4


class AnthropicConversation:
    def __init__(self, provider: "AnthropicProvider", system: str, user: str, tools: list[ToolSpec]):
        self.p = provider
        self.system = system
        self.messages: list[dict] = [{"role": "user", "content": user}]
        self.tools: list[dict] = [
            {"name": t.name, "description": t.description, "input_schema": t.parameters, "strict": True}
            for t in tools
        ]
        # Built-in web search: lets the agent confirm an official site with a second source.
        self.tools.append({"type": "web_search_20260209", "name": "web_search", "max_uses": 3})

    async def next(self) -> Turn:
        turn = Turn()
        for _ in range(MAX_PAUSE_RESUMES + 1):
            try:
                response = await self.p.client.beta.messages.create(
                    model=self.p.model,
                    max_tokens=16000,
                    system=self.system,
                    tools=self.tools,
                    messages=self.messages,
                    thinking={"type": "adaptive"},
                    output_config={"effort": self.p.effort},
                    # On a policy decline, the API re-runs the request on a fallback model in the same call.
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                )
            except anthropic.AuthenticationError as exc:
                raise ProviderError("The AI key was rejected.") from exc
            except anthropic.RateLimitError as exc:
                raise ProviderError("The AI provider is rate limiting requests.") from exc
            except anthropic.APIStatusError as exc:
                raise ProviderError(f"The AI provider returned an error ({exc.status_code}).") from exc
            except anthropic.APIConnectionError as exc:
                raise ProviderError("The AI provider could not be reached.") from exc

            self._bill(turn, response)
            self.messages.append({"role": "assistant", "content": response.content})
            for block in response.content:
                if block.type == "tool_use":
                    turn.calls.append(ToolCall(block.id, block.name, dict(block.input or {})))
                elif block.type == "server_tool_use" and block.name == "web_search":
                    query = (block.input or {}).get("query", "")
                    turn.server_events.append(ServerEvent("web_search", query))
                elif block.type == "text":
                    turn.text += block.text
            if response.stop_reason == "refusal":
                raise ProviderRefusal("The AI model declined to investigate this link.")
            if response.stop_reason == "pause_turn":
                continue  # the server-side search loop paused; re-send to let it resume
            return turn
        raise ProviderError("The AI model did not finish its turn.")

    def remind(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_results(self, results: list[tuple[str, str, bool]]) -> None:
        self.messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": call_id, "content": content, "is_error": is_error}
            for call_id, content, is_error in results
        ]})

    def _bill(self, turn: Turn, response) -> None:
        usage = response.usage
        cached = getattr(usage, "cache_read_input_tokens", 0) or 0
        turn.bill(self.p.model, (usage.input_tokens or 0) + cached, cached, usage.output_tokens or 0)
        server = getattr(usage, "server_tool_use", None)
        if server is not None:
            turn.cost_usd += (getattr(server, "web_search_requests", 0) or 0) * WEB_SEARCH_USD


class AnthropicProvider:
    name = "anthropic"
    builtin_search = True
    vision = True

    def __init__(self, key: str, model: str, effort: str, base_url: str = ""):
        self.model = model or "claude-opus-5-5"
        self.effort = effort or "medium"
        # The base URL is explicit so an unrelated ANTHROPIC_BASE_URL in the environment is never used.
        self.client = anthropic.AsyncAnthropic(api_key=key, base_url=base_url or "https://api.anthropic.com",
                                               timeout=40.0, max_retries=1)

    def start(self, system: str, user: str, tools: list[ToolSpec]) -> AnthropicConversation:
        return AnthropicConversation(self, system, user, tools)
