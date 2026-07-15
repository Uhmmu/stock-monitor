from types import SimpleNamespace

from app.services import relevance


def test_parse_extracts_scores_and_clamps():
    content = '[{"i":0,"rel":1.5,"sent":-2},{"i":1,"rel":0.4,"sent":0.2}]'
    scores = relevance._parse(content)
    assert scores[0] == (1.0, -1.0)
    assert scores[1] == (0.4, 0.2)


def test_score_news_single_batched_request(monkeypatch):
    calls = {"n": 0}

    class Completions:
        def create(self, **kwargs):
            calls["n"] += 1
            calls["content"] = kwargs["messages"][-1]["content"]
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(
                    content='[{"i":0,"rel":0.9,"sent":0.5},{"i":1,"rel":0.1,"sent":0.0}]'))]
            )

    class Client:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=Completions())

    settings = SimpleNamespace(openai_api_key="k", openai_base_url="https://x/v1",
                               model_simple="gpt-5.4-mini", translation_batch_size=20)
    monkeypatch.setattr(relevance, "get_settings", lambda: settings)
    monkeypatch.setattr(relevance, "OpenAI", Client)

    scores = relevance.score_news("AAPL", [("t0", "s0"), ("t1", "s1")])

    assert calls["n"] == 1  # 两条合并为一次请求，绝不逐条发
    assert "[0]" in calls["content"] and "[1]" in calls["content"]
    assert scores == {0: (0.9, 0.5), 1: (0.1, 0.0)}


def test_score_news_empty_without_key(monkeypatch):
    settings = SimpleNamespace(openai_api_key="", openai_base_url="", model_simple="m", translation_batch_size=20)
    monkeypatch.setattr(relevance, "get_settings", lambda: settings)
    assert relevance.score_news("AAPL", [("t", "s")]) == {}
