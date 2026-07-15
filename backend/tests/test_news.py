from app.services.news import NewsDTO, deduplicate, news_fingerprint, normalize_url


def test_normalize_url_strips_tracking_and_trailing_slash():
    a = normalize_url("https://Example.com/story/?utm_source=x&id=7")
    b = normalize_url("https://example.com/story?id=7")
    assert a == b


def test_fingerprint_prefers_external_id():
    fp1 = news_fingerprint("finnhub", "123", "https://a.com/x", "标题 A")
    fp2 = news_fingerprint("finnhub", "123", "https://a.com/y", "标题 B")
    assert fp1 == fp2


def test_fingerprint_without_id_uses_url_and_title():
    fp1 = news_fingerprint("tavily", None, "https://a.com/x/", "同一 标题")
    fp2 = news_fingerprint("tavily", None, "https://a.com/x", "同一   标题")
    assert fp1 == fp2


def test_deduplicate_removes_cross_source_duplicates():
    items = [
        NewsDTO(provider="finnhub", ticker="NVDA", title="NVDA 大涨", url="https://x.com/a", external_id="1"),
        NewsDTO(provider="finnhub", ticker="NVDA", title="重复", url="https://x.com/b", external_id="1"),
        NewsDTO(provider="tavily", ticker="NVDA", title="别的", url="https://y.com/c"),
    ]
    unique = deduplicate(items)
    assert len(unique) == 2
