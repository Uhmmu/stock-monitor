"""Standardized technical-analysis contracts and a service boundary.

The holdings module must never import or call individual analyzer implementations.
It only consumes the normalized contracts exposed here via `get_latest`.

Dependency direction:
    market data -> technical-analysis engine -> standardized results
    -> holdings position interpreter -> holdings UI
"""
from app.services.technical_analysis.schemas import (
    ArrivalEstimate,
    PriceLevelZone,
    TechnicalResult,
    TechnicalSignal,
)
from app.services.technical_analysis.service import get_latest

__all__ = [
    "ArrivalEstimate",
    "PriceLevelZone",
    "TechnicalResult",
    "TechnicalSignal",
    "get_latest",
]
