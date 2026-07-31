import pytest
from app.ai.citations import CitationBuilder
from app.ai.providers.schemas import ProviderToolCall
from app.ai.tool_loop import persistence_arguments
from app.ai_tools.adapters.external_search import WebSearchArguments
from app.ai_tools.audit import argument_summary
from app.external_search.exceptions import ExternalSearchError
from app.external_search.privacy import ExternalQueryPrivacyFilter
from app.external_search.security import normalize_domain_filter, normalize_public_url


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://example.com/a", "javascript:alert(1)", "data:text/plain,x",
    "http://localhost/a", "http://127.0.0.1/a", "http://10.0.0.1/a",
    "http://172.16.1.1/a", "http://192.168.1.1/a", "http://169.254.169.254/latest/meta-data",
    "http://[::1]/a", "http://[fc00::1]/a", "http://metadata.google.internal/a",
    "https://example.com:bad/a",
])
def test_unsafe_urls_are_rejected(url):
    with pytest.raises(ExternalSearchError) as raised:
        normalize_public_url(url)
    assert raised.value.code == "WEB_SEARCH_UNSAFE_URL"


def test_public_url_normalizes_idna_tracking_fragment_and_credentials():
    assert normalize_public_url("https://例子.测试/path?q=1&utm_source=x#frag") == "https://xn--fsqu00a.xn--0zwm56d/path?q=1"
    assert normalize_domain_filter("*.例子.测试/docs") == "*.xn--fsqu00a.xn--0zwm56d/docs"
    with pytest.raises(ExternalSearchError):
        normalize_public_url("https://user:password@example.com/a")
    with pytest.raises(ExternalSearchError):
        normalize_public_url("https://example.com/" + "x" * 2100)


def test_privacy_filter_removes_private_context_without_destroying_public_dates():
    raw = (
        "Research MSFT in 2026. user_id=42 conversation id: 99, me@example.com, "
        "API-key_abcdefghijklmnopqrstuvwxyz, 持仓数量 123, 成本价: $321.50, "
        "账户余额 9999, http://10.0.0.8/admin and /opt/stock-monitor/private/file."
    )
    sanitized = ExternalQueryPrivacyFilter().sanitize(raw)
    lower = sanitized.query.lower()
    assert "msft" in lower and "2026" in lower
    for secret in ("42", "me@example.com", "abcdefghijklmnopqrstuvwxyz", "123", "321.50", "9999", "10.0.0.8", "/opt/stock-monitor"):
        assert secret.lower() not in lower
    assert sanitized.query_hash and sanitized.query_length == len(sanitized.query)


def test_external_tool_audit_and_persistence_never_store_query_text():
    query = "latest private-sensitive research topic"
    summary = argument_summary({"query": query, "limit": 8}, tool_name="search_web")
    assert query not in summary and "query_hash" in summary and "query_length" in summary

    class Registry:
        def get(self, name):
            return type("Adapter", (), {"arguments_model": WebSearchArguments})()

    class Executor:
        registry = Registry()

    normalized, digest = persistence_arguments(Executor(), ProviderToolCall(id="c1", name="search_web", arguments={"query": query}))
    assert normalized["query"] == "[redacted external query]"
    assert normalized["query_length"] == len(query)
    assert query not in str(normalized) and digest


def test_citation_builder_rejects_non_public_urls_and_deduplicates_source_ids():
    citations = CitationBuilder().assign_keys([
        {"source_id": "web:1", "source_type": "web_search", "title": "Safe", "url": "https://sec.gov/a"},
        {"source_id": "web:1", "source_type": "web_search", "title": "Duplicate", "url": "https://example.com/b"},
        {"source_id": "web:2", "source_type": "web_search", "title": "Unsafe", "url": "http://127.0.0.1/a"},
    ])
    assert len(citations) == 2
    assert citations[0].key == "S1" and citations[0].url == "https://sec.gov/a"
    assert citations[1].key == "S2" and citations[1].url is None
