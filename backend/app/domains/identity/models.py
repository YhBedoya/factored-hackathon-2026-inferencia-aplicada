"""Identity models: the session the rest of the app trusts, the login
request body and the profile the API hands back after login.

See `docs/specs/d2-a-login-read-tools-api.md` D1, D2, D6, D9 and
`docs/solution-docs/04-contracts.md` §3 "Login and `/me`".
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domains.localization.format import Queue

__all__ = [
    "DocumentType",
    "LoginRequest",
    "MeResponse",
    "Session",
    "StaffLoginRequest",
    "StaffMeResponse",
]

DocumentType = Literal["DNI", "CC", "CE", "Pasaporte"]


class Session(BaseModel):
    """What `get_session()` returns to a route (D6). `customer_id` lives
    only here on the request path (R1): no route, tool or prompt takes it
    as an argument, and no other model in this module carries it. Staff
    sessions (`agent`, `admin`) have no `customer_id` (D15); every customer
    path narrows it before use.
    """

    model_config = ConfigDict(frozen=True)

    account_id: UUID
    role: Literal["customer", "agent", "admin"]
    customer_id: str | None
    step_up_at: datetime | None


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
    """`POST /auth/staff/login` body (D15)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    username: str
    password: str


class StaffMeResponse(BaseModel):
    """`GET /staff/me` and the staff login response body (D15). `queue` is
    `None` for `admin`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Literal["agent", "admin"]
    username: str
    display_name: str
    queue: Queue | None
