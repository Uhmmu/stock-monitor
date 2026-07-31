"""Stable external-search tool names and schemas for registry consumers."""

from app.ai_tools.adapters.external_search import (
    EXTERNAL_TOOL_SPECS,
    build_external_search_adapters,
)

__all__ = ["EXTERNAL_TOOL_SPECS", "build_external_search_adapters"]
