from __future__ import annotations

from .enums import AIErrorCode


class AIError(Exception):
    def __init__(self, code: AIErrorCode, message: str, *, retryable: bool = False, status_code: int = 500):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.status_code = status_code


class ProviderError(AIError):
    pass
