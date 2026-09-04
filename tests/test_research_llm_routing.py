import unittest
from unittest.mock import patch

from quant_core.llm.explainer import run_llm_task


class ResearchLlmRoutingTests(unittest.TestCase):
    @patch("quant_core.llm.explainer.openai_compatible.call_openai_compatible_chat")
    def test_narration_falls_back_from_local_to_remote(self, call):
        call.side_effect = [(False, "local unavailable"), (True, "远程转述")]
        ok, result, meta = run_llm_task(
            [{"role": "user", "content": "test"}],
            notification_config={
                "local_slm": {"enabled": True, "base_url": "http://local/v1", "api_key": "x", "model": "small"},
                "llm": {"enabled": True, "base_url": "https://remote/v1", "api_key": "x", "model": "large"},
            },
            complexity="narration",
        )
        self.assertTrue(ok)
        self.assertEqual(result, "远程转述")
        self.assertEqual(meta["route_name"], "llm")
        self.assertEqual(len(meta["fallback_attempts"]), 1)

    @patch("quant_core.llm.explainer.openai_compatible.call_openai_compatible_chat")
    def test_complex_research_uses_remote_first(self, call):
        call.return_value = (True, "深度解释")
        ok, _, meta = run_llm_task(
            [{"role": "user", "content": "test"}],
            notification_config={
                "local_slm": {"enabled": True, "base_url": "http://local/v1", "api_key": "x", "model": "small"},
                "llm": {"enabled": True, "base_url": "https://remote/v1", "api_key": "x", "model": "large"},
            },
            complexity="research",
        )
        self.assertTrue(ok)
        self.assertEqual(meta["route_name"], "llm")
        self.assertEqual(call.call_args.args[1]["model"], "large")


if __name__ == "__main__":
    unittest.main()
