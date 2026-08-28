from __future__ import annotations


class ExecutionAgentError(Exception):
    """Base error with messages safe to present to an operator."""


class ConfigurationError(ExecutionAgentError):
    pass


class SecurityError(ExecutionAgentError):
    pass


class WireProtocolError(ExecutionAgentError):
    pass


class LeaseError(WireProtocolError):
    pass


class ExecutionBlocked(ExecutionAgentError):
    pass


class InstanceAlreadyRunning(ExecutionAgentError):
    pass


class ControlPlaneError(ExecutionAgentError):
    pass


class BinanceError(ExecutionAgentError):
    def __init__(self, message: str, *, status_code: int | None = None, code: int | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class BinanceTransportError(BinanceError):
    pass


class BinanceTimeout(BinanceTransportError):
    pass


class BinanceRedirectError(BinanceError):
    pass


class BinanceProtocolError(BinanceError):
    pass


class AmbiguousOrderError(BinanceError):
    """The exchange may have accepted an order; query before any retry."""

    def __init__(self, client_order_id: str, message: str, *, status_code: int | None = None):
        super().__init__(message, status_code=status_code)
        self.client_order_id = client_order_id


class UnresolvedOrderError(BinanceError):
    def __init__(self, client_order_id: str, message: str):
        super().__init__(message)
        self.client_order_id = client_order_id
