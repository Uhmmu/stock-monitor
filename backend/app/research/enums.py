from enum import StrEnum


class SourceAuthority(StrEnum):
    official = "official"
    primary = "primary"
    secondary = "secondary"
    user = "user"
    derived = "derived"
    unknown = "unknown"


class FreshnessStatus(StrEnum):
    live = "live"
    fresh = "fresh"
    stale = "stale"
    expired = "expired"
    unknown = "unknown"


class WarningSeverity(StrEnum):
    info = "info"
    warning = "warning"
    error = "error"


class ResearchErrorCode(StrEnum):
    not_found = "RESEARCH_NOT_FOUND"
    invalid_symbol = "INVALID_SYMBOL"
    invalid_date_range = "INVALID_DATE_RANGE"
    invalid_parameter = "INVALID_PARAMETER"
    forbidden_resource = "FORBIDDEN_RESOURCE"
    source_unavailable = "SOURCE_UNAVAILABLE"
    source_stale = "SOURCE_STALE"
    file_not_found = "FILE_NOT_FOUND"
    file_access_denied = "FILE_ACCESS_DENIED"
    data_incomplete = "DATA_INCOMPLETE"
    internal = "INTERNAL_RESEARCH_ERROR"


class SourceType(StrEnum):
    capability_registry = "capability_registry"
    portfolio = "portfolio"
    portfolio_position = "portfolio_position"
    trade_transaction = "trade_transaction"
    news = "news"
    news_archive = "news_archive"
    sec_filing = "sec_filing"
    sec_event = "sec_event"
    sec_financial_period = "sec_financial_period"
    sec_insider_trade = "sec_insider_trade"
    sec_13f_holding = "sec_13f_holding"
    company_profile = "company_profile"
    financial_statement = "financial_statement"
    valuation_snapshot = "valuation_snapshot"
    market_quote = "market_quote"
    price_snapshot = "price_snapshot"
    historical_price = "historical_price"
    technical_analysis = "technical_analysis"
    calendar_event = "calendar_event"
    discovery_run = "discovery_run"
    discovery_candidate = "discovery_candidate"
    peer_relation = "peer_relation"
    portfolio_analysis = "portfolio_analysis"
    market_context = "market_context"
    congress_trade = "congress_trade"
    tracked_figure = "tracked_figure"
    figure_position = "figure_position"
