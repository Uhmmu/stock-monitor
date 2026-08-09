from datetime import date, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import models as m


class ResearchRepository:
    """The only Research Gateway component allowed to return ORM entities."""

    def __init__(self, db: Session):
        self.db = db

    def _page(self, query, model, offset: int, limit: int):
        total = self.db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
        return list(self.db.scalars(query.offset(offset).limit(limit)).all()), int(total)

    def portfolio(self, user_id: int, portfolio_id: int | None = None):
        query = select(m.Portfolio).where(m.Portfolio.user_id == user_id)
        if portfolio_id is not None:
            query = query.where(m.Portfolio.id == portfolio_id)
        return self.db.scalar(query.order_by(m.Portfolio.created_at, m.Portfolio.id).limit(1))

    def strategy_profile(self, user_id: int):
        return self.db.scalar(select(m.PortfolioStrategyProfile).where(m.PortfolioStrategyProfile.user_id == user_id))

    def positions(self, portfolio_id: int, offset: int, limit: int, sort: str):
        orders = {
            "symbol": m.PortfolioPosition.symbol.asc(),
            "symbol_desc": m.PortfolioPosition.symbol.desc(),
            "updated_at": m.PortfolioPosition.updated_at.desc(),
            "quantity": m.PortfolioPosition.total_quantity.desc(),
        }
        query = select(m.PortfolioPosition).where(
            m.PortfolioPosition.portfolio_id == portfolio_id,
            m.PortfolioPosition.total_quantity > 0,
        ).order_by(orders.get(sort, orders["symbol"]), m.PortfolioPosition.id)
        return self._page(query, m.PortfolioPosition, offset, limit)

    def position(self, portfolio_id: int, symbol: str):
        return self.db.scalar(select(m.PortfolioPosition).where(
            m.PortfolioPosition.portfolio_id == portfolio_id,
            m.PortfolioPosition.symbol == symbol,
            m.PortfolioPosition.total_quantity > 0,
        ))

    def position_lot_count(self, portfolio_id: int, symbol: str) -> int:
        return int(self.db.scalar(select(func.count()).select_from(m.PortfolioPositionLot).where(
            m.PortfolioPositionLot.portfolio_id == portfolio_id,
            m.PortfolioPositionLot.symbol == symbol,
            m.PortfolioPositionLot.remaining_quantity > 0,
        )) or 0)

    def trades(self, portfolio_id: int, symbol: str | None, start: date | None, end: date | None, offset: int, limit: int):
        query = select(m.TradeTransaction).where(m.TradeTransaction.portfolio_id == portfolio_id)
        if symbol:
            query = query.where(m.TradeTransaction.symbol == symbol)
        if start:
            query = query.where(m.TradeTransaction.trade_date >= start)
        if end:
            query = query.where(m.TradeTransaction.trade_date <= end)
        query = query.order_by(m.TradeTransaction.trade_date.desc(), m.TradeTransaction.id.desc())
        return self._page(query, m.TradeTransaction, offset, limit)

    def news(self, symbols: list[str], query_text: str | None, start: date | None, end: date | None,
             provider: str | None, include_market: bool, offset: int, limit: int,
             industry: str | None = None, event_type: str | None = None,
             sentiment: str | None = None, min_importance: int | None = None):
        query = select(m.NewsItem)
        scopes = ["company", "market"] if include_market else ["company"]
        query = query.where(m.NewsItem.scope.in_(scopes))
        if symbols:
            symbol_filter = m.NewsItem.ticker.in_(symbols)
            query = query.where(or_(symbol_filter, m.NewsItem.scope == "market") if include_market else symbol_filter)
        if query_text:
            pattern = f"%{query_text.strip()}%"
            query = query.where(or_(m.NewsItem.title.ilike(pattern), m.NewsItem.summary.ilike(pattern), m.NewsItem.ai_summary.ilike(pattern), m.NewsItem.topic.ilike(pattern)))
        if start:
            query = query.where(func.date(func.coalesce(m.NewsItem.published_at, m.NewsItem.found_at)) >= start)
        if end:
            query = query.where(func.date(func.coalesce(m.NewsItem.published_at, m.NewsItem.found_at)) <= end)
        if provider:
            query = query.where(m.NewsItem.provider == provider)
        if industry and industry.strip():
            pattern = f"%{industry.strip()}%"
            query = query.outerjoin(m.StockProfile, m.StockProfile.ticker == m.NewsItem.ticker).outerjoin(
                m.CompanyProfile, m.CompanyProfile.symbol == m.NewsItem.ticker,
            ).where(or_(m.StockProfile.official_industry.ilike(pattern), m.CompanyProfile.industry.ilike(pattern)))
        if event_type and event_type.strip():
            query = query.where(m.NewsItem.ai_event_type.ilike(event_type.strip()))
        if sentiment and sentiment.strip():
            query = query.where(m.NewsItem.ai_sentiment.ilike(sentiment.strip()))
        if min_importance is not None:
            query = query.where(m.NewsItem.ai_importance >= min_importance)
        query = query.order_by(m.NewsItem.published_at.desc().nullslast(), m.NewsItem.found_at.desc(), m.NewsItem.id.desc())
        return self._page(query, m.NewsItem, offset, limit)

    def news_item(self, news_id: int):
        return self.db.get(m.NewsItem, news_id)

    def archives(self, symbol: str, period: str, start: date | None, end: date | None, offset: int, limit: int):
        model = m.DailyNewsArchive if period == "daily" else m.WeeklyNewsArchive
        date_col = model.market_date if period == "daily" else model.week_start
        query = select(model).where(model.ticker == symbol)
        if start:
            query = query.where(date_col >= start)
        if end:
            query = query.where(date_col <= end)
        return self._page(query.order_by(date_col.desc(), model.id.desc()), model, offset, limit)

    def sec_filings(self, symbol: str | None, form: str | None, start: date | None, end: date | None, offset: int, limit: int):
        query = select(m.SecFiling)
        if symbol: query = query.where(m.SecFiling.ticker == symbol)
        if form:
            forms = [value.upper() for value in form] if isinstance(form, (list, tuple, set)) else [form.upper()]
            query = query.where(m.SecFiling.form.in_(forms))
        if start: query = query.where(m.SecFiling.filing_date >= start)
        if end: query = query.where(m.SecFiling.filing_date <= end)
        return self._page(query.order_by(m.SecFiling.filing_date.desc(), m.SecFiling.id.desc()), m.SecFiling, offset, limit)

    def sec_filing(self, filing_id: int): return self.db.get(m.SecFiling, filing_id)

    def sec_events(self, symbol: str | None, event_type: str | None, start: date | None, end: date | None, offset: int, limit: int):
        query = select(m.SecEvent)
        if symbol: query = query.where(m.SecEvent.ticker == symbol)
        if event_type:
            values = list(event_type) if isinstance(event_type, (list, tuple, set)) else [event_type]
            query = query.where(or_(*[clause for value in values for clause in (m.SecEvent.item_code == value, m.SecEvent.item_label.ilike(f"%{value}%"))]))
        if start: query = query.where(m.SecEvent.filing_date >= start)
        if end: query = query.where(m.SecEvent.filing_date <= end)
        return self._page(query.order_by(m.SecEvent.filing_date.desc().nullslast(), m.SecEvent.id.desc()), m.SecEvent, offset, limit)

    def sec_financial_periods(self, symbol: str, concept: str | None, period_type: str | None, start: date | None, end: date | None, limit: int):
        query = select(m.SecFinancialPeriod).where(m.SecFinancialPeriod.ticker == symbol)
        if period_type == "annual":
            query = query.where(m.SecFinancialPeriod.fiscal_period == "FY")
        elif period_type == "quarterly":
            query = query.where(m.SecFinancialPeriod.fiscal_period != "FY")
        if start: query = query.where(m.SecFinancialPeriod.period_end >= start)
        if end: query = query.where(m.SecFinancialPeriod.period_end <= end)
        return list(self.db.scalars(query.order_by(m.SecFinancialPeriod.period_end.desc().nullslast(), m.SecFinancialPeriod.id.desc()).limit(limit)).all())

    def insider_trades(self, symbol: str | None, transaction_type: str | None, start: date | None, end: date | None, offset: int, limit: int):
        query = select(m.SecInsiderTrade)
        if symbol: query = query.where(m.SecInsiderTrade.ticker == symbol)
        if transaction_type: query = query.where(m.SecInsiderTrade.transaction_code == transaction_type.upper())
        if start: query = query.where(m.SecInsiderTrade.transaction_date >= start)
        if end: query = query.where(m.SecInsiderTrade.transaction_date <= end)
        return self._page(query.order_by(m.SecInsiderTrade.transaction_date.desc().nullslast(), m.SecInsiderTrade.id.desc()), m.SecInsiderTrade, offset, limit)

    def institutional_holdings(self, symbol: str | None, report_period: date | None, institution: str | None, offset: int, limit: int):
        query = select(m.Sec13FHolding)
        if symbol: query = query.where(m.Sec13FHolding.ticker == symbol)
        if report_period: query = query.where(m.Sec13FHolding.report_period == report_period)
        if institution: query = query.where(m.Sec13FHolding.manager_name.ilike(f"%{institution.strip()}%"))
        return self._page(query.order_by(m.Sec13FHolding.report_period.desc(), m.Sec13FHolding.value_usd.desc().nullslast(), m.Sec13FHolding.id), m.Sec13FHolding, offset, limit)

    def company(self, symbol: str):
        return self.db.get(m.CompanyProfile, symbol), self.db.get(m.StockProfile, symbol), self.db.scalar(select(m.Security).where(or_(m.Security.yahoo_symbol == symbol, m.Security.display_symbol == symbol)).limit(1))

    def quarterly_financials(self, symbol: str, limit: int = 8):
        return list(self.db.scalars(select(m.QuarterlyFinancial).where(m.QuarterlyFinancial.ticker == symbol).order_by(m.QuarterlyFinancial.period_end.desc()).limit(limit)).all())

    def statement_snapshots(self, symbol: str, frequency: str, limit: int):
        return list(self.db.scalars(select(m.FinancialStatementSnapshot).where(
            m.FinancialStatementSnapshot.ticker == symbol, m.FinancialStatementSnapshot.frequency == frequency,
        ).order_by(m.FinancialStatementSnapshot.period_end.desc()).limit(limit)).all())

    def sec_periods_for_summary(self, symbol: str, limit: int = 8):
        return list(self.db.scalars(select(m.SecFinancialPeriod).where(m.SecFinancialPeriod.ticker == symbol).order_by(m.SecFinancialPeriod.period_end.desc().nullslast()).limit(limit)).all())

    def valuations(self, symbol: str, start: date | None = None, end: date | None = None, limit: int = 1):
        query = select(m.ValuationSnapshot).where(m.ValuationSnapshot.ticker == symbol)
        if start: query = query.where(m.ValuationSnapshot.snapshot_date >= start)
        if end: query = query.where(m.ValuationSnapshot.snapshot_date <= end)
        return list(self.db.scalars(query.order_by(m.ValuationSnapshot.snapshot_date.desc(), m.ValuationSnapshot.id.desc()).limit(limit)).all())

    def peers(self, symbol: str):
        relations = list(self.db.scalars(select(m.PeerRelation).where(m.PeerRelation.base_ticker == symbol).order_by(m.PeerRelation.display_order, m.PeerRelation.peer_ticker)).all())
        excluded = list(self.db.scalars(select(m.PeerExclusion).where(m.PeerExclusion.base_ticker == symbol).order_by(m.PeerExclusion.peer_ticker)).all())
        return relations, excluded

    def latest_price(self, symbol: str):
        return self.db.scalar(
            select(m.PriceSnapshot).where(
                m.PriceSnapshot.symbol == symbol,
                m.PriceSnapshot.source_type == "price_snapshot",
                m.PriceSnapshot.last_price > 0,
            ).order_by(
                m.PriceSnapshot.market_timestamp.desc().nullslast(),
                m.PriceSnapshot.fetched_at.desc().nullslast(),
                m.PriceSnapshot.persisted_at.desc().nullslast(),
            ).limit(1)
        )

    def price_history(self, symbol: str, start: date | None, end: date | None, limit: int):
        query = select(m.HistoricalPrice).where(m.HistoricalPrice.symbol == symbol)
        if start: query = query.where(m.HistoricalPrice.date >= start)
        if end: query = query.where(m.HistoricalPrice.date <= end)
        return list(self.db.scalars(query.order_by(m.HistoricalPrice.date.desc(), m.HistoricalPrice.id.desc()).limit(limit)).all())

    def technical(self, symbol: str): return self.db.get(m.TechnicalAnalysis, symbol)

    def calendar_events(self, symbols: list[str], event_type: str | None, start: date | None, end: date | None, offset: int, limit: int):
        query = select(m.InvestmentCalendarEvent)
        if symbols: query = query.where(m.InvestmentCalendarEvent.symbol.in_(symbols))
        if event_type:
            values = list(event_type) if isinstance(event_type, (list, tuple, set)) else [event_type]
            query = query.where(m.InvestmentCalendarEvent.event_type.in_(values))
        if start: query = query.where(m.InvestmentCalendarEvent.event_date >= start)
        if end: query = query.where(m.InvestmentCalendarEvent.event_date <= end)
        return self._page(query.order_by(m.InvestmentCalendarEvent.event_date, m.InvestmentCalendarEvent.id), m.InvestmentCalendarEvent, offset, limit)

    def calendar_event(self, event_id: str):
        event = self.db.get(m.InvestmentCalendarEvent, event_id)
        evidence = list(self.db.scalars(select(m.InvestmentCalendarEventSource).where(m.InvestmentCalendarEventSource.event_id == event_id).order_by(m.InvestmentCalendarEventSource.fetched_at.desc())).all()) if event else []
        return event, evidence

    def discovery_runs(self, user_id: int, status: str | None, start: date | None, end: date | None, offset: int, limit: int):
        query = select(m.StockDiscoveryRun).where(m.StockDiscoveryRun.user_id == user_id)
        if status: query = query.where(m.StockDiscoveryRun.status == status)
        if start: query = query.where(func.date(m.StockDiscoveryRun.requested_at) >= start)
        if end: query = query.where(func.date(m.StockDiscoveryRun.requested_at) <= end)
        return self._page(query.order_by(m.StockDiscoveryRun.requested_at.desc(), m.StockDiscoveryRun.id.desc()), m.StockDiscoveryRun, offset, limit)

    def discovery_run(self, user_id: int, run_id: int):
        return self.db.scalar(select(m.StockDiscoveryRun).where(m.StockDiscoveryRun.id == run_id, m.StockDiscoveryRun.user_id == user_id))

    def discovery_candidates(self, user_id: int, run_id: int, group_id: str | None, status: str | None, offset: int, limit: int):
        query = select(m.StockDiscoveryCandidate).join(m.StockDiscoveryRun, m.StockDiscoveryRun.id == m.StockDiscoveryCandidate.run_id).where(
            m.StockDiscoveryCandidate.run_id == run_id, m.StockDiscoveryRun.user_id == user_id,
        )
        if status: query = query.where(m.StockDiscoveryCandidate.display_status == status)
        if group_id:
            query = query.join(m.StockDiscoveryCandidateGroupMembership, m.StockDiscoveryCandidateGroupMembership.candidate_id == m.StockDiscoveryCandidate.id).join(
                m.StockDiscoveryCandidateGroup, m.StockDiscoveryCandidateGroup.id == m.StockDiscoveryCandidateGroupMembership.group_id,
            ).where(m.StockDiscoveryCandidateGroup.group_id == group_id)
        return self._page(query.order_by(m.StockDiscoveryCandidate.final_rank.asc().nullslast(), m.StockDiscoveryCandidate.id), m.StockDiscoveryCandidate, offset, limit)

    def discovery_components(self, run_id: int):
        one = lambda model: self.db.scalar(select(model).where(model.run_id == run_id))
        many = lambda model, order: list(self.db.scalars(select(model).where(model.run_id == run_id).order_by(order)).all())
        return {
            "portfolio_snapshot": one(m.StockDiscoveryPortfolioSnapshot),
            "market_context": one(m.StockDiscoveryMarketContext),
            "usage": one(m.StockDiscoveryUsage),
            "exposures": many(m.StockDiscoveryExposure, m.StockDiscoveryExposure.display_order),
            "flows": many(m.StockDiscoveryFlowDirection, m.StockDiscoveryFlowDirection.display_order),
            "groups": many(m.StockDiscoveryCandidateGroup, m.StockDiscoveryCandidateGroup.display_order),
            "sources": many(m.StockDiscoverySource, m.StockDiscoverySource.id),
            "opportunity_history": self.db.scalar(select(m.OpportunityHistory).where(m.OpportunityHistory.run_id == run_id)),
        }

    def discovery_candidate_components(self, candidate_ids: list[int]):
        if not candidate_ids:
            return {}, {}
        metrics: dict[int, list] = {value: [] for value in candidate_ids}
        filters = {}
        for row in self.db.scalars(select(m.StockDiscoveryCandidateMetric).where(m.StockDiscoveryCandidateMetric.candidate_id.in_(candidate_ids)).order_by(m.StockDiscoveryCandidateMetric.candidate_id, m.StockDiscoveryCandidateMetric.metric_key, m.StockDiscoveryCandidateMetric.source)).all():
            metrics[row.candidate_id].append(row)
        for row in self.db.scalars(select(m.StockDiscoveryFilterResult).where(m.StockDiscoveryFilterResult.candidate_id.in_(candidate_ids))).all():
            filters[row.candidate_id] = row
        return metrics, filters

    def portfolio_analysis_runs(self, portfolio_id: int, limit: int = 10):
        return list(self.db.scalars(select(m.PortfolioAnalysisRun).where(
            m.PortfolioAnalysisRun.portfolio_id == portfolio_id,
        ).order_by(m.PortfolioAnalysisRun.created_at.desc(), m.PortfolioAnalysisRun.id.desc()).limit(limit)).all())

    def latest_market_context(self, user_id: int):
        return self.db.execute(select(m.StockDiscoveryMarketContext, m.StockDiscoveryRun).join(
            m.StockDiscoveryRun, m.StockDiscoveryRun.id == m.StockDiscoveryMarketContext.run_id,
        ).where(m.StockDiscoveryRun.user_id == user_id).order_by(
            m.StockDiscoveryRun.completed_at.desc().nullslast(), m.StockDiscoveryRun.id.desc(),
        ).limit(1)).first()

    def congress_trades(self, symbol: str | None, person: str | None, party: str | None, chamber: str | None,
                        start: date | None, end: date | None, offset: int, limit: int):
        query = select(m.CongressTrade)
        if symbol: query = query.where(m.CongressTrade.ticker == symbol)
        if person: query = query.where(m.CongressTrade.filer_name.ilike(f"%{person.strip()}%"))
        if party: query = query.where(m.CongressTrade.party == party.upper())
        if chamber: query = query.where(m.CongressTrade.chamber.ilike(chamber.strip()))
        if start: query = query.where(m.CongressTrade.transaction_date >= start)
        if end: query = query.where(m.CongressTrade.transaction_date <= end)
        return self._page(query.order_by(m.CongressTrade.transaction_date.desc().nullslast(), m.CongressTrade.id.desc()), m.CongressTrade, offset, limit)

    def tracked_figures(self, query_text: str | None, offset: int, limit: int):
        query = select(m.TrackedFigure)
        if query_text:
            pattern = f"%{query_text.strip()}%"
            query = query.where(or_(m.TrackedFigure.display_name.ilike(pattern), m.TrackedFigure.slug.ilike(pattern)))
        return self._page(query.order_by(m.TrackedFigure.is_seed.desc(), m.TrackedFigure.display_name, m.TrackedFigure.id), m.TrackedFigure, offset, limit)

    def tracked_figure(self, figure_id: int):
        return self.db.get(m.TrackedFigure, figure_id)

    def figure_positions(self, figure_slug: str, symbol: str | None = None):
        query = select(m.FigurePosition).where(m.FigurePosition.figure_slug == figure_slug)
        if symbol: query = query.where(m.FigurePosition.ticker == symbol)
        return list(self.db.scalars(query.order_by(m.FigurePosition.adjusted_value.desc(), m.FigurePosition.id)).all())

    def figure_activity(self, filer_id: str | None, start: date | None, end: date | None, limit: int = 100):
        if not filer_id: return []
        query = select(m.CongressTrade).where(m.CongressTrade.filer_id == filer_id)
        if start: query = query.where(m.CongressTrade.transaction_date >= start)
        if end: query = query.where(m.CongressTrade.transaction_date <= end)
        return list(self.db.scalars(query.order_by(m.CongressTrade.transaction_date.desc().nullslast(), m.CongressTrade.id.desc()).limit(limit)).all())
