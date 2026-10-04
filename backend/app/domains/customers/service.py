"""Customer profile reads.

`get_profile` feeds NLU context and ADR-021 status precedence; `get_login_profile`
feeds `/auth/me` (D9). Both call `repository`, never SQL directly, and both
raise `ToolUnavailable` for a missing row or an unknown country label, as
`FakeBank.get_profile` does.

See `docs/specs/d2-a-login-read-tools-api.md` D9, D11.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.core.errors import ToolUnavailable
from app.core.pii import KnownPii
from app.domains.customers import repository
from app.domains.customers.schemas import CustomerProfile

__all__ = [
    "COUNTRY_LABELS",
    "LoginProfile",
    "build_known_pii",
    "get_display_names",
    "get_document",
    "get_known_pii",
    "get_login_profile",
    "get_profile",
]

COUNTRY_LABELS: dict[str, Literal["MX", "CO", "AR"]] = {
    "México": "MX",
    "Colombia": "CO",
    "Argentina": "AR",
}


class LoginProfile(BaseModel):
    """The fields `/auth/me` needs (D9). Never carries the full document
    number, only its last 3 characters (D2).
    """

    model_config = ConfigDict(frozen=True)

    first_name: str
    country: Literal["MX", "CO", "AR"]
    customer_status: Literal["Active", "Inactive", "Suspended", "Closed"]
    document_type: str
    document_last3: str


def build_known_pii(
    document_number: str | None, first_name: str | None, last_name: str | None
) -> KnownPii:
    """Names are split into words (3+ letters) so a customer typing only one
    surname is still masked; the shared shape for `FakeBank` and Postgres."""
    words: dict[str, None] = {}
    for full in (first_name, last_name):
        for word in (full or "").split():
            if len(word) >= 3:
                words.setdefault(word, None)
    return KnownPii(document_number=(document_number or "").strip() or None, names=tuple(words))


def _map_country(raw: str) -> Literal["MX", "CO", "AR"]:
    country = COUNTRY_LABELS.get(raw)
    if country is None:
        raise ToolUnavailable(f"unknown country {raw!r}")
    return country


async def get_profile(customer_id: str) -> CustomerProfile:
    row = await repository.fetch_profile(customer_id)
    if row is None:
        raise ToolUnavailable(f"no profile for customer {customer_id!r}")
    return CustomerProfile(
        country=_map_country(row["country"]),
        customer_status=row["customer_status"],
        first_name=(row["first_name"] or "").strip() or None,
        city=(row["city"] or "").strip() or None,
    )


async def get_login_profile(customer_id: str) -> LoginProfile:
    row = await repository.fetch_login_profile(customer_id)
    if row is None:
        raise ToolUnavailable(f"no profile for customer {customer_id!r}")
    return LoginProfile(
        first_name=row["first_name"],
        country=_map_country(row["country"]),
        customer_status=row["customer_status"],
        document_type=row["document_type"],
        document_last3=row["document_last3"],
    )


async def get_known_pii(customer_id: str) -> KnownPii:
    row = await repository.fetch_known_pii(customer_id)
    if row is None:
        raise ToolUnavailable(f"no profile for customer {customer_id!r}")
    return build_known_pii(row["document_number"], row["first_name"], row["last_name"])


async def get_document(customer_id: str) -> tuple[str, str]:
    """`(document_type, document_number)` as stored, for the admin persona
    credentials lookup (D22). Neither value is logged.
    """
    row = await repository.fetch_document(customer_id)
    if row is None:
        raise ToolUnavailable(f"no profile for customer {customer_id!r}")
    return row["document_type"], row["document_number"]


async def get_display_names(customer_ids: list[str]) -> dict[str, str]:
    """Full names for the judges' demo catalog (ADR-036). Rendered in the
    UI only, never logged; an id with no row is left out.
    """
    return await repository.fetch_display_names(customer_ids)
