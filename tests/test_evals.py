"""evals/run_eval.py 的记账逻辑测试（不调用模型）。

有后台子 agent 时，一次运行会产生多个 result 事件：total_cost_usd 和 modelUsage 是累计的，
顶层 usage、num_turns、permission_denials 是按段的，而且顶层 usage 只算主模型。
这里用一份从真实运行里摘出来的事件结构，守住"不少算子 agent、不少算轮数和拒绝"。

运行：python3 -m unittest discover -s tests
"""
import importlib.util
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("run_eval", os.path.join(ROOT, "evals", "run_eval.py"))
run_eval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_eval)


def result(turns, usage, model_usage, cost, denials):
    return {"type": "result", "num_turns": turns, "usage": usage, "modelUsage": model_usage,
            "total_cost_usd": cost, "permission_denials": [{}] * denials}


MODEL_USAGE = {  # 累计值，含子 agent 用的模型
    "main": {"inputTokens": 26, "outputTokens": 6351, "cacheReadInputTokens": 513401, "cacheCreationInputTokens": 19472},
    "sub": {"inputTokens": 6, "outputTokens": 1788, "cacheReadInputTokens": 16120, "cacheCreationInputTokens": 10599},
}


class AccountingTest(unittest.TestCase):
    def two_segments(self):
        return [
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "〔L3 · 用户指定〕"}]}},
            result(14, {"input_tokens": 22, "cache_creation_input_tokens": 17471, "cache_read_input_tokens": 422943,
                        "output_tokens": 5187}, MODEL_USAGE, 0.2848, 3),
            result(2, {"input_tokens": 4, "cache_creation_input_tokens": 2001, "cache_read_input_tokens": 90458,
                       "output_tokens": 1164}, MODEL_USAGE, 0.2848, 0),
        ]

    def test_tokens_include_the_subagent_model(self):
        u = run_eval.usage(run_eval.summarize(self.two_segments()))
        self.assertEqual(u["new"], (26 + 19472 + 6351) + (6 + 10599 + 1788))
        self.assertEqual(u["cache_read"], 513401 + 16120)
        self.assertEqual(u["output"], 6351 + 1788)

    def test_turns_and_denials_are_summed_across_segments(self):
        u = run_eval.usage(run_eval.summarize(self.two_segments()))
        self.assertEqual(u["turns"], 16)
        self.assertEqual(u["denied"], 3)

    def test_cost_is_not_double_counted(self):
        self.assertAlmostEqual(run_eval.usage(run_eval.summarize(self.two_segments()))["usd"], 0.2848)

    def test_single_result_without_model_usage_falls_back_to_usage(self):
        events = [result(3, {"input_tokens": 2, "cache_creation_input_tokens": 10, "cache_read_input_tokens": 100,
                             "output_tokens": 4}, None, 0.01, 0)]
        u = run_eval.usage(run_eval.summarize(events))
        self.assertEqual((u["new"], u["cache_read"], u["turns"]), (16, 100, 3))

    def test_first_line_comes_from_the_main_agent_only(self):
        events = [{"type": "assistant", "parent_tool_use_id": "x", "message": {"content": [{"type": "text", "text": "子 agent 说"}]}},
                  {"type": "assistant", "message": {"content": [{"type": "text", "text": "〔L2 · 依据〕\n正文"}]}}]
        self.assertEqual(run_eval.summarize(events)["first_line"], "〔L2 · 依据〕")


if __name__ == "__main__":
    unittest.main()
