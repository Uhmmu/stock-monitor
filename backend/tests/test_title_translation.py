from types import SimpleNamespace

import pytest

from app.services import title_translation


def test_title_hash_uses_exact_original_title():
    assert title_translation.title_input_hash("NVIDIA rises") == title_translation.title_input_hash("NVIDIA rises")
    assert title_translation.title_input_hash("NVIDIA rises") != title_translation.title_input_hash("NVIDIA rises ")


def test_detects_chinese_title():
    assert title_translation.is_chinese_title("英伟达发布新芯片")
    assert title_translation.is_chinese_title("NVIDIA 发布 Blackwell")
    assert not title_translation.is_chinese_title("NVIDIA unveils Blackwell")


def test_chinese_title_skips_external_client(monkeypatch):
    monkeypatch.setattr(title_translation, "OpenAI", lambda **kwargs: pytest.fail("不应调用翻译接口"))
    assert title_translation.translate_title("英伟达发布新芯片") == ("英伟达发布新芯片", None)


def test_translates_only_title_with_independent_client(monkeypatch):
    captured = {}

    class Completions:
        def create(self, **kwargs):
            captured["request"] = kwargs
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='**英伟达股价上涨**'))]
            )

    class Client:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = SimpleNamespace(completions=Completions())

    settings = SimpleNamespace(
        translation_api_key="translation-key",
        translation_base_url="https://example.test/v1",
        translation_model="claude-haiku-4-5-20251001",
    )
    monkeypatch.setattr(title_translation, "get_settings", lambda: settings)
    monkeypatch.setattr(title_translation, "OpenAI", Client)

    translated, model = title_translation.translate_title("NVIDIA shares rise")

    assert translated == "英伟达股价上涨"
    assert model == "claude-haiku-4-5-20251001"
    assert captured["client"]["base_url"] == "https://example.test/v1"
    assert captured["request"]["messages"][-1]["content"] == "NVIDIA shares rise"
    assert len(captured["request"]["messages"][-1]["content"].splitlines()) == 1


def test_rejects_multiline_response():
    with pytest.raises(ValueError, match="格式无效"):
        title_translation._clean_translation("翻译结果\n额外解释")
