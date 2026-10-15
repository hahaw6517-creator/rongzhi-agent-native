import json
from types import SimpleNamespace

import pytest

from finbridge.agent import (
    AgentConfigurationError,
    FinancialAgent,
    execute_financial_tool,
)
from finbridge.config import Settings


def test_financial_tool_calculates_only_validated_metric():
    result = execute_financial_tool(
        {"metric": "debt_to_asset_ratio", "total_liabilities": 25, "total_assets": 100}
    )

    assert result["value"] == pytest.approx(0.25)
    assert result["display"] == "25.00%"


@pytest.mark.parametrize(
    "arguments",
    [
        {"metric": "current_ratio", "current_assets": "12", "current_liabilities": 4},
        {"metric": "current_ratio", "current_assets": True, "current_liabilities": 4},
        {"metric": "current_ratio", "current_assets": 10, "current_liabilities": 0},
        {"metric": "net_profit_margin", "net_profit": 3},
        {"metric": "unknown", "value": 1},
        {"metric": "debt_to_asset_ratio", "total_assets": 10, "total_liabilities": 2, "revenue": 4},
        {"metric": "debt_to_asset_ratio", "total_assets": 1e30, "total_liabilities": 2},
    ],
)
def test_financial_tool_rejects_invalid_arguments(arguments):
    with pytest.raises(ValueError):
        execute_financial_tool(arguments)


def test_agent_requires_api_configuration():
    with pytest.raises(AgentConfigurationError):
        FinancialAgent(Settings(api_key=None, base_url="https://api.deepseek.com", model="deepseek-chat"))


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []

    def model_dump(self, exclude_none=True):
        result = {"role": "assistant", "tool_calls": []}
        for call in self.tool_calls:
            result["tool_calls"].append(
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.function.name, "arguments": call.function.arguments},
                }
            )
        if self.content is not None:
            result["content"] = self.content
        return result


class FakeCompletions:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def create(self, **request):
        self.requests.append(request)
        return SimpleNamespace(choices=[SimpleNamespace(message=next(self.responses))])


def make_tool_call(arguments):
    return SimpleNamespace(
        id="call_finance_1",
        function=SimpleNamespace(
            name="calculate_financial_metric",
            arguments=json.dumps(arguments),
        ),
    )


def test_agent_completes_model_tool_model_round_trip():
    completions = FakeCompletions(
        [
            FakeMessage(
                tool_calls=[
                    make_tool_call(
                        {
                            "metric": "current_ratio",
                            "current_assets": 150,
                            "current_liabilities": 100,
                        }
                    )
                ]
            ),
            FakeMessage(content="流动比率为 1.50 倍。"),
        ]
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    agent = FinancialAgent(
        Settings(api_key="test-key", base_url="https://api.deepseek.com", model="deepseek-chat"),
        client=client,
    )

    answer = agent.chat(
        [{"role": "user", "content": "请计算流动比率"}],
        {"current_assets": 150, "current_liabilities": 100},
    )

    assert answer == "流动比率为 1.50 倍。"
    assert len(completions.requests) == 2
    tool_messages = [message for message in completions.requests[1]["messages"] if message["role"] == "tool"]
    assert json.loads(tool_messages[0]["content"])["value"] == pytest.approx(1.5)
    assert completions.requests[0]["tools"][0]["type"] == "function"


def test_agent_stops_after_tool_call_limit():
    def repeated_call(call_id):
        return SimpleNamespace(
            id=call_id,
            function=SimpleNamespace(
                name="calculate_financial_metric",
                arguments=json.dumps(
                    {"metric": "current_ratio", "current_assets": 150, "current_liabilities": 100}
                ),
            ),
        )

    completions = FakeCompletions(
        [
            FakeMessage(tool_calls=[repeated_call("call_1")]),
            FakeMessage(tool_calls=[repeated_call("call_2")]),
        ]
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    agent = FinancialAgent(
        Settings(api_key="test-key", base_url="https://api.deepseek.com", model="deepseek-chat"),
        client=client,
        max_tool_calls=1,
    )

    answer = agent.chat([], {})

    assert "最多 1 次" in answer
    assert len(completions.requests) == 2