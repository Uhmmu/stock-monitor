"""Public, non-sensitive compatibility contract for native Apple clients."""

from fastapi import APIRouter
from pydantic import BaseModel


router = APIRouter(prefix="/api")

API_CONTRACT_VERSION = 1
MINIMUM_MACOS_CLIENT_VERSION = "0.1.0"
RECOMMENDED_MACOS_CLIENT_VERSION = "0.1.0"
MACOS_CAPABILITIES = (
    "auth.sessions.v1",
    "market.monitoring.v1",
    "company.research.v1",
    "market.intelligence.v1",
    "ai.workspace.v1",
    "portfolio.workspace.v1",
    "ibkr.server-boundary.v1",
    "crypto.research.v1",
    "quant.internal-paper.v1",
    "administration.role-gated.v1",
)


class ClientCapabilitiesOut(BaseModel):
    api_version: str
    contract_version: int
    minimum_macos_client_version: str
    recommended_macos_client_version: str
    capabilities: list[str]


@router.get("/client-capabilities", response_model=ClientCapabilitiesOut)
def client_capabilities() -> ClientCapabilitiesOut:
    """Describe compatibility without exposing configuration, identity, or secrets."""
    return ClientCapabilitiesOut(
        api_version="0.1.0",
        contract_version=API_CONTRACT_VERSION,
        minimum_macos_client_version=MINIMUM_MACOS_CLIENT_VERSION,
        recommended_macos_client_version=RECOMMENDED_MACOS_CLIENT_VERSION,
        capabilities=list(MACOS_CAPABILITIES),
    )
