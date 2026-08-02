class IbkrError(Exception):
    code = "IBKR_API_ERROR"
    status_code = 502

    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail


class IbkrDisabledError(IbkrError):
    code, status_code = "GATEWAY_DISABLED", 503


class IbkrGatewayUnavailableError(IbkrError):
    code, status_code = "GATEWAY_UNAVAILABLE", 503


class IbkrGatewayTimeoutError(IbkrError):
    code, status_code = "GATEWAY_TIMEOUT", 504


class IbkrAuthenticationRequiredError(IbkrError):
    code, status_code = "AUTHENTICATION_REQUIRED", 401


class IbkrBrokerageSessionError(IbkrError):
    code, status_code = "BROKERAGE_SESSION_NOT_CONNECTED", 409


class IbkrCompetingSessionError(IbkrError):
    code, status_code = "COMPETING_SESSION", 409


class IbkrInvalidResponseError(IbkrError):
    code, status_code = "IBKR_INVALID_RESPONSE", 502


class IbkrApiError(IbkrError):
    pass


class IbkrConfigurationError(IbkrError):
    code, status_code = "IBKR_CONFIGURATION_ERROR", 503


class IbkrFlexNotConfiguredError(IbkrError):
    code, status_code = "FLEX_NOT_CONFIGURED", 503


class IbkrFlexError(IbkrError):
    code, status_code = "FLEX_REQUEST_FAILED", 502
