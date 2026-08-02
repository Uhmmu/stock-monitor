"""Read-only IBKR integration boundary with lazy route imports.

Database models and parsers must be importable without loading Playwright,
FastAPI routes, or network clients.  The application still gets the same two
router attributes through ``__getattr__``.
"""

__all__ = ["router", "formal_router"]


def __getattr__(name: str):
    if name == "router":
        from .routes import router
        return router
    if name == "formal_router":
        from .formal_routes import router
        return router
    raise AttributeError(name)
