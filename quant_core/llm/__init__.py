"""OpenAI-compatible LLM helpers for valuation research."""

from .explainer import list_llm_routes, run_llm_task, select_llm_route, summarize_notification_message
from .openai_compatible import (
    build_chat_completions_url,
    build_models_url,
    call_openai_compatible_chat,
    inspect_openai_compatible_endpoint,
    test_local_narration,
    test_llm_connection,
)

__all__ = [
    "build_chat_completions_url",
    "build_models_url",
    "call_openai_compatible_chat",
    "inspect_openai_compatible_endpoint",
    "list_llm_routes",
    "run_llm_task",
    "select_llm_route",
    "summarize_notification_message",
    "test_local_narration",
    "test_llm_connection",
]
