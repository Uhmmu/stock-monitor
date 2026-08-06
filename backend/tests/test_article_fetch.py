from app.services.article_fetch import _extract_main_text


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
