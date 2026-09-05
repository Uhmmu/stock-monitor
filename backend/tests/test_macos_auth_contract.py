"""Compatibility gate for the native macOS authentication surface."""

import json
from pathlib import Path

from app.main import app


def test_macos_auth_contract_fixture_matches_openapi():
    fixture_path = Path(__file__).parents[2] / "apple" / "Tests" / "Contracts" / "auth-contract-v1.json"
    fixture = json.loads(fixture_path.read_text())
    schema = app.openapi()

    for operation, expected in fixture["endpoints"].items():
        method, path = operation.split(" ", 1)
        responses = schema["paths"][path][method.lower()]["responses"]
        success = responses["200"]["content"]["application/json"]["schema"]["$ref"]
        component_name = success.rsplit("/", 1)[-1]
        assert component_name.endswith(expected["response"])
        contract_schema = schema["components"]["schemas"][component_name]
        assert contract_schema["required"] == expected["required"]

    error_name = fixture["error_response"]
    login_error = schema["paths"]["/api/auth/login"]["post"]["responses"]["401"]
    error_ref = login_error["content"]["application/json"]["schema"]["$ref"]
    assert error_ref.rsplit("/", 1)[-1].endswith(error_name)
