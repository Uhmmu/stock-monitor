"""Plugin-style analyzer registry.

New analyzers register themselves here. The engine iterates the registry and, if
one analyzer raises, records the error and continues with the rest — a single
failing analyzer must never fail the whole run or break holdings retrieval.
"""
from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from app.services.technical_analysis.schemas import TechnicalSignal

logger = logging.getLogger(__name__)


@runtime_checkable
class TechnicalAnalyzer(Protocol):
    name: str
    version: str
    supported_timeframes: set[str]

    def analyze(self, symbol: str, timeframe: str, analysis: dict, context: dict) -> list[TechnicalSignal]:
        ...


_REGISTRY: list[TechnicalAnalyzer] = []


def register_analyzer(analyzer: TechnicalAnalyzer) -> None:
    if any(a.name == analyzer.name for a in _REGISTRY):
        return
    _REGISTRY.append(analyzer)


def get_analyzers() -> list[TechnicalAnalyzer]:
    return list(_REGISTRY)


def run_analyzers(symbol: str, timeframe: str, analysis: dict, context: dict) -> tuple[list[TechnicalSignal], list[dict]]:
    """Run every registered analyzer defensively. Returns (signals, errors)."""
    signals: list[TechnicalSignal] = []
    errors: list[dict] = []
    for analyzer in _REGISTRY:
        if timeframe not in analyzer.supported_timeframes:
            continue
        try:
            signals.extend(analyzer.analyze(symbol, timeframe, analysis, context))
        except Exception as exc:  # one analyzer failing must not abort the run
            logger.warning("[technical-analysis] analyzer %s failed for %s: %s", analyzer.name, symbol, exc)
            errors.append({"analyzer": analyzer.name, "version": getattr(analyzer, "version", "?"), "error": type(exc).__name__})
    return signals, errors
