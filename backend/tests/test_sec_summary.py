from types import SimpleNamespace

import pytest

from app.services import sec_extract


def _settings():
    return SimpleNamespace(
        translation_api_key="translation-key",
        translation_base_url="https://example.test/v1",
        translation_model="claude-haiku-4-5-20251001",
    )


def test_empty_text_skips_external_client(monkeypatch):
    import openai

    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: pytest.fail("不应调用翻译接口"))
    assert sec_extract.summarize_sec_event("Item 2.02", "8-K", "") == ("", None)
    assert sec_extract.summarize_sec_event("Item 2.02", "8-K", "   ") == ("", None)


def test_summarizes_full_text_with_haiku_stack(monkeypatch):
    import openai

    captured = {}

    class Completions:
        def create(self, **kwargs):
            captured["request"] = kwargs
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="**核心摘要**\n- 关键事实"))]
            )

    class Client:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = SimpleNamespace(completions=Completions())

    monkeypatch.setattr(sec_extract, "get_settings", _settings)
    monkeypatch.setattr(openai, "OpenAI", Client)

    text = "Apple Inc. announced record fourth quarter revenue of $94.9 billion."
    summary, model = sec_extract.summarize_sec_event("Results of Operations", "8-K", text)

    assert summary == "**核心摘要**\n- 关键事实"
    assert model == "claude-haiku-4-5-20251001"
    assert captured["client"]["base_url"] == "https://example.test/v1"
    assert captured["request"]["model"] == "claude-haiku-4-5-20251001"
    # 原文整段进入 user 消息，供全文翻译+总结
    user_content = captured["request"]["messages"][-1]["content"]
    assert text in user_content
    assert "8-K" in user_content
    assert "Results of Operations" in user_content
    # system prompt 存在硬约束（不臆造）
    system_content = captured["request"]["messages"][0]["content"]
    assert "原文未提供" in system_content


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.setattr(
        sec_extract, "get_settings", lambda: SimpleNamespace(translation_api_key="")
    )
    with pytest.raises(RuntimeError, match="TRANSLATION_API_KEY"):
        sec_extract.summarize_sec_event("Item 2.02", "8-K", "some filing text")


def test_empty_response_raises(monkeypatch):
    import openai

    class Completions:
        def create(self, **kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=""))])

    class Client:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=Completions())

    monkeypatch.setattr(sec_extract, "get_settings", _settings)
    monkeypatch.setattr(openai, "OpenAI", Client)

    with pytest.raises(ValueError):
        sec_extract.summarize_sec_event("Item 2.02", "8-K", "some filing text")
