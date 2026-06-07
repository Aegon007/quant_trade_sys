"""OpenAI-compatible LLM helpers."""

from .explainer import (
    build_core_etf_explanation_messages,
    build_satellite_explanation_messages,
    build_change_feed_messages,
    build_discipline_review_messages,
    build_news_summary_messages,
    explain_change_feed,
    explain_core_etf_decision,
    explain_satellite_candidate,
    explain_discipline_review,
    narrate_change_feed,
    narrate_discipline_review,
    narrate_news_summary,
    select_llm_route,
    summarize_explanation_cache,
)
from .openai_compatible import (
    build_chat_completions_url,
    build_models_url,
    call_openai_compatible_chat,
    inspect_openai_compatible_endpoint,
    test_local_narration,
    test_llm_connection,
)

__all__ = [
    "build_core_etf_explanation_messages",
    "build_satellite_explanation_messages",
    "build_change_feed_messages",
    "build_discipline_review_messages",
    "build_news_summary_messages",
    "build_chat_completions_url",
    "build_models_url",
    "call_openai_compatible_chat",
    "explain_change_feed",
    "explain_core_etf_decision",
    "explain_satellite_candidate",
    "explain_discipline_review",
    "inspect_openai_compatible_endpoint",
    "narrate_change_feed",
    "narrate_discipline_review",
    "narrate_news_summary",
    "select_llm_route",
    "summarize_explanation_cache",
    "test_local_narration",
    "test_llm_connection",
]
