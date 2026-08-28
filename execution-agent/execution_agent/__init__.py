"""Local, TEST-only Binance USD-M execution agent.

The package deliberately has no live-exchange origin or environment switch.
Its only runtime exchange authority is Binance Futures Demo.
"""

from .constants import BINANCE_TEST_ORIGIN, ENVIRONMENT, VENUE, WIRE_VERSION

__all__ = ["BINANCE_TEST_ORIGIN", "ENVIRONMENT", "VENUE", "WIRE_VERSION"]
