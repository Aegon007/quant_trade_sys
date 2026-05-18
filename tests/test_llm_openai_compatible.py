import io
import json
import unittest


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class OpenAICompatibleLLMTests(unittest.TestCase):
    def setUp(self):
        from quant_core.llm import openai_compatible

        self.module = openai_compatible

    def test_build_chat_completions_url_appends_endpoint(self):
        self.assertEqual(
            self.module.build_chat_completions_url({"base_url": "https://api.openai.com/v1"}),
            "https://api.openai.com/v1/chat/completions",
        )
        self.assertEqual(
            self.module.build_chat_completions_url({"base_url": "https://host/custom/chat/completions"}),
            "https://host/custom/chat/completions",
        )

    def test_call_openai_compatible_chat_returns_text(self):
        captured = {}

        def fake_urlopen(request, timeout=0):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["headers"] = dict(request.headers)
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            payload = {
                "choices": [
                    {
                        "message": {
                            "content": "OK"
                        }
                    }
                ]
            }
            return _FakeResponse(json.dumps(payload).encode("utf-8"))

        ok, message = self.module.call_openai_compatible_chat(
            [{"role": "user", "content": "hello"}],
            {
                "provider": "openai",
                "base_url": "https://api.openai.com/v1",
                "api_key": "secret",
                "model": "gpt-5-mini",
                "temperature": 0.1,
                "max_tokens": 64,
                "timeout_seconds": 9,
            },
            urlopen=fake_urlopen,
        )

        self.assertTrue(ok)
        self.assertEqual(message, "OK")
        self.assertEqual(captured["url"], "https://api.openai.com/v1/chat/completions")
        self.assertEqual(captured["timeout"], 9)
        self.assertEqual(captured["payload"]["model"], "gpt-5-mini")
        self.assertEqual(captured["payload"]["max_tokens"], 64)
        self.assertIn("Bearer secret", captured["headers"].get("Authorization", ""))

    def test_call_openai_compatible_chat_adds_openrouter_headers(self):
        captured = {}

        def fake_urlopen(request, timeout=0):
            captured["headers"] = dict(request.headers)
            payload = {"choices": [{"message": {"content": "OK"}}]}
            return _FakeResponse(json.dumps(payload).encode("utf-8"))

        ok, _message = self.module.call_openai_compatible_chat(
            [{"role": "user", "content": "hello"}],
            {
                "provider": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key": "secret",
                "model": "openai/gpt-4.1-mini",
                "site_url": "https://example.com",
                "app_name": "quant-trade-system",
            },
            urlopen=fake_urlopen,
        )

        self.assertTrue(ok)
        self.assertEqual(captured["headers"].get("Http-referer"), "https://example.com")
        self.assertEqual(captured["headers"].get("X-title"), "quant-trade-system")

    def test_inspect_openai_compatible_endpoint_detects_running_model(self):
        def fake_urlopen(request, timeout=0):
            payload = {
                "data": [
                    {"id": "Qwen/Qwen3-0.6B"},
                    {"id": "other-model"},
                ]
            }
            return _FakeResponse(json.dumps(payload).encode("utf-8"))

        result = self.module.inspect_openai_compatible_endpoint(
            {
                "enabled": True,
                "base_url": "http://127.0.0.1:8000/v1",
                "model": "Qwen/Qwen3-0.6B",
                "timeout_seconds": 3,
            },
            urlopen=fake_urlopen,
        )

        self.assertEqual(result["status"], "running")
        self.assertTrue(result["ok"])
        self.assertIn("Qwen/Qwen3-0.6B", result["models"])

    def test_inspect_openai_compatible_endpoint_detects_wrong_model(self):
        def fake_urlopen(request, timeout=0):
            payload = {"data": [{"id": "some-other-model"}]}
            return _FakeResponse(json.dumps(payload).encode("utf-8"))

        result = self.module.inspect_openai_compatible_endpoint(
            {
                "enabled": True,
                "base_url": "http://127.0.0.1:8000/v1",
                "model": "Qwen/Qwen3-0.6B",
            },
            urlopen=fake_urlopen,
        )

        self.assertEqual(result["status"], "wrong_model")
        self.assertFalse(result["ok"])

    def test_inspect_openai_compatible_endpoint_detects_not_running(self):
        def fake_urlopen(request, timeout=0):
            raise OSError("connection refused")

        result = self.module.inspect_openai_compatible_endpoint(
            {
                "enabled": True,
                "base_url": "http://127.0.0.1:8000/v1",
                "model": "Qwen/Qwen3-0.6B",
            },
            urlopen=fake_urlopen,
        )

        self.assertEqual(result["status"], "not_running")
        self.assertFalse(result["ok"])

    def test_test_local_narration_returns_text(self):
        captured = {}

        def fake_urlopen(request, timeout=0):
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            payload = {"choices": [{"message": {"content": "已自然转述。"}}]}
            return _FakeResponse(json.dumps(payload).encode("utf-8"))

        ok, message = self.module.test_local_narration(
            {
                "provider": "openai",
                "base_url": "http://127.0.0.1:8000/v1",
                "api_key": "EMPTY",
                "model": "Qwen/Qwen3-0.6B",
                "temperature": 0.1,
                "max_tokens": 220,
            },
            urlopen=fake_urlopen,
        )

        self.assertTrue(ok)
        self.assertEqual(message, "已自然转述。")
        self.assertEqual(captured["payload"]["model"], "Qwen/Qwen3-0.6B")


if __name__ == "__main__":
    unittest.main()
