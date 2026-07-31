from datetime import date, datetime

from .enums import SourceAuthority, SourceType
from .freshness import aware
from .schemas import ResearchSource
from .security import safe_external_url


def source(
    source_type: SourceType,
    identifier: str | int,
    title: str,
    *, symbol: str | None = None,
    provider: str | None = None,
    authority: SourceAuthority = SourceAuthority.derived,
    published_at: datetime | date | None = None,
    retrieved_at: datetime | date | None = None,
    market_timestamp: datetime | date | None = None,
    fetched_at: datetime | date | None = None,
    persisted_at: datetime | date | None = None,
    market_session: str | None = None,
    data_status: str | None = None,
    provider_role: str | None = None,
    locator: str | None = None,
    url: str | None = None,
) -> ResearchSource:
    return ResearchSource(
        source_id=f"{source_type.value}:{identifier}", source_type=source_type, title=title,
        symbol=symbol, provider=provider, authority=authority,
        published_at=aware(published_at), retrieved_at=aware(retrieved_at), locator=locator, url=safe_external_url(url),
        market_timestamp=aware(market_timestamp), fetched_at=aware(fetched_at),
        persisted_at=aware(persisted_at), market_session=market_session,
        data_status=data_status, provider_role=provider_role,
    )
