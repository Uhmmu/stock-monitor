from typing import Any

from .enums import ToolErrorCode


class ToolError(Exception):
    def __init__(self, code: ToolErrorCode, message: str, *, retryable: bool = False, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code, self.message, self.retryable, self.details = code, message, retryable, details or {}

