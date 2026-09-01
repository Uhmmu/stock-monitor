"""Explicit execution-mode boundary.

PAPER is the only active mode and runs as an in-process simulator.
BINANCE_DEMO and BINANCE_LIVE are abandoned product scope and intentionally
have no adapter.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ExecutionMode(StrEnum):
    PAPER = "paper"
    BINANCE_DEMO = "binance_demo"
    BINANCE_LIVE = "binance_live"


class ExecutionModeBlocked(RuntimeError):
    pass


class PaperExecutionBackend:
    """Credential-free adapter over the existing internal PAPER broker."""

    mode = ExecutionMode.PAPER

    def __init__(self, db: Any, account: Any) -> None:
        self.db = db
        self.account = account

    def submit_order(self, **order: Any) -> Any:
        from app.services.quant.paper import submit_manual_order

        return submit_manual_order(self.db, self.account, **order)

    def cancel_order(self, order_id: int) -> Any:
        from app.services.quant.paper import cancel_order

        return cancel_order(self.db, self.account, order_id)

    def get_account_state(self) -> dict[str, Any]:
        from app.services.quant.paper import account_payload

        return account_payload(self.db, self.account)


def backend_for(mode: ExecutionMode | str, *, db: Any = None, account: Any = None) -> PaperExecutionBackend:
    selected = ExecutionMode(mode)
    if selected is ExecutionMode.PAPER:
        if db is None or account is None:
            raise ValueError("PAPER backend requires a local database account")
        return PaperExecutionBackend(db, account)
    if selected is ExecutionMode.BINANCE_DEMO:
        raise ExecutionModeBlocked("BINANCE_DEMO is abandoned and remains fail-closed")
    raise ExecutionModeBlocked("BINANCE_LIVE is abandoned and remains fail-closed")
