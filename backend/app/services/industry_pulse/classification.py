"""Canonical base-industry and theme classification boundary.

Trusted/manual rows win over provider labels and optional Luna suggestions.
The latter are validated against the seeded IDs and are never allowed to
create taxonomy nodes or silently move a trusted primary industry.
"""

from __future__ import annotations

from typing import Any, Callable

from app.services.industry_pulse.definitions import (
    BASE_TAXONOMY_BY_ID,
    CLASSIFICATION_SEEDS,
    AI_TAXONOMY_BY_ID,
    THEME_INCLUSION_THRESHOLD,
    is_exposure_included,
)

_THEME_ALIASES = {
    "ai_cloud_hyperscaler": "ai.infrastructure.cloud.hyperscalers",
    "enterprise_ai": "ai.software_and_data.enterprise_ai",
    "ai_platform": "ai.software_and_data.ai_platforms",
    "ai_power_demand": "ai.power",
    "advanced_nuclear": "ai.power.power_generation.advanced_nuclear_smr",
    "nuclear_equipment": "ai.power.nuclear_fuel_cycle.nuclear_equipment",
}


def _valid_base(value: Any) -> str | None:
    value = str(value or "").strip()
    return value if value in BASE_TAXONOMY_BY_ID else None


def _valid_ai(value: Any) -> str | None:
    value = str(value or "").strip()
    return value if value in AI_TAXONOMY_BY_ID else None


def validate_classification(payload: dict[str, Any] | None, *, trusted: bool = False) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    primary = _valid_base(payload.get("primary_industry") or payload.get("primary_id"))
    secondary_raw = payload.get("secondary_industries") or payload.get("secondary") or ()
    secondary = tuple(dict.fromkeys(item for item in (_valid_base(value) for value in secondary_raw) if item and item != primary))
    themes_raw = payload.get("theme_exposures") or payload.get("themes") or {}
    themes: dict[str, float] = {}
    included_themes: dict[str, float] = {}
    unmapped_themes: dict[str, float] = {}
    if isinstance(themes_raw, dict):
        for key, value in themes_raw.items():
            node_id = _valid_ai(key) or _THEME_ALIASES.get(str(key).strip().casefold())
            try:
                weight = float(value)
            except (TypeError, ValueError):
                continue
            if node_id and 0 <= weight <= 1:
                themes[node_id] = weight
                if is_exposure_included(weight):
                    included_themes[node_id] = weight
            elif 0 <= weight <= 1:
                unmapped_themes[str(key)] = weight
    return {
        "status": "classified" if primary else "unclassified",
        "primary_industry": primary,
        "secondary_industries": secondary,
        "theme_exposures": themes,
        "included_theme_exposures": included_themes,
        "unmapped_theme_exposures": unmapped_themes,
        "source": "trusted" if trusted else str(payload.get("source") or "provider"),
        "confidence": max(0.0, min(1.0, float(payload.get("confidence", 1.0 if trusted and primary else .5) or 0))),
    }


def _provider_guess(profile: dict[str, Any] | None, company_profile: dict[str, Any] | None) -> dict[str, Any]:
    values = [str((profile or {}).get("official_industry") or ""), str((profile or {}).get("official_sector") or ""), str((company_profile or {}).get("industry") or ""), str((company_profile or {}).get("sector") or "")]
    lowered = " ".join(values).casefold()
    candidates = []
    for node_id, node in BASE_TAXONOMY_BY_ID.items():
        name = str(node.get("name", "")).casefold()
        if name and (name in lowered or lowered in name):
            candidates.append(node_id)
    candidates = [value for value in candidates if BASE_TAXONOMY_BY_ID[value].get("level") == 3]
    if len(candidates) == 1:
        return {"primary_industry": candidates[0], "source": "provider", "confidence": .55}
    if len(candidates) > 1:
        return {"source": "ambiguous", "candidate_ids": candidates}
    return {"source": "unclassified"}


def classify_security(
    ticker: str,
    *,
    manual: dict[str, Any] | None = None,
    profile: dict[str, Any] | None = None,
    company_profile: dict[str, Any] | None = None,
    luna_classifier: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    symbol = str(ticker or "").strip().upper()
    if manual:
        result = validate_classification(manual, trusted=True)
        if result["primary_industry"]:
            return {**result, "ticker": symbol, "trusted": True}
    seed = CLASSIFICATION_SEEDS.get(symbol)
    if seed:
        return {**validate_classification(seed, trusted=True), "ticker": symbol, "trusted": True}
    provider = _provider_guess(profile, company_profile)
    if provider.get("primary_industry"):
        return {**validate_classification(provider), "ticker": symbol, "trusted": False, "ambiguous": False}
    if luna_classifier is not None:
        try:
            suggestion = validate_classification(luna_classifier({"ticker": symbol, "profile": profile or {}, "company_profile": company_profile or {}}))
            if suggestion["primary_industry"]:
                return {**suggestion, "ticker": symbol, "trusted": False, "ambiguous": False, "source": "luna"}
        except Exception:
            pass
    return {"ticker": symbol, "status": "unclassified", "primary_industry": None, "secondary_industries": (), "theme_exposures": {}, "source": provider.get("source", "unclassified"), "trusted": False, "ambiguous": provider.get("source") == "ambiguous", "candidate_ids": provider.get("candidate_ids", ())}


def classify_ticker(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return classify_security(*args, **kwargs)


__all__ = ["classify_security", "classify_ticker", "validate_classification"]
