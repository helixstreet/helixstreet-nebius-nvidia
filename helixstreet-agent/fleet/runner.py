"""Runs an ADK pipeline for one event, logging every step (observability) and
mirroring the reasoning trace into Firestore for the dashboard."""
import datetime
import inspect
import json
import logging
import uuid

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from . import config
from .tools.memory import append_trace

log = logging.getLogger("helixstreet.runner")

_session_service = InMemorySessionService()


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


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
    async for event in runner.run_async(
        user_id=user_id, session_id=session_id, new_message=message
    ):
        author = getattr(event, "author", "unknown")
        for call in event.get_function_calls() or []:
            entry = {"t": _now(), "agent": author, "type": "tool_call", "tool": call.name}
            log.info(json.dumps({"pipeline": pipeline_agent.name, **entry}))
            append_trace(user_id, entry)
        for resp in event.get_function_responses() or []:
            entry = {"t": _now(), "agent": author, "type": "tool_result", "tool": resp.name}
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
                }
                log.info(json.dumps({"pipeline": pipeline_agent.name, **entry}))
                append_trace(user_id, entry)
                final_text = text

    return final_text
