from app.config import get_settings

from .adapters.external_search import build_external_search_adapters
from .catalog import build_adapters
from .registry import tool_registry
from app.ai_memory.tools import build_memory_adapters


def register_builtin_tools() -> None:
    if tool_registry.list(enabled_only=False): return
    disabled={name.strip() for name in get_settings().ai_tools_disabled_tools.split(",") if name.strip()}
    for adapter in [
        *build_adapters(disabled),
        *build_memory_adapters(disabled),
        *build_external_search_adapters(disabled),
    ]:
        tool_registry.register(adapter)


register_builtin_tools()

__all__ = ["register_builtin_tools", "tool_registry"]
