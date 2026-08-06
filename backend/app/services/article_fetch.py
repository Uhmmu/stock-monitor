import json
import logging
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # Unit-test and lightweight environments may omit Chromium.
    sync_playwright = None


logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_STRIP_TAGS = ("script", "style", "nav", "header", "footer", "aside", "form", "noscript", "iframe", "svg")
_MAX_CHARS = 12000  # 截断，避免超长正文吃 token
_MIN_ARTICLE_CHARS = 400
_BROWSER_TIMEOUT_MS = 25_000


@dataclass(frozen=True)
class ArticleFetchResult:
    text: str | None
    resolved_url: str
    error: str | None = None


def fetch_article_text(url: str, timeout: float = 10.0) -> str | None:
    """抓取新闻网页正文。

    先用 HTTP 抓取；遇到 Google News 中转页、JS 渲染页或普通提取失败时，
    再用 Chromium 访问并提取最终出版社页面。失败返回 None，调用方不应
    把供应商摘要冒充为原文。
    """
    return fetch_article(url, timeout=timeout).text


def fetch_article(url: str, timeout: float = 10.0) -> ArticleFetchResult:
    if not url:
        return ArticleFetchResult(None, url, "missing_url")
    if not _is_http_url(url):
        return ArticleFetchResult(None, url, "invalid_url")

    http_error = None
    try:
        resp = httpx.get(url, headers=_HEADERS, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "")
        if "html" in ctype.lower():
            text = _extract_main_text(resp.text)
            # Google News serves a large application shell at RSS article URLs.
            # It is not the publisher body even if generic extraction finds text.
            if text and urlsplit(str(resp.url)).hostname != "news.google.com":
                return ArticleFetchResult(text, str(resp.url))
        else:
            http_error = f"unsupported_content_type:{ctype[:80]}"
    except Exception as exc:
        http_error = f"{type(exc).__name__}:{exc}"[:300]

    browser_result = _fetch_with_browser(url)
    if browser_result.text:
        return browser_result
    error = browser_result.error or http_error or "article_body_not_found"
    logger.warning("Article body fetch failed host=%s reason=%s", urlsplit(url).hostname, error)
    return ArticleFetchResult(None, browser_result.resolved_url or url, error)


def _fetch_with_browser(url: str) -> ArticleFetchResult:
    if sync_playwright is None:
        return ArticleFetchResult(None, url, "browser_unavailable")
    browser = None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path="/usr/bin/chromium",
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = browser.new_context(
                user_agent=_HEADERS["User-Agent"],
                locale="en-US",
                ignore_https_errors=True,
            )
            page = context.new_page()
            response = page.goto(url, wait_until="domcontentloaded", timeout=_BROWSER_TIMEOUT_MS)
            # Google News resolves its RSS wrapper in client-side JavaScript.
            if urlsplit(url).hostname == "news.google.com":
                try:
                    page.wait_for_url(lambda value: urlsplit(value).hostname != "news.google.com", timeout=8_000)
                except Exception:
                    pass
            page.wait_for_timeout(1_500)
            resolved_url = page.url
            if not _is_http_url(resolved_url):
                return ArticleFetchResult(None, resolved_url, "invalid_browser_redirect")
            if response is not None and response.status >= 400:
                return ArticleFetchResult(None, resolved_url, f"browser_http_{response.status}")
            text = _extract_main_text(page.content())
            if text:
                return ArticleFetchResult(text, resolved_url)
            return ArticleFetchResult(None, resolved_url, "browser_article_body_not_found")
    except Exception as exc:
        return ArticleFetchResult(None, url, f"browser_{type(exc).__name__}:{exc}"[:300])
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass


def _is_http_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


def _extract_main_text(html: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    structured = _structured_article_body(soup)
    if structured:
        return structured[:_MAX_CHARS]
    for tag in soup(_STRIP_TAGS):
        tag.decompose()
    for tag in soup.select('[aria-label*="cookie" i], [class*="cookie" i], [class*="related" i], [class*="recommend" i], [class*="newsletter" i], [class*="social" i], [class*="advert" i]'):
        tag.decompose()

    # 不能盲信页面中的第一个 <article>：很多站点会先放一个推荐卡片。
    # 对所有语义容器取文本最充足的候选，再用全页段落作保底。
    selectors = (
        '[itemprop="articleBody"]', "article", "main", ".article-body", ".story-body",
        ".entry-content", '[class*="article-content"]', '[class*="story-content"]',
    )
    containers = []
    seen = set()
    for selector in selectors:
        for node in soup.select(selector):
            if id(node) not in seen:
                seen.add(id(node))
                containers.append(node)
    dense = _densest_container(soup)
    if dense is not None and id(dense) not in seen:
        containers.append(dense)
    containers.append(soup)

    candidates = [_container_text(container) for container in containers]
    text = max(candidates, key=len, default="").strip()
    if len(text) < _MIN_ARTICLE_CHARS:
        return None
    return text[:_MAX_CHARS]


def _container_text(container) -> str:
    paragraphs = [p.get_text(" ", strip=True) for p in container.find_all("p")]
    text = "\n\n".join(value for value in paragraphs if len(value) > 40)
    if not text:
        text = container.get_text(" ", strip=True)
    return text.strip()


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
