"""Goal M6 compatibility handshake contract for the native macOS app."""

from app.api.client_capabilities import (
    API_CONTRACT_VERSION,
    MACOS_CAPABILITIES,
    client_capabilities,
)
from app.main import app


def test_client_capabilities_are_public_typed_and_non_sensitive():
    value = client_capabilities()

    assert value.contract_version == API_CONTRACT_VERSION == 1
    assert value.minimum_macos_client_version == "0.1.0"
    assert value.recommended_macos_client_version == "0.1.0"
    assert set(value.capabilities) == set(MACOS_CAPABILITIES)
    rendered = value.model_dump_json().lower()
    assert not any(secret in rendered for secret in ("token", "password", "proxy", "account_id", "username"))

    operation = app.openapi()["paths"]["/api/client-capabilities"]["get"]
    assert "security" not in operation
    schema_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert schema_ref.endswith("/ClientCapabilitiesOut")


def test_internal_paper_capability_does_not_advertise_live_execution():
    lowered = " ".join(MACOS_CAPABILITIES).lower()
    assert "internal-paper" in lowered
    assert "binance-live" not in lowered
    assert "real-order" not in lowered
