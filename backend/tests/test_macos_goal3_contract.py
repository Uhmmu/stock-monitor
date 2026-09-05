"""Compatibility gates for the native macOS Goal M3 read paths."""

from app.main import app


def test_goal3_bounded_lists_keep_backward_compatible_pagination_parameters():
    schema = app.openapi()
    for path in ("/api/alerts", "/api/investigations", "/api/reports"):
        parameters = {item["name"]: item for item in schema["paths"][path]["get"]["parameters"]}
        assert parameters["limit"]["schema"]["maximum"] == 100
        assert parameters["offset"]["schema"]["minimum"] == 0

    news_parameters = {
        item["name"]: item for item in schema["paths"]["/api/news"]["get"]["parameters"]
    }
    assert news_parameters["limit"]["schema"]["maximum"] == 200
    assert news_parameters["offset"]["schema"]["minimum"] == 0


def test_goal3_routes_remain_authenticated_and_server_authoritative():
    route_by_path = {
        route.path: route
        for route in app.routes
        if route.path in {
            "/api/dashboard",
            "/api/market/realtime/stream",
            "/api/stock-management",
            "/api/news/market",
            "/api/calendar/events",
            "/api/reports/{report_id}",
        }
    }
    assert set(route_by_path) == {
        "/api/dashboard",
        "/api/market/realtime/stream",
        "/api/stock-management",
        "/api/news/market",
        "/api/calendar/events",
        "/api/reports/{report_id}",
    }
    assert all(route.dependencies for route in route_by_path.values())
