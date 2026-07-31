from typing import Any

from .enums import ResearchErrorCode


class ResearchError(Exception):
    def __init__(
        self,
        code: ResearchErrorCode,
        message: str,
        *,
        status_code: int = 400,
        field: str | None = None,
        context: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.field = field
        self.context = context or {}

