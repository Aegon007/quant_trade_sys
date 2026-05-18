from __future__ import annotations

import json
import urllib.request


def build_chat_completions_url(config) -> str:
    base_url = str((config or {}).get("base_url") or "").strip().rstrip("/")
    if not base_url:
        return ""
    if base_url.endswith("/chat/completions"):
        return base_url
    if base_url.endswith("/v1"):
        return f"{base_url}/chat/completions"
    return f"{base_url}/chat/completions"


def build_models_url(config) -> str:
    base_url = str((config or {}).get("base_url") or "").strip().rstrip("/")
    if not base_url:
        return ""
    if base_url.endswith("/chat/completions"):
        return base_url[: -len("/chat/completions")] + "/models"
    if base_url.endswith("/v1"):
        return f"{base_url}/models"
    if base_url.endswith("/models"):
        return base_url
    return f"{base_url}/models"


def _extract_response_text(payload) -> str:
    choices = list((payload or {}).get("choices", []) or [])
    if not choices:
        return ""
    first = dict(choices[0] or {})
    message = dict(first.get("message") or {})
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and str(item.get("type") or "") == "text":
                text = str(item.get("text") or "").strip()
                if text:
                    parts.append(text)
        return "\n".join(parts).strip()
    return ""


def call_openai_compatible_chat(
    messages,
    llm_config,
    *,
    urlopen=urllib.request.urlopen,
    extra_headers=None,
):
    config = dict(llm_config or {})
    api_key = str(config.get("api_key") or "").strip()
    model = str(config.get("model") or "").strip()
    url = build_chat_completions_url(config)
    timeout = int(config.get("timeout_seconds") or 30)

    if not url:
        return False, "LLM base URL 为空"
    if not api_key:
        return False, "LLM API key 为空"
    if not model:
        return False, "LLM model 为空"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if str(config.get("provider") or "").strip().lower() == "openrouter":
        site_url = str(config.get("site_url") or "").strip()
        app_name = str(config.get("app_name") or "").strip()
        if site_url:
            headers["HTTP-Referer"] = site_url
        if app_name:
            headers["X-Title"] = app_name
    headers.update(dict(extra_headers or {}))

    payload = {
        "model": model,
        "messages": list(messages or []),
        "temperature": float(config.get("temperature", 0.2) or 0.0),
        "max_tokens": int(config.get("max_tokens", 300) or 1),
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except Exception as exc:
        return False, f"LLM 调用失败: {exc}"

    try:
        parsed = json.loads(raw)
    except Exception as exc:
        return False, f"LLM 返回无法解析: {exc}"

    text = _extract_response_text(parsed)
    if not text:
        return False, "LLM 返回为空"
    return True, text


def test_llm_connection(llm_config, *, urlopen=urllib.request.urlopen):
    return call_openai_compatible_chat(
        [
            {"role": "system", "content": "You are a connectivity test assistant."},
            {"role": "user", "content": "Reply with exactly: OK"},
        ],
        llm_config,
        urlopen=urlopen,
    )


def test_local_narration(llm_config, *, urlopen=urllib.request.urlopen):
    return call_openai_compatible_chat(
        [
            {
                "role": "system",
                "content": "You are a concise financial narration assistant. Rewrite only from provided structured reasons and do not add new facts.",
            },
            {
                "role": "user",
                "content": (
                    "请把下面这组结构化原因转述成一句自然、简短的中文：\n"
                    "- 风险状态: NORMAL\n"
                    "- 动作: HOLD\n"
                    "- 原因: 趋势稳定，且今天没有新的高优先级变化"
                ),
            },
        ],
        llm_config,
        urlopen=urlopen,
    )


def inspect_openai_compatible_endpoint(llm_config, *, urlopen=urllib.request.urlopen):
    config = dict(llm_config or {})
    enabled = bool(config.get("enabled"))
    base_url = str(config.get("base_url") or "").strip()
    expected_model = str(config.get("model") or "").strip()
    timeout = min(int(config.get("timeout_seconds") or 30), 5)

    if not enabled:
        return {
            "status": "disabled",
            "label": "DISABLED",
            "ok": False,
            "message": "本地 SLM 未启用",
            "models": [],
            "expected_model": expected_model,
            "base_url": base_url,
        }
    if not base_url:
        return {
            "status": "not_configured",
            "label": "NOT CONFIGURED",
            "ok": False,
            "message": "Base URL 为空",
            "models": [],
            "expected_model": expected_model,
            "base_url": base_url,
        }

    models_url = build_models_url(config)
    if not models_url:
        return {
            "status": "not_configured",
            "label": "NOT CONFIGURED",
            "ok": False,
            "message": "Models endpoint 无法构造",
            "models": [],
            "expected_model": expected_model,
            "base_url": base_url,
        }

    request = urllib.request.Request(models_url, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except Exception as exc:
        return {
            "status": "not_running",
            "label": "NOT RUNNING",
            "ok": False,
            "message": f"无法连接本地服务: {exc}",
            "models": [],
            "expected_model": expected_model,
            "base_url": base_url,
        }

    try:
        parsed = json.loads(raw)
    except Exception as exc:
        return {
            "status": "wrong_endpoint",
            "label": "WRONG ENDPOINT",
            "ok": False,
            "message": f"返回内容无法解析为 OpenAI-compatible /models: {exc}",
            "models": [],
            "expected_model": expected_model,
            "base_url": base_url,
        }

    models = []
    for item in list((parsed or {}).get("data", []) or []):
        if isinstance(item, dict):
            model_id = str(item.get("id") or "").strip()
            if model_id:
                models.append(model_id)

    if not models:
        return {
            "status": "wrong_endpoint",
            "label": "WRONG ENDPOINT",
            "ok": False,
            "message": "接口可达，但没有返回模型列表",
            "models": [],
            "expected_model": expected_model,
            "base_url": base_url,
        }

    if expected_model and expected_model not in models:
        return {
            "status": "wrong_model",
            "label": "WRONG MODEL",
            "ok": False,
            "message": f"服务在线，但未暴露配置中的模型 `{expected_model}`",
            "models": models,
            "expected_model": expected_model,
            "base_url": base_url,
        }

    return {
        "status": "running",
        "label": "RUNNING",
        "ok": True,
        "message": "本地 SLM 服务在线，且模型匹配",
        "models": models,
        "expected_model": expected_model,
        "base_url": base_url,
    }
