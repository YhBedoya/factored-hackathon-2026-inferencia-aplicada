"""Persona catalog and credential lookup for the admin-only staff routes (D22).

The catalog is `eval/personas.yaml` (path from `PERSONAS_PATH`). The password
is recomputed with `generate_password` and the document comes from
`bank.customers` through `customers.service`, so the exported credentials file
is never read (R10). Neither value is ever logged.

See `docs/specs/d7-a-timeline-heldout-report.md` D22.
"""

from typing import Any, Literal

import yaml
from pydantic import BaseModel, JsonValue

from app.core.config import get_settings
from app.core.errors import NotFound
from app.domains.customers import service as customers_service
from app.domains.identity.passwords import generate_password

__all__ = ["PersonaCredentials", "PersonaEntry", "get_credentials", "load_catalog"]

# Keys that describe the persona itself; every other key is a trait.
_NON_TRAITS = frozenset({"customer_id", "split", "notes"})


class PersonaEntry(BaseModel):
    customer_id: str
    split: Literal["dev", "heldout"] | None
    traits: dict[str, JsonValue]
    notes: str | None


class PersonaCredentials(BaseModel):
    customer_id: str
    document_type: str
    document_number: str
    password: str


def _entry(raw: dict[str, Any]) -> PersonaEntry:
    notes = raw.get("notes")
    return PersonaEntry(
        customer_id=raw["customer_id"],
        split=raw.get("split"),
        traits={k: v for k, v in raw.items() if k not in _NON_TRAITS},
        notes=notes.strip() if isinstance(notes, str) else None,
    )


def load_catalog() -> list[PersonaEntry]:
    """The personas in file order."""
    with get_settings().personas_path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return [_entry(raw) for raw in data["personas"]]


async def get_credentials(customer_id: str) -> PersonaCredentials:
    """Credentials for a catalog persona. Raises `NotFound` for any other id,
    so the route can't be used to probe arbitrary customers.
    """
    if customer_id not in {p.customer_id for p in load_catalog()}:
        raise NotFound(f"persona {customer_id!r} is not in the catalog")
    document_type, document_number = await customers_service.get_document(customer_id)
    return PersonaCredentials(
        customer_id=customer_id,
        document_type=document_type,
        document_number=document_number,
        password=generate_password(customer_id, seed=get_settings().credentials_seed),
    )
