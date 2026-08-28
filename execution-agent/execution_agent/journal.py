from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Mapping

from .errors import SecurityError
from .security import ensure_secure_directory, ensure_secure_file, redact, redact_json
from .wire import AgentEvent


def _number(value: object, default: Decimal = Decimal("0")) -> Decimal:
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else default
    except (InvalidOperation, TypeError, ValueError):
        return default


@dataclass(frozen=True)
class JournalOrder:
    client_order_id: str
    lease_id: str
    symbol: str
    side: str
    quantity: Decimal
    status: str
    exchange_order_id: str | None
    executed_quantity: Decimal
    average_price: Decimal | None
    payload: Mapping[str, object]


class Journal:
    """Crash-safe local order/fill/event journal.

    SQLite is intentionally local and single-process. The remote API remains
    the authority for leases; this file only prevents local replay and rebuilds
    what the exchange reported.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        ensure_secure_directory(self.path.parent)
        if self.path.exists():
            ensure_secure_file(self.path)
        else:
            ensure_secure_file(self.path, create=True)
        self.db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout = 5000")
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        self._schema()

    def _schema(self) -> None:
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS orders (
                client_order_id TEXT PRIMARY KEY,
                lease_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity TEXT NOT NULL,
                target_exposure TEXT,
                status TEXT NOT NULL,
                exchange_order_id TEXT,
                executed_quantity TEXT NOT NULL DEFAULT '0',
                average_price TEXT,
                payload TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS uq_journal_lease_order
                ON orders (lease_id, client_order_id);
            CREATE TABLE IF NOT EXISTS fills (
                trade_id TEXT PRIMARY KEY,
                client_order_id TEXT NOT NULL,
                exchange_order_id TEXT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity TEXT NOT NULL,
                price TEXT NOT NULL,
                commission TEXT,
                commission_asset TEXT,
                fill_time REAL,
                payload TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS ix_journal_fills_order ON fills (client_order_id);
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                lease_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at REAL NOT NULL,
                sent_at REAL
            );
            CREATE INDEX IF NOT EXISTS ix_journal_events_pending ON events (status, created_at);
            CREATE TABLE IF NOT EXISTS reconciliations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT NOT NULL,
                mismatch TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS account_equity (
                observed_at REAL PRIMARY KEY,
                equity_usdt TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_journal_account_equity_time ON account_equity (observed_at);
            """
        )
        # SQLite may create WAL companions after the initial permission check.
        # A restrictive umask is set by the caller process; chmod the main file
        # again so a pre-existing permissive file can never be accepted.
        ensure_secure_file(self.path)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "Journal":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def prepare_order(
        self,
        *,
        lease_id: str,
        client_order_id: str,
        symbol: str,
        side: str,
        quantity: Decimal,
        target_exposure: Decimal,
        payload: Mapping[str, object] | None = None,
    ) -> None:
        now = time.time()
        safe = redact_json(dict(payload or {}))
        self.db.execute(
            """
            INSERT INTO orders (
              client_order_id, lease_id, symbol, side, quantity, target_exposure,
              status, payload, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'PREPARED', ?, ?, ?)
            ON CONFLICT(client_order_id) DO UPDATE SET updated_at=excluded.updated_at
            """,
            (client_order_id, lease_id, symbol, side, str(quantity), str(target_exposure), safe, now, now),
        )

    def mark_status(self, client_order_id: str, status: str, *, payload: Mapping[str, object] | None = None) -> None:
        if status not in {"PREPARED", "UNKNOWN", "SUBMITTED", "PARTIAL", "FILLED", "REJECTED", "CANCELLED", "ABANDONED"}:
            raise ValueError(f"invalid journal order status: {status}")
        fields = ["status = ?", "updated_at = ?"]
        values: list[object] = [status, time.time()]
        if payload is not None:
            fields.append("payload = ?")
            values.append(redact_json(dict(payload)))
        values.append(client_order_id)
        self.db.execute(f"UPDATE orders SET {', '.join(fields)} WHERE client_order_id = ?", values)

    def record_exchange_order(self, order: Mapping[str, object]) -> None:
        client_id = str(order.get("clientOrderId", order.get("client_order_id", "")) or "")
        if not client_id:
            raise ValueError("exchange order has no client order ID")
        status = _normalize_order_status(str(order.get("status", "UNKNOWN")))
        executed = str(order.get("executedQty", order.get("executed_quantity", "0")) or "0")
        avg = order.get("avgPrice", order.get("average_price"))
        safe = redact_json(dict(order))
        self.db.execute(
            """
            UPDATE orders SET status=?, exchange_order_id=?, executed_quantity=?, average_price=?, payload=?, updated_at=?
            WHERE client_order_id=?
            """,
            (
                status,
                str(order.get("orderId", order.get("exchange_order_id"))) if order.get("orderId", order.get("exchange_order_id")) is not None else None,
                executed,
                str(avg) if avg not in (None, "") else None,
                safe,
                time.time(),
                client_id,
            ),
        )

    def order(self, client_order_id: str) -> JournalOrder | None:
        row = self.db.execute("SELECT * FROM orders WHERE client_order_id = ?", (client_order_id,)).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row["payload"] or "{}")
        except ValueError:
            payload = {}
        return JournalOrder(
            client_order_id=row["client_order_id"],
            lease_id=row["lease_id"],
            symbol=row["symbol"],
            side=row["side"],
            quantity=_number(row["quantity"]),
            status=row["status"],
            exchange_order_id=row["exchange_order_id"],
            executed_quantity=_number(row["executed_quantity"]),
            average_price=_number(row["average_price"]) if row["average_price"] is not None else None,
            payload=payload,
        )

    def incomplete_orders(self) -> list[JournalOrder]:
        rows = self.db.execute(
            "SELECT client_order_id FROM orders WHERE status IN ('PREPARED','UNKNOWN','SUBMITTED','PARTIAL') ORDER BY created_at"
        ).fetchall()
        return [item for row in rows if (item := self.order(row["client_order_id"])) is not None]

    def record_fill(self, fill: Mapping[str, object]) -> bool:
        trade_id = str(fill.get("id", fill.get("tradeId", fill.get("trade_id", ""))) or "")
        client_id = str(fill.get("clientOrderId", fill.get("client_order_id", "")) or "")
        if not trade_id or not client_id:
            raise ValueError("fill needs trade ID and client order ID")
        cursor = self.db.execute(
            """
            INSERT OR IGNORE INTO fills (
              trade_id, client_order_id, exchange_order_id, symbol, side, quantity, price,
              commission, commission_asset, fill_time, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade_id,
                client_id,
                str(fill.get("order", fill.get("exchange_order_id"))) if fill.get("order", fill.get("exchange_order_id")) is not None else None,
                str(fill.get("symbol", "")).upper(),
                str(fill.get("side", "")).upper(),
                str(fill.get("qty", fill.get("quantity", "0"))),
                str(fill.get("price", "0")),
                str(fill.get("commission", "0")),
                str(fill.get("commissionAsset", fill.get("commission_asset", ""))),
                float(fill.get("time", fill.get("fill_time", time.time() * 1000))) / 1000,
                redact_json(dict(fill)),
            ),
        )
        return cursor.rowcount == 1

    def record_fills(self, fills: Iterable[Mapping[str, object]]) -> int:
        return sum(self.record_fill(fill) for fill in fills)

    def rebuild_positions(self) -> dict[str, Decimal]:
        result: dict[str, Decimal] = {}
        for row in self.db.execute("SELECT symbol, side, quantity FROM fills ORDER BY fill_time, trade_id"):
            sign = Decimal("1") if row["side"].upper() == "BUY" else Decimal("-1")
            result[row["symbol"]] = result.get(row["symbol"], Decimal("0")) + sign * _number(row["quantity"])
        return {symbol: quantity for symbol, quantity in result.items() if quantity != 0}

    def record_event(self, event: AgentEvent) -> bool:
        data = event.as_dict()
        cursor = self.db.execute(
            "INSERT OR IGNORE INTO events (event_id, lease_id, event_type, payload, created_at) VALUES (?, ?, ?, ?, ?)",
            (data["event_id"], event.lease_id, event.event_type, redact_json(data), time.time()),
        )
        return cursor.rowcount == 1

    def pending_events(self, limit: int = 50) -> list[dict[str, object]]:
        rows = self.db.execute(
            "SELECT event_id, payload FROM events WHERE status='pending' ORDER BY created_at LIMIT ?", (limit,)
        ).fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            try:
                result.append(json.loads(row["payload"]))
            except ValueError:
                continue
        return result

    def mark_event_sent(self, event_id: str) -> None:
        self.db.execute("UPDATE events SET status='sent', sent_at=? WHERE event_id=?", (time.time(), event_id))

    def record_reconciliation(self, status: str, mismatch: Mapping[str, object] | None = None) -> None:
        if status not in {"ok", "mismatch", "unknown"}:
            raise ValueError("invalid reconciliation status")
        self.db.execute(
            "INSERT INTO reconciliations(status, mismatch, created_at) VALUES (?, ?, ?)",
            (status, redact_json(dict(mismatch or {})), time.time()),
        )

    def record_account_equity(self, equity_usdt: Decimal, *, observed_at: float | None = None) -> None:
        if equity_usdt.is_finite() is False:
            raise ValueError("equity must be finite")
        self.db.execute(
            "INSERT OR REPLACE INTO account_equity(observed_at, equity_usdt) VALUES (?, ?)",
            (float(observed_at if observed_at is not None else time.time()), str(equity_usdt)),
        )

    def account_risk_metrics(self, equity_usdt: Decimal, *, observed_at: float | None = None) -> tuple[Decimal, Decimal]:
        """Return positive daily loss and peak-to-current drawdown from local samples."""

        at = float(observed_at if observed_at is not None else time.time())
        self.record_account_equity(equity_usdt, observed_at=at)
        day_start = datetime.fromtimestamp(at, tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        day_row = self.db.execute(
            "SELECT equity_usdt FROM account_equity WHERE observed_at >= ? ORDER BY observed_at LIMIT 1", (day_start,)
        ).fetchone()
        peak_row = self.db.execute("SELECT MAX(CAST(equity_usdt AS REAL)) AS peak FROM account_equity").fetchone()
        day_start_equity = _number(day_row["equity_usdt"]) if day_row else equity_usdt
        peak = _number(peak_row["peak"]) if peak_row and peak_row["peak"] is not None else equity_usdt
        return max(Decimal("0"), day_start_equity - equity_usdt), max(Decimal("0"), peak - equity_usdt)

    def mismatch_blocked(self) -> bool:
        row = self.db.execute("SELECT status FROM reconciliations ORDER BY id DESC LIMIT 1").fetchone()
        return row is not None and row["status"] in {"mismatch", "unknown"}

    def last_reconciliation(self) -> dict[str, object] | None:
        row = self.db.execute("SELECT * FROM reconciliations ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            return None
        try:
            mismatch = json.loads(row["mismatch"] or "{}")
        except ValueError:
            mismatch = {}
        return {"status": row["status"], "mismatch": mismatch, "created_at": row["created_at"]}


def _normalize_order_status(status: str) -> str:
    value = status.upper()
    return {
        "NEW": "SUBMITTED",
        "PARTIALLY_FILLED": "PARTIAL",
        "FILLED": "FILLED",
        "CANCELED": "CANCELLED",
        "CANCELLED": "CANCELLED",
        "REJECTED": "REJECTED",
        "EXPIRED": "REJECTED",
    }.get(value, "UNKNOWN")
