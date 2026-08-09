from __future__ import annotations

import logging
import time
from datetime import date
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User

from .exceptions import ResearchError
from .schemas import ResearchErrorResponse, ResearchResponse
from .service import ResearchGateway

logger = logging.getLogger(__name__)
ERROR_RESPONSES = {400: {"model": ResearchErrorResponse}, 403: {"model": ResearchErrorResponse}, 404: {"model": ResearchErrorResponse}, 422: {"model": ResearchErrorResponse}, 500: {"model": ResearchErrorResponse}}
router = APIRouter(prefix="/api/research/v1", tags=["research-data-gateway"], dependencies=[Depends(get_current_user)])


def gateway(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ResearchGateway:
    request.state.research_user_id = user.id
    return ResearchGateway(db, user, getattr(request.state, "research_request_id", None), request=request)


async def research_error_handler(request: Request, exc: ResearchError):
    request_id = getattr(request.state, "research_request_id", str(uuid4()))
    logger.warning("research_gateway_error request_id=%s user_id=%s endpoint=%s error_code=%s", request_id,
                   getattr(request.state, "research_user_id", None), request.url.path, exc.code.value)
    body = ResearchErrorResponse(request_id=request_id, error={"code": exc.code.value, "message": exc.message, "field": exc.field, "context": exc.context})
    return JSONResponse(status_code=exc.status_code, content=body.model_dump(mode="json"), headers={"X-Research-Error": "1", "X-Research-Error-Code": exc.code.value})


async def research_audit_middleware(request: Request, call_next):
    if not request.url.path.startswith("/api/research/v1"):
        return await call_next(request)
    started = time.perf_counter(); request.state.research_request_id = request.headers.get("X-Request-ID") or str(uuid4())
    error_code = None
    try:
        response = await call_next(request)
        if response.status_code >= 400: error_code = response.headers.get("X-Research-Error-Code") or f"HTTP_{response.status_code}"
    except Exception:
        logger.exception("research_gateway_unhandled request_id=%s endpoint=%s", request.state.research_request_id, request.url.path)
        error_code = "INTERNAL_RESEARCH_ERROR"
        body = ResearchErrorResponse(request_id=request.state.research_request_id, error={"code": error_code, "message": "Research data is temporarily unavailable."})
        response = JSONResponse(status_code=500, content=body.model_dump(mode="json"))
    if response.status_code in {401, 403, 404, 422} and response.headers.get("X-Research-Error") != "1":
        code, message = {
            401: ("FORBIDDEN_RESOURCE", "Authentication is required."),
            403: ("FORBIDDEN_RESOURCE", "The research resource is not accessible."),
            404: ("RESEARCH_NOT_FOUND", "The research resource was not found."),
            422: ("INVALID_PARAMETER", "One or more request parameters are invalid."),
        }[response.status_code]
        body = ResearchErrorResponse(request_id=request.state.research_request_id, error={"code": code, "message": message})
        response = JSONResponse(status_code=response.status_code, content=body.model_dump(mode="json"))
        error_code = code
    response.headers["X-Request-ID"] = request.state.research_request_id
    filters = {k: v[:160] for k, v in request.query_params.items() if k not in {"token", "authorization", "api_key"}}
    logger.info("research_gateway_request request_id=%s user_id=%s endpoint=%s filters=%s result_count=%s source_types=%s warning_codes=%s status=%s duration_ms=%.2f error_code=%s",
                request.state.research_request_id, getattr(request.state, "research_user_id", None), request.url.path,
                filters, getattr(request.state, "research_result_count", None), getattr(request.state, "research_source_types", []),
                getattr(request.state, "research_warning_codes", []), response.status_code,
                (time.perf_counter() - started) * 1000, error_code)
    return response


@router.get("/capabilities", response_model=ResearchResponse[dict], responses=ERROR_RESPONSES, summary="List Research Gateway capabilities")
def capabilities(gw: ResearchGateway = Depends(gateway)): return gw.capabilities()


@router.get("/portfolio/summary", response_model=ResearchResponse[dict], responses=ERROR_RESPONSES, summary="Read the current user's portfolio summary")
def portfolio_summary(portfolio_id: int | None = None, gw: ResearchGateway = Depends(gateway)): return gw.portfolio_summary(portfolio_id)


@router.get("/portfolio/positions", response_model=ResearchResponse[list[dict]], responses=ERROR_RESPONSES, summary="List current user-owned positions")
def portfolio_positions(portfolio_id: int | None = None, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1), sort: str = "symbol", gw: ResearchGateway = Depends(gateway)):
    return gw.portfolio_positions(portfolio_id, page, page_size, sort)


@router.get("/portfolio/positions/{symbol}", response_model=ResearchResponse[dict], responses=ERROR_RESPONSES, summary="Read one user-owned position")
def portfolio_position(symbol: str, portfolio_id: int | None = None, gw: ResearchGateway = Depends(gateway)): return gw.portfolio_position(symbol, portfolio_id)


@router.get("/portfolio/trades", response_model=ResearchResponse[list[dict]], responses=ERROR_RESPONSES, summary="List authoritative trade transactions")
def portfolio_trades(portfolio_id: int | None = None, symbol: str | None = None, start_date: date | None = None, end_date: date | None = None,
                     page: int = Query(1, ge=1), page_size: int = Query(25, ge=1), gw: ResearchGateway = Depends(gateway)):
    return gw.trades(portfolio_id, symbol, start_date, end_date, page, page_size)


@router.get("/news/archives", response_model=ResearchResponse[list[dict]], responses=ERROR_RESPONSES, summary="List persisted news archives")
def news_archives(symbol: str, period: str = "daily", start_date: date | None = None, end_date: date | None = None,
                  page: int = Query(1, ge=1), page_size: int = Query(25, ge=1), gw: ResearchGateway = Depends(gateway)):
    return gw.archives(symbol, period, start_date, end_date, page, page_size)


@router.get("/news", response_model=ResearchResponse[list[dict]], responses=ERROR_RESPONSES, summary="Search persisted company and market news")
def news(symbol: str | None = None, symbols: list[str] = Query(default=[]), query: str | None = Query(None, max_length=200),
         start_date: date | None = None, end_date: date | None = None, provider: str | None = None,
         limit: int = Query(25, ge=1), page: int = Query(1, ge=1), include_market_news: bool = False,
         industry: str | None = Query(None, max_length=192), event_type: str | None = Query(None, max_length=32),
         sentiment: str | None = Query(None, max_length=16), min_importance: int | None = Query(None, ge=0, le=100),
         gw: ResearchGateway = Depends(gateway)):
    values = ([symbol] if symbol else []) + symbols
    return gw.news(values, query, start_date, end_date, provider, include_market_news, page, limit,
                   industry, event_type, sentiment, min_importance)


@router.get("/news/{news_id}", response_model=ResearchResponse[dict], responses=ERROR_RESPONSES, summary="Read one persisted news item")
def news_detail(news_id: int, gw: ResearchGateway = Depends(gateway)): return gw.news_detail(news_id)


@router.get("/sec/filings", response_model=ResearchResponse[list[dict]], responses=ERROR_RESPONSES, summary="List official SEC filing metadata")
def sec_filings(symbol: str | None = None, form_type: str | None = None, start_date: date | None = None, end_date: date | None = None,
                page: int = Query(1, ge=1), page_size: int = Query(25, ge=1), gw: ResearchGateway = Depends(gateway)):
    return gw.sec_filings(symbol, form_type, start_date, end_date, page, page_size)


@router.get("/sec/filings/{filing_id}", response_model=ResearchResponse[dict], responses=ERROR_RESPONSES, summary="Read one SEC filing's safe metadata")
def sec_filing(filing_id: int, gw: ResearchGateway = Depends(gateway)): return gw.sec_filing(filing_id)


@router.get("/sec/events", response_model=ResearchResponse[list[dict]], responses=ERROR_RESPONSES, summary="List extracted SEC events")
def sec_events(symbol: str | None = None, event_type: str | None = None, start_date: date | None = None, end_date: date | None = None,
               page: int = Query(1, ge=1), page_size: int = Query(25, ge=1), gw: ResearchGateway = Depends(gateway)):
    return gw.sec_events(symbol, event_type, start_date, end_date, page, page_size)


@router.get("/sec/financial-periods", response_model=ResearchResponse[list[dict]], responses=ERROR_RESPONSES, summary="Read normalized SEC XBRL periods")
def sec_financial_periods(symbol: str, concept: str | None = None, period_type: str | None = None, start_date: date | None = None,
                          end_date: date | None = None, limit: int = Query(25, ge=1, le=100), gw: ResearchGateway = Depends(gateway)):
    return gw.sec_periods(symbol, concept, period_type, start_date, end_date, limit)


@router.get("/sec/insider-trades", response_model=ResearchResponse[list[dict]], responses=ERROR_RESPONSES, summary="List SEC Form 4 insider transactions")
def insider_trades(symbol: str | None = None, start_date: date | None = None, end_date: date | None = None, transaction_type: str | None = None,
                   page: int = Query(1, ge=1), page_size: int = Query(25, ge=1), gw: ResearchGateway = Depends(gateway)):
    return gw.insider_trades(symbol, start_date, end_date, transaction_type, page, page_size)


@router.get("/sec/institutional-holdings", response_model=ResearchResponse[list[dict]], responses=ERROR_RESPONSES, summary="List SEC 13F institutional holdings")
def institutional_holdings(symbol: str | None = None, report_period: date | None = None, institution: str | None = None,
                           page: int = Query(1, ge=1), page_size: int = Query(25, ge=1), gw: ResearchGateway = Depends(gateway)):
    return gw.institutional_holdings(symbol, report_period, institution, page, page_size)


@router.get("/companies/{symbol}/profile", response_model=ResearchResponse[dict], responses=ERROR_RESPONSES, summary="Read a normalized persisted company profile")
def company_profile(symbol: str, gw: ResearchGateway = Depends(gateway)): return gw.company_profile(symbol)


@router.get("/companies/{symbol}/financials/summary", response_model=ResearchResponse[dict], responses=ERROR_RESPONSES, summary="Read persisted financial summary periods")
def financial_summary(symbol: str, gw: ResearchGateway = Depends(gateway)): return gw.financial_summary(symbol)


@router.get("/companies/{symbol}/financial-statements", response_model=ResearchResponse[list[dict]], responses=ERROR_RESPONSES, summary="Read bounded persisted statement snapshots")
def financial_statements(symbol: str, statement: str, period_type: str = "annual", limit: int = Query(4, ge=1, le=20), gw: ResearchGateway = Depends(gateway)):
    return gw.financial_statements(symbol, statement, period_type, limit)


@router.get("/companies/{symbol}/valuation/history", response_model=ResearchResponse[list[dict]], responses=ERROR_RESPONSES, summary="Read valuation snapshot history")
def valuation_history(symbol: str, start_date: date | None = None, end_date: date | None = None, limit: int = Query(30, ge=1, le=366), gw: ResearchGateway = Depends(gateway)):
    return gw.valuation_history(symbol, start_date, end_date, limit)


@router.get("/companies/{symbol}/valuation", response_model=ResearchResponse[dict], responses=ERROR_RESPONSES, summary="Read the latest persisted valuation snapshot")
def valuation(symbol: str, gw: ResearchGateway = Depends(gateway)): return gw.valuation(symbol)


@router.get("/companies/{symbol}/peers", response_model=ResearchResponse[dict], responses=ERROR_RESPONSES, summary="Read persisted peer relationships")
def peers(symbol: str, gw: ResearchGateway = Depends(gateway)): return gw.peers(symbol)


@router.get("/companies/{symbol}/price/latest", response_model=ResearchResponse[dict], responses=ERROR_RESPONSES, summary="Read the latest persisted quote")
def price_latest(symbol: str, gw: ResearchGateway = Depends(gateway)): return gw.price_latest(symbol)


@router.get("/companies/{symbol}/prices/history", response_model=ResearchResponse[list[dict]], responses=ERROR_RESPONSES, summary="Read persisted daily price history")
def price_history(symbol: str, start_date: date | None = None, end_date: date | None = None, interval: str = "1d",
                  limit: int = Query(500, ge=1, le=2500), gw: ResearchGateway = Depends(gateway)):
    return gw.price_history(symbol, start_date, end_date, interval, limit)


@router.get("/companies/{symbol}/technical/chart", responses={**ERROR_RESPONSES, 200: {"content": {"image/webp": {}}}}, summary="Stream a validated persisted technical chart")
def technical_chart(symbol: str, gw: ResearchGateway = Depends(gateway)):
    path = gw.technical_chart_path(symbol)
    media = {".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}[path.suffix.lower()]
    return FileResponse(path, media_type=media, headers={"Cache-Control": "private, max-age=86400"})


@router.get("/companies/{symbol}/technical", response_model=ResearchResponse[dict], responses=ERROR_RESPONSES, summary="Read normalized persisted technical analysis")
def technical(symbol: str, gw: ResearchGateway = Depends(gateway)): return gw.technical(symbol)


@router.get("/calendar/events", response_model=ResearchResponse[list[dict]], responses=ERROR_RESPONSES, summary="List normalized investment calendar events")
def calendar_events(symbol: str | None = None, symbols: list[str] = Query(default=[]), event_type: str | None = None,
                    start_date: date | None = None, end_date: date | None = None, page: int = Query(1, ge=1),
                    page_size: int = Query(25, ge=1), gw: ResearchGateway = Depends(gateway)):
    return gw.calendar_events(([symbol] if symbol else []) + symbols, event_type, start_date, end_date, page, page_size)


@router.get("/calendar/events/{event_id}", response_model=ResearchResponse[dict], responses=ERROR_RESPONSES, summary="Read one event and its bounded source evidence")
def calendar_event(event_id: str, gw: ResearchGateway = Depends(gateway)): return gw.calendar_event(event_id)


@router.get("/discovery/runs", response_model=ResearchResponse[list[dict]], responses=ERROR_RESPONSES, summary="List current user's opportunity discovery runs")
def discovery_runs(status: str | None = None, start_date: date | None = None, end_date: date | None = None,
                   page: int = Query(1, ge=1), page_size: int = Query(25, ge=1), gw: ResearchGateway = Depends(gateway)):
    return gw.discovery_runs(status, start_date, end_date, page, page_size)


@router.get("/discovery/runs/{run_id}/candidates", response_model=ResearchResponse[list[dict]], responses=ERROR_RESPONSES, summary="List bounded candidates from a user-owned run")
def discovery_candidates(run_id: int, group: str | None = None, status: str | None = None, sort: str = "rank",
                         page: int = Query(1, ge=1), page_size: int = Query(25, ge=1), gw: ResearchGateway = Depends(gateway)):
    if sort != "rank":
        from .enums import ResearchErrorCode
        raise ResearchError(ResearchErrorCode.invalid_parameter, "only sort=rank is supported", field="sort", status_code=422)
    return gw.discovery_candidates(run_id, group, status, page, page_size)


@router.get("/discovery/runs/{run_id}", response_model=ResearchResponse[dict], responses=ERROR_RESPONSES, summary="Read one aggregated user-owned discovery run")
def discovery_run(run_id: int, gw: ResearchGateway = Depends(gateway)): return gw.discovery_run(run_id)


@router.get("/portfolio/analysis", response_model=ResearchResponse[list[dict]], responses=ERROR_RESPONSES, summary="Read persisted portfolio analysis runs")
def portfolio_analysis(portfolio_id: int | None = None, limit: int = Query(10, ge=1, le=20), gw: ResearchGateway = Depends(gateway)):
    return gw.portfolio_analysis(portfolio_id, limit)


@router.get("/market/context", response_model=ResearchResponse[dict], responses=ERROR_RESPONSES, summary="Read the current user's persisted last-good market context")
def market_context(gw: ResearchGateway = Depends(gateway)): return gw.market_context()


@router.get("/ownership/congress-trades", response_model=ResearchResponse[list[dict]], responses=ERROR_RESPONSES, summary="List persisted public official transaction disclosures")
def congress_trades(symbol: str | None = None, person: str | None = None, party: str | None = None, chamber: str | None = None,
                    start_date: date | None = None, end_date: date | None = None, page: int = Query(1, ge=1),
                    page_size: int = Query(25, ge=1, le=100), gw: ResearchGateway = Depends(gateway)):
    return gw.congress_trades(symbol, person, party, chamber, start_date, end_date, page, page_size)


@router.get("/ownership/figures", response_model=ResearchResponse[list[dict]], responses=ERROR_RESPONSES, summary="List persisted tracked public figures")
def tracked_figures(query: str | None = Query(None, max_length=200), page: int = Query(1, ge=1),
                    page_size: int = Query(25, ge=1, le=100), gw: ResearchGateway = Depends(gateway)):
    return gw.tracked_figures(query, page, page_size)


@router.get("/ownership/figures/{figure_id}/positions", response_model=ResearchResponse[list[dict]], responses=ERROR_RESPONSES, summary="Read persisted public figure positions")
def figure_positions(figure_id: int, symbol: str | None = None, gw: ResearchGateway = Depends(gateway)):
    return gw.figure_positions(figure_id, symbol)


@router.get("/ownership/figures/{figure_id}/activity", response_model=ResearchResponse[dict], responses=ERROR_RESPONSES, summary="Read bounded persisted public figure activity")
def public_figure_activity(figure_id: int, start_date: date | None = None, end_date: date | None = None, gw: ResearchGateway = Depends(gateway)):
    return gw.public_figure_activity(figure_id, start_date, end_date)
