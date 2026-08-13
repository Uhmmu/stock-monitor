"""Small, canonical options universe.

The industry-pulse registry remains the source of truth for ETF symbols and
sector node IDs.  This module only selects the finite options subset and maps
watchlist metadata to the existing level-one taxonomy.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

from app.services.industry_pulse.definitions import BASE_SECTORS, ETF_REGISTRY

MARKET_ETFS: tuple[str, ...] = ("SPY", "QQQ", "IWM")
SECTOR_ETFS: tuple[str, ...] = (
    "XLK", "XLC", "XLY", "XLP", "XLV", "XLF", "XLI", "XLE", "XLB", "XLU", "XLRE",
)
SECONDARY_ETFS: tuple[str, ...] = (
    "SMH", "IGV", "XRT", "ITB", "XBI", "IHI", "KRE", "ITA", "IYT", "XOP", "XME", "URA", "ICLN",
)


def _registry_row(symbol: str) -> Mapping[str, Any]:
    row = ETF_REGISTRY.get(symbol)
    if not row:
        raise ValueError(f"options ETF is missing from canonical ETF_REGISTRY: {symbol}")
    return row


def _primary_sector(symbol: str) -> dict[str, Any] | None:
    row = _registry_row(symbol)
    mappings = [item for item in row.get("mappings", ()) if item.get("enabled", True)]
    mapping = next((item for item in mappings if item.get("role") == "primary"), None)
    # Secondary proxies often intentionally have no primary mapping.  Their
    # first canonical base mapping still identifies the parent level-one
    # sector, without inventing a competing taxonomy.
    if mapping is None:
        mapping = next((item for item in mappings if str(item.get("node_id", "")).startswith("base.")), None)
    if mapping is None:
        return None
    node_id = str(mapping.get("node_id", ""))
    sector_id = ".".join(node_id.split(".")[:2]) if node_id.startswith("base.") else None
    sector = next((item for item in BASE_SECTORS if item["id"] == sector_id), None)
    return {
        "sector_id": sector_id,
        "sector_name": sector.get("name") if sector else None,
        "sector_name_zh": sector.get("name_zh") if sector else None,
    }


@dataclass(frozen=True)
class OptionsUnderlying:
    symbol: str
    asset_type: str
    role: str
    sector_id: str | None = None
    sector_name: str | None = None
    sector_name_zh: str | None = None
    company_name: str | None = None
    source: str = "canonical_etf_registry"
    primary_etf: str | None = None
    secondary_etfs: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def sector_etf_mapping() -> dict[str, dict[str, Any]]:
    """Return primary/secondary proxies keyed by canonical sector ID."""
    result = {
        sector["id"]: {
            "sector_id": sector["id"],
            "sector_name": sector["name"],
            "sector_name_zh": sector.get("name_zh"),
            "primary_etf": None,
            "secondary_etfs": [],
        }
        for sector in BASE_SECTORS
    }
    for symbol in (*SECTOR_ETFS, *SECONDARY_ETFS):
        row = _registry_row(symbol)
        for mapping in row.get("mappings", ()):
            node_id = str(mapping.get("node_id", ""))
            if not node_id.startswith("base."):
                continue
            sector_id = ".".join(node_id.split(".")[:2])
            if sector_id not in result:
                continue
            if symbol in SECTOR_ETFS and mapping.get("role") == "primary" and result[sector_id]["primary_etf"] is None:
                result[sector_id]["primary_etf"] = symbol
            elif symbol in SECONDARY_ETFS and symbol not in result[sector_id]["secondary_etfs"]:
                result[sector_id]["secondary_etfs"].append(symbol)
    return result


def _sector_id_from_value(value: Any) -> str | None:
    if isinstance(value, Mapping):
        value = value.get("id") or value.get("node_id") or value.get("sector_id") or value.get("name")
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text in {item["id"] for item in BASE_SECTORS}:
        return text
    folded = text.casefold().replace("&", "and").replace("_", " ").replace("-", " ")
    provider_aliases = {
        "information technology": "base.technology",
        "technology": "base.technology",
        "consumer cyclical": "base.consumer_discretionary",
        "consumer defensive": "base.consumer_staples",
        "health care": "base.healthcare",
        "healthcare": "base.healthcare",
        "utilities": "base.utilities_and_power",
        "utilities and power": "base.utilities_and_power",
    }
    if folded in provider_aliases:
        return provider_aliases[folded]
    for item in BASE_SECTORS:
        if folded in {item["name"].casefold(), item.get("name_zh", "").casefold()}:
            return item["id"]
    return None


def map_ticker_to_sector(
    ticker: str,
    metadata: Mapping[str, Any] | None = None,
    *,
    classifications: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Map one watchlist row to the existing first-level sector.

    ``metadata`` may be a watchlist row or provider/profile payload.  No symbol
    guessing is performed: a missing/unknown classification stays unclassified.
    """
    symbol = str(ticker).strip().upper()
    if not symbol or any(char.isspace() for char in symbol):
        raise ValueError("ticker must be a non-empty symbol")
    metadata = metadata or {}
    source = classifications or {}
    values = (
        metadata.get("sector_id"), metadata.get("sector_node_id"), metadata.get("sector"),
        metadata.get("official_sector"), metadata.get("classification", {}).get("sector")
        if isinstance(metadata.get("classification"), Mapping) else None,
        source.get(symbol) if isinstance(source, Mapping) else None,
    )
    sector_id = next((candidate for value in values if (candidate := _sector_id_from_value(value))), None)
    mapping = sector_etf_mapping().get(sector_id) if sector_id else None
    return {
        "ticker": symbol,
        "company_name": metadata.get("company_name") or metadata.get("name") or metadata.get("display_name"),
        "sector_id": sector_id,
        "sector_name": mapping.get("sector_name") if mapping else None,
        "sector_name_zh": mapping.get("sector_name_zh") if mapping else None,
        "primary_etf": mapping.get("primary_etf") if mapping else None,
        "secondary_etfs": list(mapping.get("secondary_etfs", ())) if mapping else [],
        "watchlist_category": metadata.get("category") or metadata.get("group") or metadata.get("watchlist_category"),
        "mapping_status": "mapped" if mapping else "unclassified",
    }


def build_options_universe(
    watchlist: Iterable[str | Mapping[str, Any]] = (),
    *,
    classifications: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build market + sector ETF rows and only the supplied watchlist rows."""
    rows: list[OptionsUnderlying] = []
    mappings = sector_etf_mapping()
    for symbol in MARKET_ETFS:
        rows.append(OptionsUnderlying(symbol=symbol, asset_type="market_etf", role="market"))
    for symbol in SECTOR_ETFS:
        sector = _primary_sector(symbol) or {}
        mapping = mappings.get(sector.get("sector_id"), {})
        rows.append(OptionsUnderlying(
            symbol=symbol,
            asset_type="sector_etf",
            role="primary",
            sector_id=sector.get("sector_id"),
            sector_name=sector.get("sector_name"),
            sector_name_zh=sector.get("sector_name_zh"),
            primary_etf=symbol,
            secondary_etfs=tuple(mapping.get("secondary_etfs", ())),
        ))
    for symbol in SECONDARY_ETFS:
        sector = _primary_sector(symbol) or {}
        rows.append(OptionsUnderlying(
            symbol=symbol,
            asset_type="secondary_etf",
            role="secondary",
            sector_id=sector.get("sector_id"),
            sector_name=sector.get("sector_name"),
            sector_name_zh=sector.get("sector_name_zh"),
            primary_etf=mappings.get(sector.get("sector_id"), {}).get("primary_etf"),
        ))
    known = {row.symbol for row in rows}
    for item in watchlist:
        metadata = item if isinstance(item, Mapping) else {"ticker": item}
        symbol = str(metadata.get("ticker") or metadata.get("symbol") or "").strip().upper()
        if not symbol or symbol in known:
            continue
        mapped = map_ticker_to_sector(symbol, metadata, classifications=classifications)
        rows.append(OptionsUnderlying(
            symbol=symbol,
            asset_type="watchlist_stock",
            role="watchlist",
            sector_id=mapped["sector_id"],
            sector_name=mapped["sector_name"],
            sector_name_zh=mapped["sector_name_zh"],
            company_name=mapped["company_name"],
            source="watchlist",
            primary_etf=mapped["primary_etf"],
            secondary_etfs=tuple(mapped["secondary_etfs"]),
        ))
        known.add(symbol)
    return [row.as_dict() for row in rows]


options_universe = build_options_universe
get_options_universe = build_options_universe
build_watchlist_universe = build_options_universe
get_sector_etf_mapping = sector_etf_mapping
map_watchlist_ticker = map_ticker_to_sector

ETF_OPTIONS_UNIVERSE = build_options_universe()
OPTIONS_MARKET_ETFS = MARKET_ETFS
OPTIONS_SECTOR_ETFS = SECTOR_ETFS
OPTIONS_SECONDARY_ETFS = SECONDARY_ETFS

__all__ = [
    "ETF_OPTIONS_UNIVERSE", "MARKET_ETFS", "SECONDARY_ETFS", "SECTOR_ETFS", "OptionsUnderlying",
    "OPTIONS_MARKET_ETFS", "OPTIONS_SECONDARY_ETFS", "OPTIONS_SECTOR_ETFS",
    "build_options_universe", "build_watchlist_universe", "get_options_universe", "get_sector_etf_mapping",
    "map_ticker_to_sector", "map_watchlist_ticker", "options_universe", "sector_etf_mapping",
]
