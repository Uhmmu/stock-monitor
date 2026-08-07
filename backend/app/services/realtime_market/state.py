"""Redis-backed ephemeral realtime quote and provider-health state."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Mapping

from app.config import Settings, get_settings

from .contracts import IntradayBar, ProviderHealth, RealtimeQuote, RealtimeQuoteEnvelope

logger = logging.getLogger(__name__)

REALTIME_QUOTE_KEY_PREFIX = "market:realtime:"
PROVIDER_HEALTH_KEY_PREFIX = "market:provider:"
PROVIDER_HEALTH_KEY_SUFFIX = ":health"
INTRADAY_BAR_KEY_PREFIX = "market:intraday:"
REALTIME_UPDATES_CHANNEL = "market:realtime:updates"


def quote_key(symbol: str) -> str:
    return f"{REALTIME_QUOTE_KEY_PREFIX}{symbol.strip().upper()}"


def health_key(provider: str) -> str:
    return f"{PROVIDER_HEALTH_KEY_PREFIX}{provider.strip().lower()}{PROVIDER_HEALTH_KEY_SUFFIX}"


def bar_key(symbol: str, timestamp: datetime) -> str:
    moment = timestamp.isoformat().replace("+00:00", "Z")
    return f"{INTRADAY_BAR_KEY_PREFIX}{symbol.strip().upper()}:{moment}"


def _decode(value: Any) -> Any:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _json(value: Any) -> str:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


class RealtimeStateStore:
    """Small Redis adapter with an injectable client for unit tests.

    Redis failures are intentionally fail-soft for market state: upstream
    stream processing may continue in memory and callers can use their regular
    REST fallback.  No token/secret is ever written to Redis by this class.
    """

    def __init__(
        self,
        client: Any | None = None,
        *,
        settings: Settings | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self.ttl_seconds = max(1, int(ttl_seconds or getattr(self.settings, "realtime_quote_ttl_seconds", 180)))

    @property
    def client(self) -> Any | None:
        if self._client is None:
            try:
                import redis

                self._client = redis.Redis.from_url(
                    self.settings.redis_url,
                    socket_connect_timeout=0.25,
                    socket_timeout=0.5,
                    decode_responses=False,
                )
            except Exception:
                self._client = False
        return None if self._client is False else self._client

    def _set(self, key: str, value: Any, *, ttl: int | None = None) -> bool:
        client = self.client
        if client is None:
            return False
        try:
            payload = _json(value)
            if hasattr(client, "setex"):
                client.setex(key, max(1, int(ttl or self.ttl_seconds)), payload)
            else:
                client.set(key, payload, ex=max(1, int(ttl or self.ttl_seconds)))
            return True
        except Exception:
            logger.debug("realtime state Redis write failed", exc_info=True)
            return False

    def _get(self, key: str) -> Any | None:
        client = self.client
        if client is None:
            return None
        try:
            return _decode(client.get(key))
        except Exception:
            logger.debug("realtime state Redis read failed", exc_info=True)
            return None

    def publish(self, event: str, payload: Any) -> bool:
        client = self.client
        if client is None:
            return False
        value = {"event": event, "data": payload.to_dict() if hasattr(payload, "to_dict") else payload}
        try:
            client.publish(REALTIME_UPDATES_CHANNEL, _json(value))
            return True
        except Exception:
            logger.debug("realtime state Redis publish failed", exc_info=True)
            return False

    def set_quote(
        self,
        quote: RealtimeQuote | RealtimeQuoteEnvelope,
        *,
        ttl_seconds: int | None = None,
        publish: bool = True,
    ) -> bool:
        envelope = quote if isinstance(quote, RealtimeQuoteEnvelope) else None
        authoritative = envelope.authoritative_quote if envelope else quote
        if not isinstance(authoritative, RealtimeQuote):
            raise TypeError("set_quote expects RealtimeQuote or RealtimeQuoteEnvelope")
        # Keep the complete envelope in Redis when provenance/reference data is
        # available.  A plain quote remains the compact legacy shape.  The API
        # layer can therefore expose alternate providers/divergence without a
        # second lookup while get_quote() still unwraps the authority safely.
        stored_payload = envelope.to_dict() if envelope else authoritative.to_dict()
        stored = self._set(quote_key(authoritative.symbol), stored_payload, ttl=ttl_seconds)
        if publish:
            event_payload = envelope.to_dict() if envelope else authoritative.to_dict()
            self.publish("quote_update", event_payload)
        return stored

    def get_quote(self, symbol: str) -> RealtimeQuote | None:
        payload = self._get(quote_key(symbol))
        if not isinstance(payload, Mapping):
            return None
        try:
            if isinstance(payload.get("authoritative_quote"), Mapping):
                payload = payload["authoritative_quote"]
            value = dict(payload)
            for key in ("timestamp", "received_at"):
                raw = value.get(key)
                if isinstance(raw, str):
                    value[key] = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return RealtimeQuote(**{key: value[key] for key in RealtimeQuote.__dataclass_fields__ if key in value})
        except (TypeError, ValueError, KeyError):
            return None

    def set_bar(self, bar: IntradayBar, *, ttl_seconds: int | None = None, publish: bool = True) -> bool:
        if not isinstance(bar, IntradayBar):
            raise TypeError("set_bar expects IntradayBar")
        stored = self._set(bar_key(bar.symbol, bar.timestamp), bar.to_dict(), ttl=ttl_seconds)
        if publish:
            self.publish("bar_update", bar.to_dict())
        return stored

    def get_health(self, provider: str) -> dict[str, Any] | None:
        value = self._get(health_key(provider))
        return dict(value) if isinstance(value, Mapping) else None

    def set_health(
        self,
        health: ProviderHealth | Mapping[str, Any],
        *,
        ttl_seconds: int | None = None,
        publish: bool = True,
    ) -> bool:
        value = health.to_dict() if isinstance(health, ProviderHealth) else dict(health)
        provider = str(value.get("provider") or "").strip().lower()
        if not provider:
            raise ValueError("provider health requires provider")
        stored = self._set(health_key(provider), value, ttl=ttl_seconds or self.ttl_seconds)
        if publish:
            self.publish("provider_status", value)
        return stored

    # Explicit aliases used by runner/API wiring.
    set_provider_health = set_health
    get_provider_health = get_health

    def quote(self, symbol: str) -> RealtimeQuote | None:
        return self.get_quote(symbol)

    def health(self, provider: str) -> dict[str, Any] | None:
        return self.get_health(provider)

    get_realtime_quote = get_quote
    set_realtime_quote = set_quote
    publish_update = publish

    def subscribe(self) -> Any | None:
        client = self.client
        if client is None or not hasattr(client, "pubsub"):
            return None
        try:
            subscription = client.pubsub()
            subscription.subscribe(REALTIME_UPDATES_CHANNEL)
            return subscription
        except Exception:
            logger.debug("realtime state Redis subscribe failed", exc_info=True)
            return None
