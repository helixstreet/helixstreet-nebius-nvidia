"""Runs an ADK pipeline for one event, logging every step (observability) and
mirroring the reasoning trace + token/latency/cost telemetry into the Memory Bank."""
import datetime
import inspect
import json
import logging
import time
import uuid

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from . import config
from .tools.memory import append_trace

log = logging.getLogger("helixstreet.runner")

_session_service = InMemorySessionService()

_AGENT_DEFAULT_MODEL = {
    "helixstreet_intake": config.NEMOTRON_NANO_MODEL,
    "helixstreet_variant_caller": config.NEMOTRON_NANO_MODEL,
    "helixstreet_analyst": config.NEMOTRON_ULTRA_MODEL,
    "helixstreet_pharmacist": config.NEMOTRON_ULTRA_MODEL,
    "helixstreet_steward": config.NEMOTRON_SUPER_MODEL,
}


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _compute_cost(model_id: str, prompt_tokens: int, completion_tokens: int) -> tuple[float, float]:
    """Returns (actual_cost_usd, all_ultra_baseline_cost_usd) using official
    Nebius Token Factory per-1M-token rates."""
    pricing = config.NEBIUS_MODEL_PRICING.get(
        model_id,
        {"input_per_1m": 1.00, "output_per_1m": 3.00},
    )
    actual = (
        prompt_tokens * pricing["input_per_1m"] + completion_tokens * pricing["output_per_1m"]
    ) / 1_000_000.0
    ultra_baseline = (prompt_tokens * 1.00 + completion_tokens * 3.00) / 1_000_000.0
    return round(actual, 6), round(ultra_baseline, 6)


async def run_pipeline(pipeline_agent, user_id: str, prompt: str) -> str:
    """Executes one fleet pipeline; returns the final agent response text."""
    from google.genai import types

    session_id = f"{pipeline_agent.name}-{uuid.uuid4().hex[:10]}"
    maybe = _session_service.create_session(
        app_name=config.APP_NAME, user_id=user_id, session_id=session_id
    )
    if inspect.isawaitable(maybe):
        await maybe

    runner = Runner(
        agent=pipeline_agent, app_name=config.APP_NAME, session_service=_session_service
    )
    message = types.Content(role="user", parts=[types.Part(text=prompt)])

    final_text = ""
    last_step_t = time.perf_counter()

    async for event in runner.run_async(
        user_id=user_id, session_id=session_id, new_message=message
    ):
        now_perf = time.perf_counter()
        latency_ms = round((now_perf - last_step_t) * 1000.0, 1)
        last_step_t = now_perf

        author = getattr(event, "author", "unknown")
        model_ver = getattr(event, "model_version", None) or _AGENT_DEFAULT_MODEL.get(
            author, config.NEMOTRON_ULTRA_MODEL
        )
        usage = getattr(event, "usage_metadata", None)
        p_tok = int(getattr(usage, "prompt_token_count", 0) or 0) if usage else 0
        c_tok = int(getattr(usage, "candidates_token_count", 0) or 0) if usage else 0
        actual_cost, ultra_cost = _compute_cost(model_ver, p_tok, c_tok)
        telemetry = {
            "model": model_ver,
            "latency_ms": latency_ms,
            "prompt_tokens": p_tok,
            "completion_tokens": c_tok,
            "cost_usd": actual_cost,
            "all_ultra_cost_usd": ultra_cost,
        }

        for call in event.get_function_calls() or []:
            entry = {
                "t": _now(),
                "agent": author,
                "type": "tool_call",
                "tool": call.name,
                "args": json.dumps(dict(call.args or {}), default=str)[:500],
                **telemetry,
            }
            log.info(json.dumps({"pipeline": pipeline_agent.name, **entry}))
            append_trace(user_id, entry)
            # Only attribute token usage once per LLM turn
            telemetry = {
                "model": model_ver,
                "latency_ms": 0.0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "cost_usd": 0.0,
                "all_ultra_cost_usd": 0.0,
            }

        for resp in event.get_function_responses() or []:
            entry = {
                "t": _now(),
                "agent": author,
                "type": "tool_result",
                "tool": resp.name,
                "result": json.dumps(resp.response, default=str)[:800],
                "model": model_ver,
                "latency_ms": latency_ms,
            }
            log.info(json.dumps({"pipeline": pipeline_agent.name, **entry}))
            append_trace(user_id, entry)

        if event.content and event.content.parts:
            text = "".join(p.text or "" for p in event.content.parts if getattr(p, "text", None))
            if text.strip():
                entry = {
                    "t": _now(),
                    "agent": author,
                    "type": "message",
                    "text": text.strip()[:1500],
                    **telemetry,
                }
                log.info(json.dumps({"pipeline": pipeline_agent.name, **entry}))
                append_trace(user_id, entry)
                final_text = text

    return final_text
