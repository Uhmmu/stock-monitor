import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
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
_BROWSER_WAIT_SECONDS = 2.0
DOMAIN_POLICY = {"news.google.com": "playwright"}
DEFAULT_DOMAIN_POLICY = "http_then_playwright"
# Publishers whose pages reliably defeat both HTTP and browser extraction
# (hard bot walls, no JSON-LD). Retrying every article costs a 25s browser
# timeout per row; the provider summary is the ceiling, so fail fast instead.
UNFETCHABLE_NEWS_DOMAINS = ("reuters.com",)
_BLOCKER_PATTERNS = (
    r"\baccess denied\b",
    r"\bchecking your browser before accessing\b",
    r"\bcloudflare\s+(?:ray id|security check|challenge|verification)\b",
    r"\bcaptcha\b",
    r"\bunusual traffic\b",
    r"\bverify (?:you are|that you(?:'re| are)) human\b",
    r"\blog in to (?:read|continue)\b",
    r"\bsign in to (?:read|continue)\b",
    r"\bsubscribe to (?:read|continue)\b",
    r"\bsubscription required\b",
    r"\b(?:enable|please enable) javascript\b",
    r"\bjavascript (?:is )?required\b",
    r"\baccept (?:all )?cookies to continue\b",
)

# ponytail: one browser at a time per process; use a dedicated browser pool
# only if measured article throughput makes this ceiling material.
_BROWSER_SEMAPHORE = threading.BoundedSemaphore(1)


@dataclass(frozen=True)
class ArticleFetchResult:
    url: str
    final_url: str
    title: str | None
    content: str | None
    method: str
    success: bool
    quality: float
    error: str | None = None
    error_code: str | None = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    latency: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str | None:
        """Compatibility alias for the previous result shape."""
        return self.content

    @property
    def resolved_url(self) -> str:
        """Compatibility alias for the previous result shape."""
        return self.final_url

    @property
    def quality_score(self) -> float:
        """Compatibility alias for persistence/task callers using score naming."""
        return self.quality

    @property
    def latency_ms(self) -> float:
        """Compatibility alias for telemetry callers using millisecond naming."""
        return self.latency * 1000


def fetch_article_text(url: str, timeout: float = 10.0) -> str | None:
    """抓取新闻网页正文。

    先用 HTTP 抓取；遇到 Google News 中转页、JS 渲染页或普通提取失败时，
    再用 Chromium 访问并提取最终出版社页面。失败返回 None，调用方不应
    把供应商摘要冒充为原文。
    """
    return fetch_article(url, timeout=timeout).text


def fetch_article(url: str, timeout: float = 10.0) -> ArticleFetchResult:
    started = time.perf_counter()
    fetched_at = datetime.now(UTC)
    if not url:
        return _result(
            url="",
            final_url="",
            fetched_at=fetched_at,
            started=started,
            error="missing_url",
            error_code="missing_url",
        )
    if not _is_http_url(url):
        return _result(
            url=url,
            final_url=url,
            fetched_at=fetched_at,
            started=started,
            error="invalid_url",
            error_code="invalid_url",
        )
    if _is_unfetchable_news_domain(url):
        return _result(
            url=url,
            final_url=url,
            fetched_at=fetched_at,
            started=started,
            error="publisher bot wall blocks article extraction",
            error_code="quality_blocked",
            metadata={"domain_policy": "unfetchable"},
        )

    http_error = None
    http_error_code = None
    domain_policy = _domain_policy(url)
    http_metadata: dict[str, Any] = {"domain_policy": domain_policy}
    if domain_policy == "playwright":
        return _fetch_with_browser(url)
    try:
        resp = httpx.get(url, headers=_HEADERS, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        ctype = str(resp.headers.get("content-type", "") or "")
        final_url = str(getattr(resp, "url", None) or url)
        http_metadata = {
            "http_status": getattr(resp, "status_code", None),
            "content_type": ctype[:120],
            "domain_policy": domain_policy,
        }
        if "html" in ctype.lower():
            title, text = _extract_document(resp.text)
            quality, quality_error = _content_quality(title, text)
            extraction_method = "http" if _has_structured_article_body(resp.text) else "reader"
            # Google News serves a large application shell at RSS article URLs.
            # It is not the publisher body even if generic extraction finds text.
            if urlsplit(final_url).hostname != "news.google.com" and quality_error is None:
                return _result(
                    url=url,
                    final_url=final_url,
                    title=title,
                    content=text,
                    method=extraction_method,
                    success=True,
                    quality=quality,
                    fetched_at=fetched_at,
                    started=started,
                    metadata=http_metadata,
                )
            if quality_error == "quality_blocked":
                return _result(
                    url=url,
                    final_url=final_url,
                    title=title,
                    content=None,
                    method="http",
                    quality=quality,
                    fetched_at=fetched_at,
                    started=started,
                    error="publisher access control blocked article extraction",
                    error_code=quality_error,
                    metadata=http_metadata,
                )
            http_error = quality_error or "article_body_not_found"
            http_error_code = quality_error or "article_body_not_found"
        else:
            http_error = f"unsupported_content_type:{ctype[:80]}"
            http_error_code = "unsupported_content_type"
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        http_error = f"http_{status}"
        http_error_code = http_error
        http_metadata = {"http_status": status, "domain_policy": domain_policy}
        # Public rendering is a fallback for incomplete pages, not a way around
        # authentication, paywalls, rate limits, or other explicit HTTP denials.
        if status < 500:
            return _result(
                url=url,
                final_url=str(exc.response.url or url),
                method="http",
                fetched_at=fetched_at,
                started=started,
                error=http_error,
                error_code="quality_blocked" if status in {401, 402, 403, 407, 451} else http_error_code,
                metadata=http_metadata,
            )
    except httpx.TimeoutException as exc:
        http_error = f"{type(exc).__name__}:{exc}"[:300]
        http_error_code = "network_timeout"
    except httpx.RequestError as exc:
        http_error = f"{type(exc).__name__}:{exc}"[:300]
        http_error_code = "network_error"
    except Exception as exc:
        http_error = f"{type(exc).__name__}:{exc}"[:300]
        http_error_code = "http_error"

    browser_result = _fetch_with_browser(url)
    if browser_result.success and browser_result.content:
        metadata = {**http_metadata, **browser_result.metadata, "http_error": http_error}
        return ArticleFetchResult(
            url=url,
            final_url=browser_result.final_url or url,
            title=browser_result.title,
            content=browser_result.content,
            method=browser_result.method,
            success=True,
            quality=browser_result.quality,
            fetched_at=fetched_at,
            latency=time.perf_counter() - started,
            metadata=metadata,
        )
    error = browser_result.error or http_error or "article_body_not_found"
    error_code = (
        http_error_code
        if _is_retryable_error_code(http_error_code)
        else browser_result.error_code or http_error_code or "article_body_not_found"
    )
    logger.warning("Article body fetch failed host=%s reason=%s", urlsplit(url).hostname, error)
    return ArticleFetchResult(
        url=url,
        final_url=browser_result.final_url or url,
        title=browser_result.title,
        content=None,
        method=browser_result.method,
        success=False,
        quality=browser_result.quality,
        error=error,
        error_code=error_code,
        fetched_at=fetched_at,
        latency=time.perf_counter() - started,
        metadata={**http_metadata, **browser_result.metadata, "http_error": http_error},
    )


def _fetch_with_browser(url: str) -> ArticleFetchResult:
    started = time.perf_counter()
    fetched_at = datetime.now(UTC)
    if not _BROWSER_SEMAPHORE.acquire(timeout=_BROWSER_WAIT_SECONDS):
        return _result(
            url=url,
            final_url=url,
            method="playwright",
            fetched_at=fetched_at,
            started=started,
            error="browser concurrency limit reached",
            error_code="browser_busy",
        )
    if sync_playwright is None:
        _BROWSER_SEMAPHORE.release()
        return _result(
            url=url,
            final_url=url,
            method="playwright",
            fetched_at=fetched_at,
            started=started,
            error="browser_unavailable",
            error_code="browser_unavailable",
        )
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
                return _result(
                    url=url,
                    final_url=resolved_url,
                    method="playwright",
                    fetched_at=fetched_at,
                    started=started,
                    error="invalid_browser_redirect",
                    error_code="invalid_browser_redirect",
                )
            if response is not None and response.status >= 400:
                return _result(
                    url=url,
                    final_url=resolved_url,
                    method="playwright",
                    fetched_at=fetched_at,
                    started=started,
                    error=f"browser_http_{response.status}",
                    error_code=f"browser_http_{response.status}",
                    metadata={"http_status": response.status},
                )
            title, text = _extract_document(page.content())
            quality, quality_error = _content_quality(title, text)
            if quality_error == "quality_blocked":
                return _result(
                    url=url,
                    final_url=resolved_url,
                    title=title,
                    method="playwright",
                    quality=quality,
                    fetched_at=fetched_at,
                    started=started,
                    error="publisher access control blocked article extraction",
                    error_code=quality_error,
                )
            if quality_error:
                return _result(
                    url=url,
                    final_url=resolved_url,
                    title=title,
                    method="playwright",
                    quality=quality,
                    fetched_at=fetched_at,
                    started=started,
                    error="browser_article_body_not_found",
                    error_code=quality_error,
                )
            return _result(
                url=url,
                final_url=resolved_url,
                title=title,
                content=text,
                method="playwright",
                success=True,
                quality=quality,
                fetched_at=fetched_at,
                started=started,
            )
    except Exception as exc:
        return _result(
            url=url,
            final_url=url,
            method="playwright",
            fetched_at=fetched_at,
            started=started,
            error=f"browser_{type(exc).__name__}:{exc}"[:300],
            error_code="browser_error",
        )
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        _BROWSER_SEMAPHORE.release()


def _result(
    *,
    url: str,
    final_url: str,
    fetched_at: datetime,
    started: float,
    title: str | None = None,
    content: str | None = None,
    method: str = "none",
    success: bool = False,
    quality: float = 0.0,
    error: str | None = None,
    error_code: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ArticleFetchResult:
    return ArticleFetchResult(
        url=url,
        final_url=final_url,
        title=title,
        content=content,
        method=method,
        success=success,
        quality=max(0.0, min(1.0, float(quality))),
        error=error,
        error_code=error_code,
        fetched_at=fetched_at,
        latency=max(0.0, time.perf_counter() - started),
        metadata=metadata or {},
    )


def _is_http_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


def _domain_policy(value: str) -> str:
    hostname = (urlsplit(value).hostname or "").casefold()
    return DOMAIN_POLICY.get(hostname, DEFAULT_DOMAIN_POLICY)


def _is_unfetchable_news_domain(value: str) -> bool:
    hostname = (urlsplit(value).hostname or "").casefold().removeprefix("www.")
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in UNFETCHABLE_NEWS_DOMAINS)


def _is_retryable_error_code(code: str | None) -> bool:
    if code in {"network_error", "network_timeout", "http_error"}:
        return True
    if not code:
        return False
    try:
        status = int(code.rsplit("_", 1)[-1])
    except ValueError:
        return False
    return status in {408, 429} or status >= 500


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


def _extract_document(html: str) -> tuple[str | None, str | None]:
    soup = BeautifulSoup(html, "lxml")
    title = _extract_title(soup)
    return title, _extract_main_text(html)


def _has_structured_article_body(html: str) -> bool:
    return _structured_article_body(BeautifulSoup(html, "lxml")) is not None


def _extract_title(soup: BeautifulSoup) -> str | None:
    for node in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = node.string or node.get_text(" ", strip=True)
        try:
            payload = json.loads(raw) if raw else None
        except (TypeError, ValueError):
            payload = None
        queue = payload if isinstance(payload, list) else [payload]
        while queue:
            item = queue.pop(0)
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            if isinstance(graph, list):
                queue.extend(graph)
            headline = item.get("headline")
            if isinstance(headline, str) and headline.strip():
                return headline.strip()[:512]
    for selector in ("h1", "title"):
        node = soup.select_one(selector)
        value = node.get_text(" ", strip=True) if node else ""
        if value:
            return value[:512]
    return None


def _content_quality(title: str | None, content: str | None) -> tuple[float, str | None]:
    value = (content or "").strip()
    if not value:
        return 0.0, "article_body_not_found"
    folded = re.sub(r"\s+", " ", f"{title or ''} {value}").casefold()
    if any(re.search(pattern, folded) for pattern in _BLOCKER_PATTERNS):
        return 0.05, "quality_blocked"
    if len(value) < _MIN_ARTICLE_CHARS:
        return min(len(value) / _MIN_ARTICLE_CHARS * 0.5, 0.5), "content_too_short"
    paragraphs = [part for part in re.split(r"\n\s*\n", value) if part.strip()]
    quality = 0.55 + min(len(value), 6000) / 12000
    if title:
        quality += 0.1
    if len(paragraphs) >= 2:
        quality += 0.1
    return min(1.0, quality), None


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
