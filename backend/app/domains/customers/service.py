"""Customer profile reads.

`get_profile` feeds NLU context and ADR-021 status precedence; `get_login_profile`
feeds `/auth/me` (D9). Both call `repository`, never SQL directly, and both
raise `ToolUnavailable` for a missing row or an unknown country label, as
`FakeBank.get_profile` does.

See `docs/specs/d2-a-login-read-tools-api.md` D9, D11.
"""

from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.errors import ToolUnavailable
from app.core.pii import KnownPii
from app.domains.customers import repository
from app.domains.customers.schemas import (
    PROFILE_FIELDS,
    CustomerProfile,
    DecisionProfile,
    ProfileField,
    ProfileFormReadOnly,
    ProfileFormView,
    ProfileValues,
)
from app.domains.localization.format import format_date
from app.domains.safety.vault import encrypt_text

__all__ = [
    "COUNTRY_LABELS",
    "LoginProfile",
    "apply_profile_changes",
    "build_known_pii",
    "changed_fields",
    "changed_fields_for_request",
    "get_decision_profile",
    "get_display_names",
    "get_document",
    "get_known_pii",
    "get_login_profile",
    "get_profile",
    "get_profile_form",
    "get_profile_values",
    "income_currency",
    "login_hint",
]

_FOUR_BULLETS = "\u2022" * 4  # the login-hint mask

# AS6: declared income is in the country's local currency.
_INCOME_CURRENCY: dict[str, Literal["MXN", "COP", "ARS"]] = {
    "MX": "MXN",
    "CO": "COP",
    "AR": "ARS",
}


def income_currency(country: str) -> Literal["MXN", "COP", "ARS"]:
    """The currency declared income is shown in (AS6): the local one, which for
    MX differs from the card currency (USD, ADR-014)."""
    return _INCOME_CURRENCY[country]


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


def login_hint(document_type: str, last3: str) -> str:
    """The masked document shown at login and in the profile form (`04` §3): type, four
    bullets, last 3 characters. One definition so both surfaces stay identical (R4).
    """
    return f"{document_type} {_FOUR_BULLETS}{last3}"


def _values_from_row(row: RowMapping) -> ProfileValues:
    income = row["estimated_monthly_income"]
    return ProfileValues(
        email=(row["email"] or "").strip(),
        mobile_phone=(row["mobile_phone"] or "").strip(),
        address=(row["address"] or "").strip(),
        occupation=(row["occupation"] or "").strip(),
        estimated_monthly_income=Decimal(str(income)) if income is not None else Decimal(0),
    )


async def get_profile_values(customer_id: str) -> ProfileValues:
    row = await repository.fetch_profile_values(customer_id)
    if row is None:
        raise ToolUnavailable(f"no profile for customer {customer_id!r}")
    return _values_from_row(row)


async def get_profile_form(customer_id: str, language: Literal["es", "pt"]) -> ProfileFormView:
    """The form's initial view: document masked as the login hint, date of birth
    and currency decided in code (R4). The date is day-first in both languages
    (`02` §7), so `language` doesn't change it today.
    """
    del language
    row = await repository.fetch_profile_form_row(customer_id)
    if row is None:
        raise ToolUnavailable(f"no profile for customer {customer_id!r}")
    country = _map_country(row["country"])
    dob = row["date_of_birth"]
    return ProfileFormView(
        editable=_values_from_row(row),
        read_only=ProfileFormReadOnly(
            full_name=" ".join(
                part.strip()
                for part in (row["first_name"], row["last_name"])
                if part and part.strip()
            ),
            document_masked=login_hint(row["document_type"], row["document_last3"]),
            date_of_birth_display=format_date(dob) if dob is not None else "",
        ),
        income_currency=_INCOME_CURRENCY[country],
    )


def _normalised(values: ProfileValues) -> dict[ProfileField, str | Decimal]:
    return {
        "email": values.email.strip(),
        "mobile_phone": values.mobile_phone.strip(),
        "address": values.address.strip(),
        "occupation": values.occupation.strip(),
        "estimated_monthly_income": Decimal(values.estimated_monthly_income),
    }


async def changed_fields(customer_id: str, submitted: ProfileValues) -> list[ProfileField]:
    """Fields whose submitted value differs from the stored one, in I7 order."""
    current = _normalised(await get_profile_values(customer_id))
    new = _normalised(submitted)
    return [field for field in PROFILE_FIELDS if new[field] != current[field]]


async def apply_profile_changes(
    conn: AsyncConnection,
    customer_id: str,
    changes: Mapping[ProfileField, str],
    *,
    actor: str,
    conversation_id: str | None,
    card_request_id: str | None,
) -> list[ProfileField]:
    """Write the changed columns and one history row per field on the caller's
    transaction (R12): this never commits. Old and new values are stored as
    Fernet ciphertext. Returns the fields actually changed.
    """
    old = await repository.lock_profile_values(conn, customer_id)
    if old is None:
        raise ToolUnavailable(f"no profile for customer {customer_id!r}")
    old_text: dict[str, str | None] = {
        field: (str(old[field]).strip() if old[field] is not None else None)
        for field in PROFILE_FIELDS
    }
    columns: dict[str, Any] = {}
    applied: list[ProfileField] = []
    for field in PROFILE_FIELDS:
        if field not in changes:
            continue
        new_text = changes[field].strip()
        previous = old_text[field]
        if field == "estimated_monthly_income":
            same = previous is not None and Decimal(previous) == Decimal(new_text)
            column_value: Any = Decimal(new_text)
        else:
            same = previous == new_text
            column_value = new_text
        if same:
            continue
        columns[field] = column_value
        applied.append(field)
        await repository.insert_history_row(
            conn,
            customer_id=customer_id,
            field=field,
            old_value_enc=encrypt_text(previous) if previous is not None else None,
            new_value_enc=encrypt_text(new_text),
            actor=actor,
            conversation_id=conversation_id,
            card_request_id=card_request_id,
        )
    if columns:
        await repository.update_profile_columns(conn, customer_id, columns)
    return applied


async def get_decision_profile(customer_id: str) -> DecisionProfile:
    row = await repository.fetch_decision_profile(customer_id)
    if row is None:
        raise ToolUnavailable(f"no profile for customer {customer_id!r}")
    income = row["estimated_monthly_income"]
    return DecisionProfile(
        credit_score=row["credit_score"],
        segment=(row["segment"] or "").strip() or None,
        tenure_years=row["tenure_years"],
        occupation=(row["occupation"] or "").strip() or None,
        estimated_monthly_income=Decimal(str(income)) if income is not None else None,
        country=_map_country(row["country"]),
    )


async def changed_fields_for_request(card_request_id: str) -> set[ProfileField]:
    """Fields a card request's profile edit changed (drives the panel's "just changed" flags)."""
    known = set(PROFILE_FIELDS)
    return {f for f in await repository.fetch_history_fields(card_request_id) if f in known}  # type: ignore[misc]
