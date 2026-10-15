"""Opt-in integration check for DeepSeek Function Calling."""

import os
from types import SimpleNamespace

import pytest

from finbridge.agent import AgentRequestError, FinancialAgent
from finbridge.config import load_settings


class TrackingCompletions:
    def __init__(self, completions):
        self.completions = completions
        self.tool_call_observed = False

    def create(self, **request):
        response = self.completions.create(**request)
        self.tool_call_observed |= bool(response.choices[0].message.tool_calls)
        return response


@pytest.mark.skipif(
    os.getenv("FINBRIDGE_LIVE_API_TEST") != "1",
    reason="set FINBRIDGE_LIVE_API_TEST=1 to make a real API request",
)
def test_live_model_calls_financial_tool():
    settings = load_settings()
    assert settings.api_configured, "DeepSeek API configuration is missing"

    agent = FinancialAgent(settings)
    tracker = TrackingCompletions(agent.client.chat.completions)
    agent.client.chat.completions = tracker
    try:
        answer = agent.chat(
            [
                {
                    "role": "user",
                    "content": "必须调用财务计算工具计算流动比率，不要自行心算。",
                }
            ],
            {
                "company_name": "模拟测试企业",
                "current_assets": 1_500_000,
                "current_liabilities": 1_000_000,
            },
        )
    except AgentRequestError as error:
        pytest.fail(str(error))

    assert tracker.tool_call_observed, "模型没有请求财务计算工具"
    assert "1.5" in answer, "模型最终回复没有说明工具算出的 1.50 倍流动比率"