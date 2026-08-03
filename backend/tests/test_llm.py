from types import SimpleNamespace

import app.services.llm as llm
from app.services.llm import (
    MOVEMENT_SYSTEM_PROMPT,
    POST_EARNINGS_SYSTEM_PROMPT,
    POSTMARKET_SYSTEM_PROMPT,
    PRE_EARNINGS_SYSTEM_PROMPT,
    PREMARKET_SYSTEM_PROMPT,
    get_system_prompt,
)


def test_report_type_prompt_routing():
    expected = {
        "movement": MOVEMENT_SYSTEM_PROMPT,
        "premarket": PREMARKET_SYSTEM_PROMPT,
        "postmarket": POSTMARKET_SYSTEM_PROMPT,
        "earnings_before": PRE_EARNINGS_SYSTEM_PROMPT,
        "earnings_after": POST_EARNINGS_SYSTEM_PROMPT,
    }
    for report_type, prompt in expected.items():
        routed = get_system_prompt(report_type)
        assert routed.startswith(prompt)
        assert "不得输出模板占位符" in routed
        assert "不构成投资建议" in routed


def test_unknown_report_type_uses_safe_default():
    prompt = get_system_prompt("unknown")
    assert "严谨的美股信息分析员" in prompt
    assert "输入未提供" in prompt


def test_news_summary_uses_low_latency_translation_stack(monkeypatch):
    captured = {}

    class Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="- 中文要点"))]
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setattr(llm, "_translation_client_and_model", lambda: (client, "haiku-test"))

    summary, model = llm.summarize_news("Title", "Article body")

    assert summary == "- 中文要点"
    assert model == "haiku-test"
    assert captured["temperature"] == 0
    assert "Article body" in captured["messages"][1]["content"]


def test_news_summary_retries_when_provider_ignores_chinese_requirement(monkeypatch):
    replies = iter(["- English summary only", "- 中文要点已经修正"])
    calls = []

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=next(replies)))]
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setattr(llm, "_translation_client_and_model", lambda: (client, "haiku-test"))

    summary, _ = llm.summarize_news("Title", "Article body")

    assert summary == "- 中文要点已经修正"
    assert len(calls) == 2
    assert "不是中文" in calls[1]["messages"][-1]["content"]
