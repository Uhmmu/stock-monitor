"""Analyzer plugins that normalize the persisted weekly analysis into signals.

Each analyzer reads the already-computed `TechnicalAnalysis.analysis` JSON (produced
by the existing engine in `app.services.technical_analysis` module — the weekly
support/resistance/indicator calculator) and re-expresses one slice of it as
standardized `TechnicalSignal`s. This keeps the holdings module decoupled from how
each indicator is actually computed: to add Fibonacci, Gann, volume-profile etc.
later, register another analyzer here without touching holdings-domain code.
"""
from app.services.technical_analysis.analyzers.moving_average import MovingAverageAnalyzer
from app.services.technical_analysis.analyzers.momentum import MomentumAnalyzer
from app.services.technical_analysis.analyzers.swing_point import SwingPointAnalyzer
from app.services.technical_analysis.analyzers.volatility import VolatilityAnalyzer
from app.services.technical_analysis.registry import register_analyzer


def register_default_analyzers() -> None:
    register_analyzer(SwingPointAnalyzer())
    register_analyzer(MovingAverageAnalyzer())
    register_analyzer(MomentumAnalyzer())
    register_analyzer(VolatilityAnalyzer())


__all__ = [
    "MovingAverageAnalyzer",
    "MomentumAnalyzer",
    "SwingPointAnalyzer",
    "VolatilityAnalyzer",
    "register_default_analyzers",
]
