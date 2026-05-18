import json
import tempfile
import unittest
from pathlib import Path


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class LLMExplainerTests(unittest.TestCase):
    def setUp(self):
        from quant_core.llm import explainer

        self.module = explainer

    def test_select_llm_route_prefers_local_slm_for_narration_tasks(self):
        route_name, config = self.module.select_llm_route(
            {
                "local_slm": {"enabled": True, "base_url": "http://127.0.0.1:8000/v1", "model": "Qwen/Qwen3-0.6B"},
                "llm": {"enabled": True, "base_url": "https://api.openai.com/v1", "model": "gpt-5-mini"},
            },
            complexity="narration",
        )

        self.assertEqual(route_name, "local_slm")
        self.assertEqual(config["model"], "Qwen/Qwen3-0.6B")

    def test_select_llm_route_prefers_remote_llm_for_explanation_tasks(self):
        route_name, config = self.module.select_llm_route(
            {
                "local_slm": {"enabled": True, "base_url": "http://127.0.0.1:8000/v1", "model": "Qwen/Qwen3-0.6B"},
                "llm": {"enabled": True, "base_url": "https://api.openai.com/v1", "model": "gpt-5-mini"},
            },
            complexity="explanation",
        )

        self.assertEqual(route_name, "llm")
        self.assertEqual(config["model"], "gpt-5-mini")

    def test_explain_core_etf_decision_uses_cache_after_first_call(self):
        calls = {"count": 0}

        def fake_urlopen(request, timeout=0):
            calls["count"] += 1
            payload = {"choices": [{"message": {"content": "解释完成"}}]}
            return _FakeResponse(json.dumps(payload).encode("utf-8"))

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = str(Path(temp_dir) / "llm_summary_cache.json")
            config = {
                "local_slm": {
                    "enabled": True,
                    "provider": "openai",
                    "base_url": "http://127.0.0.1:8000/v1",
                    "api_key": "EMPTY",
                    "model": "Qwen/Qwen3-0.6B",
                }
            }
            kwargs = dict(
                symbol_row={
                    "symbol": "VOO",
                    "action": "ACCUMULATE",
                    "target_weight_pct": 55.0,
                    "target_weight_range_low_pct": 50.0,
                    "target_weight_range_high_pct": 60.0,
                    "rotation_score": 78.0,
                    "signal_reason": "趋势稳定且未超买",
                },
                notification_config=config,
                discipline_snapshot={"regime": "NORMAL", "summary": "可正常执行计划。"},
                change_feed={"generated_at": "2026-05-14T06:00:00", "high_items": []},
                cache_path=cache_path,
                urlopen=fake_urlopen,
            )
            ok1, text1, meta1 = self.module.explain_core_etf_decision(**kwargs)
            ok2, text2, meta2 = self.module.explain_core_etf_decision(**kwargs)

        self.assertTrue(ok1)
        self.assertTrue(ok2)
        self.assertEqual(text1, "解释完成")
        self.assertEqual(text2, "解释完成")
        self.assertFalse(meta1["cached"])
        self.assertTrue(meta2["cached"])
        self.assertEqual(calls["count"], 1)

    def test_narrate_change_feed_prefers_local_slm_and_uses_cache(self):
        calls = {"count": 0}

        def fake_urlopen(request, timeout=0):
            calls["count"] += 1
            payload = {"choices": [{"message": {"content": "本地转述完成"}}]}
            return _FakeResponse(json.dumps(payload).encode("utf-8"))

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = str(Path(temp_dir) / "llm_summary_cache.json")
            config = {
                "local_slm": {
                    "enabled": True,
                    "provider": "openai",
                    "base_url": "http://127.0.0.1:8000/v1",
                    "api_key": "EMPTY",
                    "model": "Qwen/Qwen3-0.6B",
                },
                "llm": {
                    "enabled": True,
                    "provider": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "sk-test",
                    "model": "gpt-5-mini",
                },
            }
            kwargs = dict(
                change_feed={
                    "generated_at": "2026-05-14T06:00:00",
                    "summary": {"high_count": 1, "medium_count": 0},
                    "high_items": [{"title": "纪律层状态切换", "message": "从 NORMAL 到 LIGHT"}],
                    "medium_items": [],
                },
                monthly_discipline_review={"status": "CAUTION", "summary": "IGNORE 天数上升。"},
                notification_config=config,
                cache_path=cache_path,
                urlopen=fake_urlopen,
            )
            ok1, text1, meta1 = self.module.narrate_change_feed(**kwargs)
            ok2, text2, meta2 = self.module.narrate_change_feed(**kwargs)

        self.assertTrue(ok1)
        self.assertTrue(ok2)
        self.assertEqual(text1, "本地转述完成")
        self.assertEqual(text2, "本地转述完成")
        self.assertEqual(meta1["route_name"], "local_slm")
        self.assertFalse(meta1["cached"])
        self.assertTrue(meta2["cached"])
        self.assertEqual(calls["count"], 1)

    def test_explain_discipline_review_prefers_remote_llm(self):
        calls = {"count": 0}

        def fake_urlopen(request, timeout=0):
            calls["count"] += 1
            payload = {"choices": [{"message": {"content": "远程解释完成"}}]}
            return _FakeResponse(json.dumps(payload).encode("utf-8"))

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = str(Path(temp_dir) / "llm_summary_cache.json")
            config = {
                "local_slm": {
                    "enabled": True,
                    "provider": "openai",
                    "base_url": "http://127.0.0.1:8000/v1",
                    "api_key": "EMPTY",
                    "model": "Qwen/Qwen3-0.6B",
                },
                "llm": {
                    "enabled": True,
                    "provider": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "sk-test",
                    "model": "gpt-5-mini",
                },
            }
            ok, text, meta = self.module.explain_discipline_review(
                review={
                    "month": "2026-05",
                    "status": "MONITOR",
                    "summary": "FOLLOW 和 IGNORE 基本均衡。",
                    "follow_days": 4,
                    "ignore_days": 2,
                    "rows": [{"检查项": "纪律状态", "观察": "MONITOR"}],
                    "notes": ["最近有少量计划外交易。"],
                },
                discipline_snapshot={"regime": "LIGHT"},
                latest_post_close_review={"executed_count": 1, "missed_count": 0, "unplanned_trade_count": 1},
                notification_config=config,
                cache_path=cache_path,
                urlopen=fake_urlopen,
            )

        self.assertTrue(ok)
        self.assertEqual(text, "远程解释完成")
        self.assertEqual(meta["route_name"], "llm")
        self.assertFalse(meta["cached"])
        self.assertEqual(calls["count"], 1)
