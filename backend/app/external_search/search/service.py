from __future__ import annotations

import json
from hashlib import sha256

from app.config import get_settings

from ..audit import audit_external_search
from ..budgets import enforce_search_budget, record_search_cost
from ..cache import external_search_cache
from ..domains import blocked_domains
from ..enums import SearchFreshness
from ..exceptions import ExternalSearchError
from ..metrics import external_search_metrics
from ..privacy import ExternalQueryPrivacyFilter
from ..registry import get_external_search_registry
from ..schemas import SearchProviderRequest, SearchProviderResponse
from ..security import normalize_domain_filter

FRESHNESS_TTL = {
    SearchFreshness.live: 30,
    SearchFreshness.fresh: 180,
    SearchFreshness.balanced: 900,
    SearchFreshness.cached: 3600,
}


class ExternalSearchService:
    def __init__(self, provider=None):
        self.provider = provider or get_external_search_registry().get("exa")
        self.privacy = ExternalQueryPrivacyFilter()

    async def search(self, request: SearchProviderRequest, *, context=None) -> SearchProviderResponse:
        settings = get_settings()
        if not settings.exa_enabled or not settings.exa_search_enabled:
            raise ExternalSearchError("WEB_SEARCH_DISABLED", "External web search is disabled.", status_code=503)
        if not settings.exa_api_key and self.provider.provider_name == "exa":
            raise ExternalSearchError("WEB_SEARCH_PROVIDER_NOT_CONFIGURED", "External web search is not configured.", status_code=503)
        sanitized = self.privacy.sanitize(request.query, context)
        if not sanitized.query:
            raise ExternalSearchError("WEB_SEARCH_INVALID_REQUEST", "External search query is empty after privacy filtering.", status_code=422)
        hard_max = min(max(settings.exa_search_hard_max_results, 1), 10)
        include = [normalize_domain_filter(value) for value in request.include_domains]
        excludes = [normalize_domain_filter(value) for value in request.exclude_domains]
        excludes = list(dict.fromkeys(excludes + [normalize_domain_filter(value) for value in blocked_domains()]))
        max_age = request.max_age_hours
        limit = min(request.num_results, hard_max)
        if request.content_mode == "text":
            limit = min(limit, 5)
        if request.freshness == SearchFreshness.fresh:
            max_age = 1
        elif request.freshness == SearchFreshness.live:
            max_age, limit = 0, min(limit, 5)
        elif request.freshness == SearchFreshness.cached:
            max_age = -1
        category = request.category
        if category in {"company", "people"} and (
            excludes or request.start_published_date or request.end_published_date
        ):
            # Exa documents these filters as unsupported for entity categories.
            # Dropping the category preserves forced block/date policy.
            category = None
        prepared = request.model_copy(update={
            "query": sanitized.query,
            "num_results": limit,
            "category": category,
            "include_domains": include,
            "exclude_domains": excludes,
            "max_age_hours": max_age,
        })
        cache_payload = prepared.model_dump(mode="json", exclude_none=True)
        key = "external-search:v1:" + sha256(json.dumps(cache_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if settings.exa_cache_enabled and request.freshness != SearchFreshness.live:
            cached = external_search_cache.get(key)
            if cached is not None:
                external_search_metrics.record("search", "success", cache_hit=True)
                return cached
        user_id = int(getattr(context, "user_id", 0) or 0)
        if user_id:
            enforce_search_budget(user_id=user_id)
        try:
            response = await self.provider.search(prepared)
        except ExternalSearchError as exc:
            external_search_metrics.record("search", exc.code)
            audit_external_search("search", user_id=getattr(context, "user_id", None), query_hash=sanitized.query_hash, query_length=sanitized.query_length, status="error", error_code=exc.code)
            raise
        if user_id:
            record_search_cost(user_id=user_id, cost_usd=response.cost_usd)
        if settings.exa_cache_enabled and response.results:
            external_search_cache.set(key, response, FRESHNESS_TTL[request.freshness])
        external_search_metrics.record("search", "success")
        audit_external_search(
            "search", user_id=getattr(context, "user_id", None), conversation_id=getattr(context, "conversation_id", None),
            request_id=getattr(context, "request_id", None), query_hash=sanitized.query_hash,
            query_length=sanitized.query_length, result_count=len(response.results),
            provider_request_id=response.request_id, cost_usd=str(response.cost_usd) if response.cost_usd is not None else None,
            status="success",
        )
        return response
