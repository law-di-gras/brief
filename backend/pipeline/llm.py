"""Thin Anthropic wrapper: JSON through a tool call, token usage logged per run."""
import json
import logging
import os
import threading

import anthropic

log = logging.getLogger(__name__)

SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-4-5-20251001"

_client = None
_usage = threading.local()


class LLMError(RuntimeError):
    pass


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        headers = {}
        if os.environ.get("ANTHROPIC_WORKSPACE_ID"):   # needed when the API key is not scoped to a workspace
            headers["anthropic-workspace-id"] = os.environ["ANTHROPIC_WORKSPACE_ID"]
        _client = anthropic.Anthropic(max_retries=4, default_headers=headers or None)
    return _client


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


# ---- usage accounting -------------------------------------------------------

def reset_usage() -> None:
    _usage.input = 0
    _usage.output = 0


def usage() -> tuple[int, int]:
    return getattr(_usage, "input", 0), getattr(_usage, "output", 0)


def _record(resp) -> None:
    u = resp.usage
    inp = (u.input_tokens or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0) \
        + (getattr(u, "cache_creation_input_tokens", 0) or 0)
    _usage.input = getattr(_usage, "input", 0) + inp
    _usage.output = getattr(_usage, "output", 0) + (u.output_tokens or 0)


# ---- calls ------------------------------------------------------------------

def call_json(model: str, system: str, user: str, tool_name: str, tool_description: str,
              schema: dict, max_tokens: int = 16000, effort: str | None = None) -> dict:
    """Ask the model to answer by calling one tool; return the tool input.

    Sonnet 5.5 rejects forced tool_choice, so it gets tool_choice=auto plus an
    explicit instruction, and we retry once if no tool call comes back. Haiku 4.5
    supports forced tool_choice.
    """
    tool = {"name": tool_name, "description": tool_description, "input_schema": schema}
    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        tools=[tool],
    )
    forced = model == HAIKU
    if forced:
        kwargs["tool_choice"] = {"type": "tool", "name": tool_name}
    else:
        kwargs["tool_choice"] = {"type": "auto"}
        if effort:
            kwargs["output_config"] = {"effort": effort}

    content = user if forced else f"{user}\n\nAnswer only by calling the `{tool_name}` tool."
    for attempt in range(2):
        if forced:
            resp = client().messages.create(messages=[{"role": "user", "content": content}], **kwargs)
        else:
            # Server-side refusal fallback (routes a declined request to another model).
            resp = client().beta.messages.create(
                messages=[{"role": "user", "content": content}],
                betas=["server-side-fallback-2026-07-01"],
                extra_body={"fallbacks": "default"},
                **kwargs,
            )
        _record(resp)
        if resp.stop_reason == "refusal":
            raise LLMError(f"model refused ({tool_name})")
        for block in resp.content:
            if block.type == "tool_use" and block.name == tool_name:
                data = block.input
                if isinstance(data, str):
                    data = json.loads(data)
                return data
        log.warning("no %s tool call (stop_reason=%s), attempt %d", tool_name, resp.stop_reason, attempt + 1)
    raise LLMError(f"model did not call {tool_name}")
