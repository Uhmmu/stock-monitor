from .enums import ResultMode, ToolErrorCode
from .exceptions import ToolError
from .schemas import ToolDefinition, ToolExecutionContext


class ToolPolicy:
    def validate(self, definition: ToolDefinition, context: ToolExecutionContext, result_mode: ResultMode) -> None:
        if not definition.enabled: raise ToolError(ToolErrorCode.disabled, "The requested tool is disabled.")
        if context.allowed_tools is not None and definition.name not in context.allowed_tools:
            raise ToolError(ToolErrorCode.not_allowed, "The requested tool is not in the caller allowlist.")
        if definition.name in context.denied_tools:
            raise ToolError(ToolErrorCode.not_allowed, "The requested tool is denied for this execution context.")
        if definition.contains_private_data and not context.allow_private_data:
            raise ToolError(ToolErrorCode.private_data_denied, "Private user data is not allowed in this execution context.")
        if result_mode not in definition.supports_result_modes:
            raise ToolError(ToolErrorCode.not_allowed, "The requested result mode is not supported by this tool.")

