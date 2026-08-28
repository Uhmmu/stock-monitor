from __future__ import annotations

import json
import time
from typing import Mapping
from urllib.parse import urlsplit

import httpx

from .constants import CONTROL_PREFIX, WIRE_VERSION
from .errors import ControlPlaneError
from .security import build_auth_headers, redact, validate_control_url
from .wire import AgentEvent, Lease


class ControlPlaneClient:
    """Versioned HTTPS lease/event client for the VPS control plane."""

    def __init__(
        self,
        base_url: str,
        agent_id: str,
        token: str,
        *,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
        allow_test_server: bool = False,
        clock=time.time,
    ):
        self.base_url = validate_control_url(base_url, allow_test_server=allow_test_server)
        self.agent_id = agent_id
        self.token = token
        self.clock = clock
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
            verify=True,
        )

    @classmethod
    def for_test(
        cls,
        base_url: str = "http://testserver",
        agent_id: str = "test-agent",
        token: str = "test-token-test-token-test-token-test-token",
        *,
        transport: httpx.BaseTransport | None = None,
        clock=time.time,
    ) -> "ControlPlaneClient":
        return cls(
            base_url,
            agent_id,
            token,
            transport=transport,
            allow_test_server=True,
            clock=clock,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ControlPlaneClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, object] | None = None,
        body: Mapping[str, object] | None = None,
        idempotency_key: str | None = None,
    ) -> object:
        payload = b"" if body is None else json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        query_string = ""
        if query:
            from urllib.parse import urlencode

            query_string = "?" + urlencode(query, doseq=True)
        path_query = path + query_string
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        headers.update(
            build_auth_headers(
                self.token,
                self.agent_id,
                method,
                path_query,
                payload,
                timestamp=int(self.clock()),
            )
        )
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            response = self._client.request(
                method,
                path,
                params=query,
                content=payload if body is not None else None,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise ControlPlaneError("control API request timed out") from exc
        except httpx.TransportError as exc:
            raise ControlPlaneError("control API transport failed") from exc
        if 300 <= response.status_code < 400:
            raise ControlPlaneError("control API redirect rejected")
        try:
            data: object = response.json() if response.content else None
        except ValueError:
            data = {"detail": response.text[:500]}
        if not response.is_success:
            detail = data.get("detail", data.get("message", "control API request failed")) if isinstance(data, Mapping) else "control API request failed"
            raise ControlPlaneError(f"control API HTTP {response.status_code}: {redact(str(detail))}")
        return data

    def get_lease(self) -> Lease | None:
        payload = self._request("GET", f"{CONTROL_PREFIX}/lease", query={"wire_version": WIRE_VERSION})
        if payload is None or payload == {}:
            return None
        if not isinstance(payload, Mapping):
            raise ControlPlaneError("lease response is malformed")
        nested = payload.get("lease", payload)
        if nested in (None, {}):
            return None
        if not isinstance(nested, Mapping):
            raise ControlPlaneError("lease response is malformed")
        return Lease.from_payload(nested)

    def post_event(self, event: AgentEvent) -> object:
        return self.post_event_payload(event.as_dict(), idempotency_key=event.stable_id())

    def post_event_payload(self, payload: Mapping[str, object], *, idempotency_key: str | None = None) -> object:
        return self._request(
            "POST",
            f"{CONTROL_PREFIX}/events",
            body=payload,
            idempotency_key=idempotency_key or str(payload.get("event_id", "")) or None,
        )

    def status(self) -> object:
        return self._request("GET", f"{CONTROL_PREFIX}/status")
