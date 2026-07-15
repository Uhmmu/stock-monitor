import httpx
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_STRIP_TAGS = ("script", "style", "nav", "header", "footer", "aside", "form", "noscript", "iframe")
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
    for tag in soup(_STRIP_TAGS):
        tag.decompose()

    # 优先 <article>；否则取 <p> 最密集的容器；再退化为全体 <p>
    article = soup.find("article")
    container = article or _densest_container(soup) or soup
    paragraphs = [p.get_text(" ", strip=True) for p in container.find_all("p")]
    text = "\n\n".join(p for p in paragraphs if len(p) > 40)
    if not text:
        text = container.get_text(" ", strip=True)
    text = text.strip()
    if len(text) < 200:  # 正文太短判为抽取失败
        return None
    return text[:_MAX_CHARS]


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
