import json
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


def test_analysis_falls_back_to_haiku_on_primary_503(monkeypatch):
    calls = []

    class ServiceUnavailable(RuntimeError):
        status_code = 503

    def client(model, error=None):
        class Completions:
            def create(self, **kwargs):
                calls.append(kwargs["model"])
                if error:
                    raise error
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="回退摘要"))])

        return SimpleNamespace(chat=SimpleNamespace(completions=Completions())), model

    monkeypatch.setattr(llm, "_client_and_model", lambda tier: client("gpt-5.6-luna", ServiceUnavailable()))
    monkeypatch.setattr(llm, "_translation_client_and_model", lambda: client("claude-haiku-4-5-20251001"))

    text, model = llm.generate_analysis("Pulse", "evidence", fallback_to_translation=True)

    assert (text, model) == ("回退摘要", "claude-haiku-4-5-20251001")
    assert calls == ["gpt-5.6-luna", "claude-haiku-4-5-20251001"]


def _news_payload():
    return {
        "summary_zh": "公司公布了新的经营安排。",
        "key_points": ["公司公布经营安排", "报道说明执行范围", "原文未提供行情数据"],
        "companies": ["Example Corp"],
        "tickers": ["EXM"],
        "industries": ["Technology"],
        "event_type": "management",
        "sentiment": "neutral",
        "market_impact": "数据不足",
        "importance": 60,
        "source_quality": "model-must-not-infer",
        "confidence": 0.7,
        "facts": ["公司公布了新的经营安排。"],
    }


def test_news_summary_uses_luna_structured_json_contract(monkeypatch):
    captured = {}

    class Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=json.dumps(_news_payload()))
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18),
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setattr(llm, "_client_and_model", lambda tier: (client, "gpt-5.6-luna"))

    analysis, model, usage = llm.summarize_news(
        "Title", "Article body", source_quality="medium", known_tickers=["AAPL"]
    )

    assert analysis["summary_zh"] == "公司公布了新的经营安排。"
    assert analysis["source_quality"] == "medium"
    assert analysis["importance"] == 60
    assert model == "gpt-5.6-luna"
    assert usage == {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}
    assert captured["temperature"] == 0
    schema = captured["response_format"]
    assert schema["type"] == "json_schema"
    assert schema["json_schema"]["strict"] is True
    assert "summary_zh" in schema["json_schema"]["schema"]["required"]
    assert "Article body" in captured["messages"][1]["content"]
    assert "来源质量：medium" in captured["messages"][1]["content"]
    assert "已知关联证券代码：AAPL" in captured["messages"][1]["content"]
    assert "每个键都必须存在" in captured["messages"][0]["content"]
    assert "event_type` 只能是 earnings" in captured["messages"][0]["content"]


def test_news_summary_uses_key_points_when_provider_omits_facts(monkeypatch):
    payload = _news_payload()
    payload.pop("facts")

    class Completions:
        def create(self, **kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setattr(llm, "_client_and_model", lambda tier: (client, "gpt-5.6-luna"))

    analysis, _, _ = llm.summarize_news("Title", "Article body")

    assert analysis["facts"] == payload["key_points"]


def test_news_summary_rejects_english_summary(monkeypatch):
    payload = _news_payload()
    payload["summary_zh"] = "English summary only"

    class Completions:
        def create(self, **kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setattr(llm, "_client_and_model", lambda tier: (client, "gpt-5.6-luna"))

    try:
        llm.summarize_news("Title", "Article body")
    except ValueError as exc:
        assert "中文摘要" in str(exc)
    else:
        raise AssertionError("English-only summary must fail validation")


def test_news_summary_rejects_nonstandard_enums(monkeypatch):
    payload = _news_payload()
    payload["event_type"] = "company_update"

    class Completions:
        def create(self, **kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setattr(llm, "_client_and_model", lambda tier: (client, "gpt-5.6-luna"))

    analysis, _, _ = llm.summarize_news("Title", "Article body")

    assert analysis["event_type"] == "other"


def test_news_summary_normalizes_compatible_endpoint_schema_drift(monkeypatch):
    payload = {
        "title": "extra field",
        "summary_zh": "公司公布了新的经营安排。",
        "key_points": ["要点一", "要点二"],
        "market_impact": {"analysis": "原文未提供行情数据"},
        "importance": "61.4",
        "confidence": "0.7",
        "facts": [f"事实 {index}" for index in range(14)],
        "source_quality": "model-value",
    }

    class Completions:
        def create(self, **kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setattr(llm, "_client_and_model", lambda tier: (client, "gpt-5.6-luna"))

    analysis, _, _ = llm.summarize_news("Title", "Article body", source_quality="low")

    assert analysis["companies"] == []
    assert analysis["event_type"] == "other"
    assert analysis["sentiment"] == "neutral"
    assert analysis["market_impact"] == "原文未提供行情数据"
    assert analysis["importance"] == 61
    assert len(analysis["facts"]) == 12
    assert analysis["source_quality"] == "low"
