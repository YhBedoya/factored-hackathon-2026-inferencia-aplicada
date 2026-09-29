"""Identity models: the session the rest of the app trusts, the login
request body and the profile the API hands back after login.

See `docs/specs/d2-a-login-read-tools-api.md` D1, D2, D6, D9,
`docs/specs/d4-b-disputes-handoff-screens.md` D3, D4 and
`docs/solution-docs/04-contracts.md` §3 "Login and `/me`".
"""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

__all__ = [
    "DocumentType",
    "LoginRequest",
    "MeResponse",
    "Session",
    "StaffLoginRequest",
    "StaffMeResponse",
    "require_customer_id",
]

DocumentType = Literal["DNI", "CC", "CE", "Pasaporte"]


class Session(BaseModel):
    """What `get_session()` returns to a route (D6). `customer_id` lives
    only here on the request path (R1): no route, tool or prompt takes it
    as an argument, and no other model in this module carries it.

    D4: a `customer` session always carries a `customer_id`, and an `agent`
    session never does. Customer-only code narrows through
    `require_customer_id` rather than asserting the field itself.
    """

    model_config = ConfigDict(frozen=True)

    account_id: UUID
    role: Literal["customer", "agent"]
    customer_id: str | None
    step_up_at: datetime | None

    @model_validator(mode="after")
    def _customer_id_matches_role(self) -> Self:
        if self.role == "customer" and self.customer_id is None:
            raise ValueError("a customer session requires customer_id")
        if self.role == "agent" and self.customer_id is not None:
            raise ValueError("an agent session must not carry customer_id")
        return self


class LoginRequest(BaseModel):
    """`POST /auth/login` body (D1). `document_number` has deliberately no
    length or pattern constraint: a validation error must never be able to
    echo it back, normalized or not (D2).
    """

    model_config = ConfigDict(frozen=True)

    document_type: DocumentType
    document_number: str
    password: str


class MeResponse(BaseModel):
    """`GET /auth/me` and the login response body (D9). Flat, because the
    staff variant (`customer: null`) doesn't exist on this card (D3).
    `login_hint` is masked and formatted in code before this model is built
    (R4): no document number, email, phone, address or last name ever
    reaches it.
    """

    model_config = ConfigDict(frozen=True)

    role: Literal["customer"]
    login_hint: str
    display_name: str
    country: Literal["MX", "CO", "AR"]
    customer_status: Literal["Active", "Inactive", "Suspended", "Closed"]


class StaffLoginRequest(BaseModel):
    """`POST /auth/staff/login` body (D3). Deliberately as bare as
    `LoginRequest`: no length or pattern constraint on either field, so a
    validation error can never echo a partial credential back.
    """

    model_config = ConfigDict(frozen=True)

    username: str
    password: str


class StaffMeResponse(BaseModel):
    """`GET /staff/me` and the staff login response body (D3, D5)."""

    model_config = ConfigDict(frozen=True)

    role: Literal["agent"]
    display_name: str


def require_customer_id(session: Session) -> str:
    """Narrow a session to its `customer_id` for customer-only code (D4).
    Raises `ValueError` for an agent session -- callers that reach here on
    a route already exclusive to `role="customer"` (R13) only ever hit this
    as a type narrowing, never as a real branch.
    """

    if session.customer_id is None:
        raise ValueError("session has no customer_id (agent session)")
    return session.customer_id
