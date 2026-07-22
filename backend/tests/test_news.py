from datetime import UTC, datetime, timedelta

from app.services.news import NewsDTO, deduplicate, news_fingerprint, normalize_title, normalize_url, prepare_news


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


def test_title_and_url_normalization_are_stable():
    assert normalize_url("https://example.com/a?ref=x&utm_source=y&id=1") == "https://example.com/a?id=1"
    assert normalize_title("Breaking: Fed—Holds Rates Steady - Reuters") == "fed-holds rates steady"


def test_market_pipeline_clusters_and_diversifies():
    now = datetime.now(UTC)
    rows = [
        NewsDTO("finnhub", "__MARKET__", "Fed holds rates steady", "https://r.test/1", source="Reuters", published_at=now),
        NewsDTO("marketaux", "__MARKET__", "Federal Reserve holds interest rates steady", "https://b.test/2", source="Bloomberg", published_at=now + timedelta(minutes=1)),
        NewsDTO("finnhub", "__MARKET__", "Oil rises as OPEC weighs supply", "https://r.test/3", source="Reuters", published_at=now),
    ]
    final, stats = prepare_news(rows, scope="market", now=now, limit=20)
    assert len(final) == 2
    assert stats["clustered"] == 1
    assert {row.topic for row in final} >= {"央行与利率", "能源与大宗商品"}


def test_market_diversity_soft_limits_backfill_articles_without_tickers():
    now = datetime.now(UTC)
    labels = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet"]
    rows = [
        NewsDTO("finnhub", "__MARKET__", f"Market update {label} oil", f"https://r.test/{index}", external_id=str(index), source="Reuters", published_at=now)
        for index, label in enumerate(labels)
    ]
    final, _ = prepare_news(rows, scope="market", now=now, limit=8)
    assert len(final) == 8
