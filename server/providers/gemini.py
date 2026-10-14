"""Google Gemini adapter, on the official google-genai SDK (section 8.1).

Function calling runs the investigation tools. Google Search is added as the built-in web search when the
model accepts it next to function calling; otherwise the agent gets the Brave `web_search` tool instead.
The model's own content blocks are appended to the history unchanged, so Gemini's thought signatures
survive between turns.
"""
from __future__ import annotations

import asyncio

from google import genai
from google.genai import errors, types

from ..tools import ToolSpec
from . import ProviderError, ProviderNotConfigured, ProviderRefusal, ServerEvent, ToolCall, Turn, redact

EFFORT_TO_LEVEL = {"low": "low", "medium": "medium", "high": "high", "xhigh": "high", "max": "high"}

# Models that rejected Google Search next to function calling, remembered for the life of the process.
_NO_SEARCH_WITH_TOOLS: set[str] = set()


def search_allowed(model: str) -> bool:
    return model not in _NO_SEARCH_WITH_TOOLS


class GeminiConversation:
    def __init__(self, provider: "GeminiProvider", system: str, user: str, tools: list[ToolSpec]):
        self.p = provider
        self.contents: list[types.Content] = [types.Content(role="user", parts=[types.Part(text=user)])]
        self.declarations = [
            types.FunctionDeclaration(name=t.name, description=t.description, parameters_json_schema=t.parameters)
            for t in tools
        ]
        self.system = system
        self.names: dict[str, str] = {}
        self.local_ids: set[str] = set()   # ids made up here when the model sent none; never sent back

    def _config(self, with_search: bool) -> types.GenerateContentConfig:
        tools = [types.Tool(function_declarations=self.declarations)]
        if with_search:
            tools.append(types.Tool(google_search=types.GoogleSearch()))
        thinking = None
        if self.p.model.startswith("gemini-3"):
            thinking = types.ThinkingConfig(thinking_level=EFFORT_TO_LEVEL.get(self.p.effort, "medium"))
        return types.GenerateContentConfig(
            system_instruction=self.system,
            tools=tools,
            tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="AUTO")),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            thinking_config=thinking,
            max_output_tokens=16000,
        )

    async def _generate(self):
        # A model "experiencing high demand" (503) usually answers a second later: one short retry.
        try:
            return await self._generate_once()
        except errors.ServerError as exc:
            if exc.code not in (500, 503):
                raise
            await asyncio.sleep(1.5)
            return await self._generate_once()

    async def _generate_once(self):
        with_search = search_allowed(self.p.model)
        try:
            return await self.p.client.aio.models.generate_content(
                model=self.p.model, contents=self.contents, config=self._config(with_search))
        except errors.ClientError as exc:
            text = str(exc).lower()
            refused = exc.code == 400 and ("search" in text or "tool" in text)
            if with_search and (refused or exc.code == 429):
                # Google Search is refused next to function calling, or not included in the key's plan
                # (the free tier answers 429): run without it from now on.
                _NO_SEARCH_WITH_TOOLS.add(self.p.model)
                return await self.p.client.aio.models.generate_content(
                    model=self.p.model, contents=self.contents, config=self._config(False))
            raise

    async def next(self) -> Turn:
        try:
            response = await self._generate()
        except errors.ClientError as exc:
            if exc.code in (401, 403):
                raise ProviderError("The AI key was rejected.") from None
            if exc.code == 429:
                raise ProviderError("The AI provider is rate limiting requests.") from None
            if exc.code == 404:
                raise ProviderNotConfigured(f"The model {self.p.model} is not available with this key.") from None
            message = redact(str(exc), self.p.key)[:160]
            if "function" in message.lower() and "support" in message.lower():
                raise ProviderNotConfigured(
                    "This model does not support tool calling, which the investigation needs.") from None
            raise ProviderError(f"The AI provider rejected the request ({exc.code}).") from None
        except errors.ServerError as exc:
            raise ProviderError(f"The AI provider returned an error ({exc.code}).") from None
        except errors.APIError:
            raise ProviderError("The AI provider returned an error.") from None
        except Exception as exc:  # network errors from the HTTP layer
            raise ProviderError(f"The AI provider could not be reached ({type(exc).__name__}).") from None

        turn = Turn()
        self._bill(turn, response)
        candidate = (response.candidates or [None])[0]
        if candidate is None or candidate.content is None:
            block = getattr(getattr(response, "prompt_feedback", None), "block_reason", None)
            if block:
                raise ProviderRefusal("The AI model declined to investigate this link.")
            raise ProviderError("The AI model returned an empty answer.")
        finish = str(getattr(candidate, "finish_reason", "") or "")
        if "SAFETY" in finish or "PROHIBITED" in finish or "BLOCKLIST" in finish:
            raise ProviderRefusal("The AI model declined to investigate this link.")
        self.contents.append(candidate.content)  # unchanged: keeps thought signatures
        for index, part in enumerate(candidate.content.parts or []):
            if part.function_call:
                call = part.function_call
                call_id = call.id or f"{call.name}_{len(self.contents)}_{index}"
                if not call.id:
                    self.local_ids.add(call_id)
                self.names[call_id] = call.name
                turn.calls.append(ToolCall(call_id, call.name, dict(call.args or {})))
            elif part.text and not part.thought:
                turn.text += part.text
        grounding = getattr(candidate, "grounding_metadata", None)
        for query in (getattr(grounding, "web_search_queries", None) or []):
            turn.server_events.append(ServerEvent("web_search", query))
        return turn

    def remind(self, text: str) -> None:
        self.contents.append(types.Content(role="user", parts=[types.Part(text=text)]))

    def add_results(self, results: list[tuple[str, str, bool]]) -> None:
        import json
        parts = []
        for call_id, content, is_error in results:
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                payload = {"text": content}
            parts.append(types.Part(function_response=types.FunctionResponse(
                id=None if call_id in self.local_ids else call_id,
                name=self.names.get(call_id, ""),
                response={"error": payload} if is_error else {"output": payload},
            )))
        self.contents.append(types.Content(role="user", parts=parts))

    def _bill(self, turn: Turn, response) -> None:
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return
        prompt = (usage.prompt_token_count or 0) + (getattr(usage, "tool_use_prompt_token_count", 0) or 0)
        cached = getattr(usage, "cached_content_token_count", 0) or 0
        output = (getattr(usage, "candidates_token_count", None) or getattr(usage, "response_token_count", 0) or 0)
        output += getattr(usage, "thoughts_token_count", 0) or 0   # thinking is billed as output
        turn.bill(self.p.model, prompt, cached, output)


class GeminiProvider:
    name = "gemini"
    vision = True

    def __init__(self, key: str, model: str, effort: str):
        self.key = key
        self.model = model
        self.effort = effort or "medium"
        self.client = genai.Client(api_key=key)

    @property
    def builtin_search(self) -> bool:
        return search_allowed(self.model)

    def start(self, system: str, user: str, tools: list[ToolSpec]) -> GeminiConversation:
        return GeminiConversation(self, system, user, tools)
