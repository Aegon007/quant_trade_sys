"""Small LLM router used only for narration and notification delivery.

Valuation routing and research analysis use the remote LLM directly. The local
SLM is deliberately limited to rewriting already-structured facts.
"""

from __future__ import annotations

from typing import Mapping

from quant_core.llm import openai_compatible
from quant_core.notifications import notification_config as config_store


def list_llm_routes(config: Mapping, *, complexity: str = "narration") -> list[tuple[str, dict]]:
    normalized = config_store.normalize_notification_config(dict(config or {}))
    local = dict(normalized.get("local_slm", {}) or {})
    remote = dict(normalized.get("llm", {}) or {})
    order = (("local_slm", local), ("llm", remote)) if complexity in {"narration", "rewrite", "verbalize"} else (("llm", remote),)
    return [(name, route) for name, route in order if route.get("enabled") and route.get("base_url") and route.get("model")]


def select_llm_route(config: Mapping, *, complexity: str = "narration"):
    routes = list_llm_routes(config, complexity=complexity)
    return routes[0] if routes else ("", {})


def run_llm_task(messages, *, notification_config: Mapping, complexity: str = "narration", urlopen=None):
    attempts = []
    routes = list_llm_routes(notification_config, complexity=complexity)
    if not routes:
        return False, "没有可用的LLM路由", {"route_name": "", "model": "", "fallback_attempts": []}
    for route_name, route in routes:
        kwargs = {"urlopen": urlopen} if urlopen is not None else {}
        ok, response = openai_compatible.call_openai_compatible_chat(messages, route, **kwargs)
        if ok:
            return True, str(response).strip(), {"route_name": route_name, "model": route.get("model"), "fallback_attempts": attempts}
        attempts.append({"route_name": route_name, "model": route.get("model"), "error": str(response)})
    last = attempts[-1]
    return False, last["error"], {"route_name": last["route_name"], "model": last["model"], "fallback_attempts": attempts[:-1]}


def summarize_notification_message(*, delivery_type: str, subject: str, body: str, notification_config: Mapping, urlopen=None):
    messages = [
        {
            "role": "system",
            "content": (
                "你是估值研究系统的中文叙述层。把输入改写为适合Slack和Email阅读的自然中文。"
                "必须保留所有数字、结论和不确定性；不要使用Markdown表格或竖线；不要新增事实、价格或交易指令。"
            ),
        },
        {
            "role": "user",
            "content": f"消息类型：{delivery_type}\n标题：{subject}\n\n结构化内容：\n{body}",
        },
    ]
    return run_llm_task(messages, notification_config=notification_config, complexity="narration", urlopen=urlopen)
