"""
Compass — LLM Router using Nemotron-3 Nano.

Dispatches user messages to skills via native OpenAI function calling.
Probed and verified on Nebius Token Factory with nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B.
"""

import json
import logging
from typing import Any, Optional, Dict, Tuple
from openai import OpenAI, AsyncOpenAI
from backend.config import get_settings
from backend.skills import TOOL_DEFINITIONS

logger = logging.getLogger("compass.router")
settings = get_settings()

TOOLS = TOOL_DEFINITIONS


def get_openai_client() -> AsyncOpenAI:
    """Return configured AsyncOpenAI client for Nebius Token Factory."""
    return AsyncOpenAI(
        api_key=settings.NEBIUS_API_KEY,
        base_url=settings.NEBIUS_BASE_URL,
        timeout=15.0,
    )


async def route_message(
    message: str,
    history: Optional[list[dict[str, str]]] = None,
) -> Tuple[Optional[str], Optional[dict[str, Any]], str]:
    """Route a message through Nemotron-3 Nano using native tool calling.

    Returns:
        (skill_name, tool_arguments, text_response)
        - If a tool was chosen: ('add_task', {'title': ...}, '')
        - If regular chat: (None, None, 'Assistant text response')
    """
    client = get_openai_client()
    messages: Any = [
        {
            "role": "system",
            "content": (
                "You are Compass, an intelligent personal assistant. "
                "You maintain context across conversation history. "
                "When the user asks follow-up questions about recently created tasks, deadlines, or status, "
                "either call query_tasks with the relevant domain/project or answer directly from conversation history. "
                "When the user requests adding, scheduling, or tracking a task, action item, or deadline, "
                "call the add_task tool with properly extracted fields. "
                "For general inquiries or conversation, respond directly with helpful text."
            ),
        }
    ]

    if history:
        messages.extend(history)

    messages.append({"role": "user", "content": message})
    tools: Any = TOOLS

    try:
        response = await client.chat.completions.create(
            model=settings.ROUTER_MODEL,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            max_tokens=1024,
        )

        from backend.services.usage import record_usage
        usage = getattr(response, "usage", None)
        p_tok = usage.prompt_tokens if usage else max(len(message.split()) * 2, 64)
        c_tok = usage.completion_tokens if usage else 50
        record_usage(settings.ROUTER_MODEL, p_tok, c_tok)

        choice = response.choices[0]
        if choice.message.tool_calls:
            tc: Any = choice.message.tool_calls[0]
            func_name = getattr(getattr(tc, "function", None), "name", None) or getattr(tc, "name", "add_task")
            raw_args = getattr(getattr(tc, "function", None), "arguments", "{}") or "{}"

            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except Exception as e:
                logger.warning(f"Failed to parse function arguments JSON ({e}): {raw_args}")
                args = {"title": message}

            logger.info(f"Router invoked tool: {func_name} with args: {args}")
            return func_name, args, ""
        else:
            reply = choice.message.content or "How can I help you today?"
            return None, None, reply

    except Exception as e:
        logger.error(f"Nebius router invocation failed: {e}")
        # Fallback keyword routing for robustness
        msg_lower = message.lower()
        if "add task" in msg_lower or "add a task" in msg_lower or "new task" in msg_lower:
            return "add_task", {"title": message.replace("add a task:", "").replace("add task:", "").strip()}, ""
        if history:
            for h in reversed(history):
                content = h.get("content", "")
                if any(term in content.lower() for term in ("task", "deliverable", "due", "demo", "submit", "video")):
                    if any(term in msg_lower for term in ("due", "when", "deadline", "date")):
                        return "query_tasks", {}, f"Checking your task due dates based on previous context: {content}"
                    return "query_tasks", {}, f"Referencing previous task: {content}"
        if any(term in msg_lower for term in ("task", "due", "deliverable", "deadline")):
            return "query_tasks", {}, ""
        return None, None, "I'm having a moment — could you try that again? I'm here to help!"
