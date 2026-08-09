import json
from types import SimpleNamespace

import httpx

import app.services.article_fetch as article_fetch
from app.services.article_fetch import ArticleFetchResult, _extract_main_text


def test_extract_prefers_newsarticle_json_ld():
    body = "这是结构化新闻正文。" * 30
    html = f'''<html><head><script type="application/ld+json">{{
      "@type": "NewsArticle", "articleBody": "{body}"
    }}</script></head><body><nav>{'导航链接 ' * 100}</nav><p>推荐内容而非正文</p></body></html>'''

    assert _extract_main_text(html) == body


def test_extract_removes_common_recommendation_and_cookie_blocks():
    article = "Company revenue increased while management maintained guidance. " * 8
    html = f'''<main><div class="cookie-banner">{'Cookie policy ' * 40}</div>
      <article><p>{article}</p><div class="related-stories"><p>{'Related story ' * 40}</p></div></article>
    </main>'''

    result = _extract_main_text(html)

    assert result is not None
    assert "Company revenue" in result
    assert "Related story" not in result
    assert "Cookie policy" not in result


def test_extract_does_not_let_short_recommendation_article_shadow_body():
    body = "Revenue increased and management explained the operating drivers in detail. " * 12
    html = f'''<body>
      <article><p>Short promoted card that must not be selected as the story body.</p></article>
      <main><section class="entry-content"><p>{body}</p></section></main>
    </body>'''

    result = _extract_main_text(html)

    assert result is not None
    assert "operating drivers" in result


def _response(url: str, html: str, *, content_type: str = "text/html; charset=utf-8"):
    return SimpleNamespace(
        headers={"content-type": content_type},
        status_code=200,
        url=url,
        text=html,
        raise_for_status=lambda: None,
    )


def _browser_result(url: str, content: str) -> ArticleFetchResult:
    return ArticleFetchResult(
        url=url,
        final_url="https://publisher.example/story",
        title="Publisher headline",
        content=content,
        method="playwright",
        success=True,
        quality=0.82,
    )


def test_fetch_article_returns_normalized_http_result(monkeypatch):
    body = "The company reported operating progress and maintained its outlook. " * 12
    monkeypatch.setattr(
        article_fetch.httpx,
        "get",
        lambda *args, **kwargs: _response(
            "https://publisher.example/story", f"<article><h1>Headline</h1><p>{body}</p></article>"
        ),
    )

    result = article_fetch.fetch_article("https://publisher.example/story")

    assert result.success is True
    assert result.method == "reader"
    assert result.final_url == "https://publisher.example/story"
    assert result.title == "Headline"
    assert result.content and len(result.content) >= 400
    assert 0 < result.quality <= 1
    assert result.quality_score == result.quality
    assert result.latency_ms >= 0
    assert result.metadata["domain_policy"] == "http_then_playwright"


def test_fetch_article_labels_structured_json_ld_as_http(monkeypatch):
    body = "The structured article body contains the publisher's complete report. " * 12
    payload = json.dumps({"@type": "NewsArticle", "headline": "Headline", "articleBody": body})
    html = f'<script type="application/ld+json">{payload}</script>'
    monkeypatch.setattr(
        article_fetch.httpx,
        "get",
        lambda *args, **kwargs: _response("https://publisher.example/story", html),
    )

    result = article_fetch.fetch_article("https://publisher.example/story")

    assert result.success is True
    assert result.method == "http"


def test_fetch_article_falls_back_to_bounded_browser_result(monkeypatch):
    monkeypatch.setattr(
        article_fetch.httpx,
        "get",
        lambda *args, **kwargs: _response(
            "https://publisher.example/story", "<article><p>Too short.</p></article>"
        ),
    )
    browser_body = "The browser-rendered article contains the complete publisher story. " * 12
    monkeypatch.setattr(article_fetch, "_fetch_with_browser", lambda url: _browser_result(url, browser_body))

    result = article_fetch.fetch_article("https://publisher.example/story")

    assert result.success is True
    assert result.method == "playwright"
    assert result.final_url == "https://publisher.example/story"
    assert result.metadata["http_error"] == "article_body_not_found"


def test_fetch_article_does_not_browser_bypass_access_control(monkeypatch):
    blocked = "Access denied. Please subscribe to continue. " * 20
    monkeypatch.setattr(
        article_fetch.httpx,
        "get",
        lambda *args, **kwargs: _response(
            "https://publisher.example/story", f"<article><h1>Blocked</h1><p>{blocked}</p></article>"
        ),
    )

    def fail_if_called(_url):
        raise AssertionError("blocked publisher content must not trigger a browser bypass")

    monkeypatch.setattr(article_fetch, "_fetch_with_browser", fail_if_called)

    result = article_fetch.fetch_article("https://publisher.example/story")

    assert result.success is False
    assert result.error_code == "quality_blocked"
    assert result.content is None


def test_fetch_article_does_not_browser_bypass_http_denial(monkeypatch):
    request = httpx.Request("GET", "https://publisher.example/story")
    response = httpx.Response(403, request=request)
    monkeypatch.setattr(
        article_fetch.httpx,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            httpx.HTTPStatusError("forbidden", request=request, response=response)
        ),
    )
    monkeypatch.setattr(
        article_fetch,
        "_fetch_with_browser",
        lambda _url: (_ for _ in ()).throw(AssertionError("HTTP denial must not reach a browser")),
    )

    result = article_fetch.fetch_article("https://publisher.example/story")

    assert result.success is False
    assert result.error_code == "quality_blocked"
    assert result.method == "http"


def test_domain_policy_can_skip_http(monkeypatch):
    expected = _browser_result("https://news.google.com/story", "Rendered publisher body")
    monkeypatch.setattr(article_fetch.httpx, "get", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(article_fetch, "_fetch_with_browser", lambda _url: expected)

    assert article_fetch.fetch_article("https://news.google.com/story") is expected


def test_fetch_article_rejects_invalid_url_without_network(monkeypatch):
    monkeypatch.setattr(article_fetch.httpx, "get", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))

    result = article_fetch.fetch_article("ftp://publisher.example/story")

    assert result.success is False
    assert result.error_code == "invalid_url"
    assert result.final_url == "ftp://publisher.example/story"


def test_fetch_article_rejects_malformed_url_without_raising():
    result = article_fetch.fetch_article("http://[bad")

    assert result.success is False
    assert result.error_code == "invalid_url"


def test_http_5xx_remains_retryable_when_browser_has_no_content(monkeypatch):
    request = httpx.Request("GET", "https://publisher.example/story")
    response = httpx.Response(503, request=request)
    monkeypatch.setattr(
        article_fetch.httpx,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            httpx.HTTPStatusError("unavailable", request=request, response=response)
        ),
    )
    monkeypatch.setattr(
        article_fetch,
        "_fetch_with_browser",
        lambda url: ArticleFetchResult(
            url=url,
            final_url=url,
            title=None,
            content=None,
            method="playwright",
            success=False,
            quality=0,
            error="no content",
            error_code="article_body_not_found",
        ),
    )

    assert article_fetch.fetch_article("https://publisher.example/story").error_code == "http_503"


def test_fetch_article_text_keeps_legacy_text_contract(monkeypatch):
    expected = "article body"
    monkeypatch.setattr(
        article_fetch,
        "fetch_article",
        lambda url, timeout=10.0: ArticleFetchResult(
            url=url,
            final_url=url,
            title="Title",
            content=expected,
            method="cache",
            success=True,
            quality=1.0,
        ),
    )

    assert article_fetch.fetch_article_text("https://publisher.example/story") == expected
