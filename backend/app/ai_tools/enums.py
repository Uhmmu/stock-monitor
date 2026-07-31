from enum import StrEnum


class ResultMode(StrEnum):
    compact = "compact"
    standard = "standard"
    detailed = "detailed"


class ToolStatus(StrEnum):
    success = "success"
    partial = "partial"
    error = "error"
    timeout = "timeout"
    denied = "denied"


class ToolErrorCode(StrEnum):
    not_allowed = "TOOL_NOT_ALLOWED"
    disabled = "TOOL_DISABLED"
    call_limit = "TOOL_CALL_LIMIT_EXCEEDED"
    output_budget = "TOOL_OUTPUT_BUDGET_EXCEEDED"
    arguments_invalid = "TOOL_ARGUMENTS_INVALID"
    timeout = "TOOL_TIMEOUT"
    result_too_large = "TOOL_RESULT_TOO_LARGE"
    private_data_denied = "TOOL_PRIVATE_DATA_DENIED"
    execution_failed = "TOOL_EXECUTION_FAILED"
    not_found = "TOOL_NOT_FOUND"

