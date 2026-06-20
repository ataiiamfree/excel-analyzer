import asyncio
import json

from app.agent.next_actions import generate_next_actions, parse_next_actions_response


class FakeNextActionLLM:
    def __init__(self, response: str):
        self.response = response
        self.calls: list[dict] = []

    async def call(self, prompt: str, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        return self.response


class BrokenNextActionLLM:
    async def call(self, prompt: str, **kwargs):
        raise RuntimeError("llm unavailable")


def test_parse_next_actions_response_from_json_object():
    text = json.dumps(
        {
            "actions": [
                "按门店拆分销售额和客流趋势",
                "导出异常月份明细表",
                "补充销售额与客流量相关性图",
            ]
        },
        ensure_ascii=False,
    )

    actions = parse_next_actions_response(text)

    assert actions == [
        "按门店拆分销售额和客流趋势",
        "导出异常月份明细表",
        "补充销售额与客流量相关性图",
    ]


def test_parse_next_actions_response_strips_fence_dedupes_and_limits():
    response = """```json
    {"actions":["1. 按区域继续拆分趋势","按区域继续拆分趋势","输出明细表","补充折线图"]}
    ```"""

    actions = parse_next_actions_response(response)

    assert actions == ["按区域继续拆分趋势", "输出明细表", "补充折线图"]


def test_generate_next_actions_calls_llm_with_summary_only():
    llm = FakeNextActionLLM('{"actions":["按月份补充同比分析","导出趋势明细表"]}')

    actions = asyncio.run(
        generate_next_actions(
            llm_client=llm,
            query="按月汇总销售额和客流量",
            report="销售额 1 月 43 万，2 月 36 万，3 月 44 万。",
            steps=[{"step_id": "s1", "status": "done", "stdout": "生成了月度汇总"}],
            artifacts=[{"name": "monthly.csv", "kind": "csv"}],
        )
    )

    assert actions == ["按月份补充同比分析", "导出趋势明细表"]
    assert llm.calls
    assert llm.calls[0]["max_tokens"] == 500
    assert llm.calls[0]["thinking"] is False
    assert "monthly.csv" in llm.calls[0]["prompt"]


def test_generate_next_actions_returns_empty_on_failure():
    actions = asyncio.run(
        generate_next_actions(
            llm_client=BrokenNextActionLLM(),
            query="q",
            report="report",
            steps=[],
            artifacts=[],
        )
    )

    assert actions == []
