from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.ai_tools.catalog import dispatch
from app.ai_tools.catalog import CompanySnapshotArguments
from app.ai_tools.schemas import SymbolArguments
from app.research.enums import FreshnessStatus
from app.research.schemas import ResearchFreshness, ResearchMeta, ResearchResponse


def _response(data, *, status=FreshnessStatus.live):
    now = datetime.now(UTC)
    return ResearchResponse(
        data=data,
        freshness=ResearchFreshness(
            as_of=now,
            status=status,
            age_seconds=0,
            ttl_seconds=300,
            reason="test",
        ),
        meta=ResearchMeta(request_id="test", generated_at=now, symbol="MSFT"),
    )


def test_latest_price_tool_uses_persisted_gateway_method():
    current = _response({
        "symbol": "MSFT",
        "last_price": 125.5,
        "market_timestamp": datetime.now(UTC),
        "persisted_at": datetime.now(UTC),
        "source_type": "price_snapshot",
    })
    gateway = SimpleNamespace(price_latest=lambda symbol: current)

    result = dispatch("get_latest_price", SymbolArguments(symbol="MSFT"), gateway)

    assert result.data["last_price"] == 125.5
    assert "latest persisted market snapshot" in result.summary


def test_technical_tool_separates_indicator_close_from_current_quote():
    generated_at = datetime.now(UTC) - timedelta(hours=8)
    technical = _response(
        {
            "symbol": "MSFT",
            "latest_close": 120.0,
            "trend": "up",
            "generated_at": generated_at,
            "data_through": generated_at.date(),
        },
        status=FreshnessStatus.fresh,
    )
    persisted = _response({
        "symbol": "MSFT",
        "last_price": 125.5,
        "market_timestamp": datetime.now(UTC),
        "source_type": "price_snapshot",
    })
    gateway = SimpleNamespace(
        technical=lambda symbol: technical,
        price_latest=lambda symbol: persisted,
    )

    result = dispatch("get_technical_analysis", SymbolArguments(symbol="MSFT"), gateway)

    assert "latest_close" not in result.data
    assert result.data["indicator_reference_close"] == 120.0
    assert result.data["latest_price_snapshot"]["last_price"] == 125.5
    assert "latest persisted price" in result.summary


def test_company_snapshot_exposes_freshness_for_each_time_domain():
    current = _response({
        "symbol": "MSFT",
        "price": 125.5,
        "quote_time": datetime.now(UTC),
        "retrieved_at": datetime.now(UTC),
    })
    profile = _response({"symbol": "MSFT"}, status=FreshnessStatus.fresh)
    technical = _response(
        {"symbol": "MSFT", "latest_close": 120.0},
        status=FreshnessStatus.stale,
    )
    gateway = SimpleNamespace(
        company_profile=lambda symbol: profile,
        portfolio_position=lambda symbol, portfolio_id: None,
        price_latest=lambda symbol: current,
        valuation=lambda symbol: None,
        technical=lambda symbol: technical,
    )

    result = dispatch(
        "get_company_snapshot",
        CompanySnapshotArguments(
            symbol="MSFT",
            include_position=False,
            include_price=True,
            include_valuation=False,
            include_technical=True,
        ),
        gateway,
    )

    assert result.data["section_freshness"]["price"]["status"] == "live"
    assert result.data["section_freshness"]["technical"]["status"] == "stale"
