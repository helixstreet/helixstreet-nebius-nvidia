"""Nebius Token Factory LLM adapter for Google ADK.

Connects ADK agents directly to NVIDIA Nemotron models served on Nebius Token
Factory (https://api.tokenfactory.nebius.com/v1/) via its OpenAI-compatible
Chat Completions API, with native function/tool calling and reasoning trace
extraction.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

from google.adk.models._capabilities import LlmCapabilities
from google.adk.models.base_llm import BaseLlm
from google.adk.models.interactions_utils import extract_system_instruction
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from openai import AsyncOpenAI, APIStatusError, APITimeoutError, RateLimitError
from pydantic import Field, PrivateAttr

from . import config

log = logging.getLogger("helixstreet.nebius_llm")


def _schema_to_json(schema: Any) -> Dict[str, Any]:
    """Converts a google.genai.types.Schema (or dict) into a JSON Schema dict."""
    if schema is None:
        return {"type": "object", "properties": {}}
    if isinstance(schema, dict):
         raw = dict(schema)
    elif hasattr(schema, "to_json_dict"):
        raw = schema.to_json_dict()
    elif hasattr(schema, "model_dump"):
        raw = schema.model_dump(exclude_none=True)
    else:
        return {"type": "object", "properties": {}}

    def _normalize(node: Any) -> Any:
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if k == "type" and isinstance(v, str):
                    out[k] = v.lower()
                elif k in ("properties", "$defs", "definitions") and isinstance(v, dict):
                    out[k] = {pk: _normalize(pv) for pk, pv in v.items()}
                else:
                    out[k] = _normalize(v)
            return out
        if isinstance(node, list):
            return [_normalize(x) for x in node]
        return node

    norm = _normalize(raw)
    if "type" not in norm:
        norm["type"] = "object"
    if norm["type"] == "object" and "properties" not in norm:
        norm["properties"] = {}
    return norm


def _tools_from_request(llm_request: LlmRequest) -> Optional[List[Dict[str, Any]]]:
    if not llm_request.config or not llm_request.config.tools:
        return None
    tools: List[Dict[str, Any]] = []
    for tool in llm_request.config.tools:
        if not isinstance(tool, types.Tool) or not tool.function_declarations:
            continue
        for decl in tool.function_declarations:
            params = _schema_to_json(decl.parameters) if decl.parameters else {
                "type": "object",
                "properties": {},
            }
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": decl.name,
                        "description": decl.description or "",
                        "parameters": params,
                    },
                }
            )
    return tools or None


def _messages_from_request(llm_request: LlmRequest) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []
    sys_inst = extract_system_instruction(llm_request.config)
    if sys_inst:
        messages.append({"role": "system", "content": sys_inst})

    for content in llm_request.contents or []:
        role = content.role or "user"
        parts = content.parts or []

        text_segments: List[str] = []
        tool_calls: List[Dict[str, Any]] = []
        tool_responses: List[Dict[str, Any]] = []

        for part in parts:
            if getattr(part, "thought", False):
                continue
            if getattr(part, "text", None):
                text_segments.append(part.text)
            if getattr(part, "function_call", None):
                fc = part.function_call
                call_id = getattr(fc, "id", None) or f"call_{uuid.uuid4().hex[:12]}"
                tool_calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": fc.name,
                            "arguments": json.dumps(dict(fc.args or {}), default=str),
                        },
                    }
                )
            if getattr(part, "function_response", None):
                fr = part.function_response
                call_id = getattr(fr, "id", None) or f"call_{uuid.uuid4().hex[:12]}"
                resp_payload = fr.response if fr.response is not None else {}
                tool_responses.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": fr.name,
                        "content": (
                            resp_payload
                            if isinstance(resp_payload, str)
                            else json.dumps(resp_payload, default=str)
                        ),
                    }
                )

        if role == "model":
            msg: Dict[str, Any] = {
                "role": "assistant",
                "content": "\n".join(text_segments) if text_segments else None,
            }
            if tool_calls:
                msg["tool_calls"] = tool_calls
            if msg["content"] or tool_calls:
                messages.append(msg)
        elif tool_responses:
            messages.extend(tool_responses)
            if text_segments:
                messages.append({"role": "user", "content": "\n".join(text_segments)})
        else:
            if text_segments:
                messages.append({"role": "user", "content": "\n".join(text_segments)})

    # Reconcile tool_call_ids if ADK omitted IDs on function_response parts
    pending_ids_by_name: Dict[str, List[str]] = {}
    for m in messages:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                fn_name = tc["function"]["name"]
                pending_ids_by_name.setdefault(fn_name, []).append(tc["id"])
        elif m.get("role") == "tool":
            fn_name = m.get("name", "")
            q = pending_ids_by_name.get(fn_name, [])
            if q and m["tool_call_id"] not in q:
                m["tool_call_id"] = q.pop(0)
            elif m["tool_call_id"] in q:
                q.remove(m["tool_call_id"])

    return messages


def _parse_args(raw_args: Optional[str]) -> Dict[str, Any]:
    if not raw_args:
        return {}
    try:
        parsed = json.loads(raw_args)
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except json.JSONDecodeError:
        # Attempt to extract first JSON object if wrapped in markdown
        start, end = raw_args.find("{"), raw_args.rfind("}")
        if start != -1 and end > start:
            try:
                parsed = json.loads(raw_args[start : end + 1])
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
        return {}


class NebiusTokenFactoryLlm(BaseLlm):
    """ADK BaseLlm implementation for NVIDIA Nemotron on Nebius Token Factory."""

    base_url: str = Field(default_factory=lambda: config.NEBIUS_BASE_URL)
    api_key: Optional[str] = Field(default_factory=lambda: config.NEBIUS_API_KEY, exclude=True)
    temperature: float = 0.2
    max_tokens: int = 4096
    max_retries: int = 5
    enable_thinking: bool = False

    _client: Optional[AsyncOpenAI] = PrivateAttr(default=None)

    @property
    def capabilities(self) -> LlmCapabilities:
        return LlmCapabilities(output_schema_and_tools=True)

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            key = self.api_key or config.NEBIUS_API_KEY or "missing-nebius-api-key"
            self._client = AsyncOpenAI(
                base_url=self.base_url,
                api_key=key,
                timeout=120.0,
            )
        return self._client

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self._maybe_append_user_content(llm_request)
        messages = _messages_from_request(llm_request)
        tools = _tools_from_request(llm_request)

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "extra_body": {"chat_template_kwargs": {"enable_thinking": self.enable_thinking}},
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        delay = 5.0
        last_err: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = await self._get_client().chat.completions.create(**kwargs)
                break
            except (RateLimitError, APITimeoutError, APIStatusError) as exc:
                last_err = exc
                status = getattr(exc, "status_code", None)
                if status and status not in (429, 500, 502, 503, 504):
                    raise
                if attempt == self.max_retries:
                    raise
                log.warning(
                    "Nebius Token Factory (%s) transient %s on attempt %d/%d; retrying in %.1fs",
                    self.model,
                    status or type(exc).__name__,
                    attempt,
                    self.max_retries,
                    delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2.0, 60.0)
        else:
            raise RuntimeError(f"Nebius Token Factory call failed: {last_err}")

        choice = resp.choices[0]
        msg = choice.message
        parts: List[types.Part] = []

        # Capture Nemotron reasoning trace if present
        reasoning = getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None)
        if isinstance(reasoning, str) and reasoning.strip():
            parts.append(types.Part(text=reasoning.strip(), thought=True))

        if msg.content and msg.content.strip():
            parts.append(types.Part.from_text(text=msg.content))

        for tc in msg.tool_calls or []:
            if tc.type == "function" and tc.function:
                part = types.Part.from_function_call(
                    name=tc.function.name,
                    args=_parse_args(tc.function.arguments),
                )
                if part.function_call is not None:
                    part.function_call.id = tc.id or f"call_{uuid.uuid4().hex[:12]}"
                parts.append(part)

        if not parts:
            parts.append(types.Part.from_text(text=""))

        usage = None
        if resp.usage:
            usage = types.GenerateContentResponseUsageMetadata(
                prompt_token_count=resp.usage.prompt_tokens,
                candidates_token_count=resp.usage.completion_tokens,
                total_token_count=resp.usage.total_tokens,
            )

        yield LlmResponse(
            model_version=resp.model or self.model,
            content=types.Content(role="model", parts=parts),
            partial=False,
            turn_complete=True,
            finish_reason=types.FinishReason.STOP,
            usage_metadata=usage,
        )
