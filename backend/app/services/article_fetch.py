import json

import httpx
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_STRIP_TAGS = ("script", "style", "nav", "header", "footer", "aside", "form", "noscript", "iframe", "svg")
_MAX_CHARS = 8000  # 截断，避免超长正文吃 token


def fetch_article_text(url: str, timeout: float = 10.0) -> str | None:
    """抓取新闻网页正文。失败返回 None（调用方降级用摘要）。"""
    if not url:
        return None
    try:
        resp = httpx.get(url, headers=_HEADERS, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
    except Exception:
        return None
    ctype = resp.headers.get("content-type", "")
    if "html" not in ctype.lower():
        return None
    return _extract_main_text(resp.text)


def _extract_main_text(html: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    structured = _structured_article_body(soup)
    if structured:
        return structured[:_MAX_CHARS]
    for tag in soup(_STRIP_TAGS):
        tag.decompose()
    for tag in soup.select('[aria-label*="cookie" i], [class*="cookie" i], [class*="related" i], [class*="recommend" i], [class*="newsletter" i], [class*="social" i], [class*="advert" i]'):
        tag.decompose()

    # 优先 <article>；否则取 <p> 最密集的容器；再退化为全体 <p>
    article = soup.find("article") or soup.find("main") or soup.select_one('[itemprop="articleBody"]')
    container = article or _densest_container(soup) or soup
    paragraphs = [p.get_text(" ", strip=True) for p in container.find_all("p")]
    text = "\n\n".join(p for p in paragraphs if len(p) > 40)
    if not text:
        text = container.get_text(" ", strip=True)
    text = text.strip()
    if len(text) < 200:  # 正文太短判为抽取失败
        return None
    return text[:_MAX_CHARS]


def _structured_article_body(soup: BeautifulSoup) -> str | None:
    """Prefer publisher-provided NewsArticle JSON-LD over navigation-heavy HTML."""
    for node in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = node.string or node.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue
        queue = payload if isinstance(payload, list) else [payload]
        while queue:
            item = queue.pop(0)
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            if isinstance(graph, list):
                queue.extend(graph)
            body = item.get("articleBody")
            kind = item.get("@type")
            kinds = kind if isinstance(kind, list) else [kind]
            if isinstance(body, str) and any(value in {"Article", "NewsArticle", "ReportageNewsArticle"} for value in kinds):
                cleaned = "\n\n".join(part.strip() for part in body.splitlines() if part.strip())
                if len(cleaned) >= 200:
                    return cleaned
    return None


def _densest_container(soup):
    """找 <p> 文本总量最大的直接父容器，规避侧边栏/推荐位的碎片文本。"""
    best = None
    best_len = 0
    seen = set()
    for p in soup.find_all("p"):
        parent = p.parent
        if parent is None or id(parent) in seen:
            continue
        seen.add(id(parent))
        total = sum(len(sib.get_text(" ", strip=True)) for sib in parent.find_all("p", recursive=False))
        if total > best_len:
            best_len = total
            best = parent
    return best
