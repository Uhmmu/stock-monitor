"""TEST-only execution control-plane services.

This package deliberately contains no exchange client and no live-environment
branch.  A local agent may report observations through the authenticated API;
it remains the only component allowed to talk to an exchange test endpoint.
"""

from app.services.execution.auth import (
    AgentAuthError,
    authenticate_request,
    canonical_request,
    create_agent,
    sign_request,
)
from app.services.execution.health import health_payload
from app.services.execution.intents import (
    claim_next_lease,
    create_test_account,
    expire_leases,
    project_eligible_intents,
)
from app.services.execution.ledger import record_event
from app.services.execution.risk import (
    create_policy,
    is_killed,
    policy_allowed,
    set_kill_switch,
)

__all__ = [
    "AgentAuthError",
    "authenticate_request",
    "canonical_request",
    "claim_next_lease",
    "create_agent",
    "create_policy",
    "create_test_account",
    "expire_leases",
    "health_payload",
    "is_killed",
    "policy_allowed",
    "project_eligible_intents",
    "record_event",
    "set_kill_switch",
    "sign_request",
]
