"""Judges' quick-access catalog (ADR-036).

`eval/demo_personas.yaml` (path from `DEMO_PERSONAS_PATH`) lists the 10
personas the landing page's quick-access panel offers. Each one must be a
`dev` persona of the main catalog (`personas.load_catalog()`), so this can
never open a session for an arbitrary customer or a held-out persona. Traits
come from that catalog, turned here into a closed set of chip codes the
frontend translates. The display name is read from `bank.customers` at
request time and is never logged.

The routes are mounted only when `DEMO_QUICK_LOGIN=true`
(`app/api/v1/demo_access.py`).
"""

from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict

from app.core.config import get_settings
from app.core.errors import NotFound
from app.domains.customers import service as customers_service
from app.domains.identity import personas

__all__ = [
    "DemoPersona",
    "InvalidDemoCatalog",
    "Localized",
    "LocalizedList",
    "list_demo_personas",
    "load_demo_catalog",
    "resolve_customer_id",
]

Chip = Literal[
    "credit",
    "debit",
    "blocked",
    "inactive",
    "suspended",
    "recent_decline",
    "pending_tx",
    "reversed_tx",
    "expiring_card",
]


class InvalidDemoCatalog(ValueError):
    """`demo_personas.yaml` names an id that is not a `dev` persona."""


class Localized(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    es: str
    pt: str


class LocalizedList(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    es: list[str]
    pt: list[str]


class _DemoEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    customer_id: str
    purpose: Localized
    prompts: LocalizedList


class DemoPersona(BaseModel):
    """What the panel shows for one persona. `persona_id` is the opaque
    handle the login route takes back; it is never named `customer_id` (R1).
    """

    model_config = ConfigDict(frozen=True)

    persona_id: str
    display_name: str
    country: Literal["MX", "CO", "AR"]
    card_count: int
    chips: list[Chip]
    purpose: Localized
    prompts: LocalizedList


def _chips(traits: dict[str, Any]) -> list[Chip]:
    chips: list[Chip] = []
    kinds = traits.get("card_kinds") or []
    if "credit" in kinds:
        chips.append("credit")
    if "debit" in kinds:
        chips.append("debit")
    if traits.get("blocked"):
        chips.append("blocked")
    status = traits.get("customer_status")
    if status == "Inactive":
        chips.append("inactive")
    elif status == "Suspended":
        chips.append("suspended")
    if traits.get("recent_declines"):
        chips.append("recent_decline")
    if traits.get("has_pending_transaction"):
        chips.append("pending_tx")
    if traits.get("has_reversed_transaction"):
        chips.append("reversed_tx")
    if traits.get("expiring_card"):
        chips.append("expiring_card")
    return chips


def load_demo_catalog() -> list[tuple[_DemoEntry, personas.PersonaEntry]]:
    """The demo entries in file order, each paired with its main-catalog
    persona. Raises `InvalidDemoCatalog` for an id that is not a `dev` persona.
    """
    with get_settings().demo_personas_path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    dev = {p.customer_id: p for p in personas.load_catalog() if p.split == "dev"}
    pairs: list[tuple[_DemoEntry, personas.PersonaEntry]] = []
    for raw in data["personas"]:
        entry = _DemoEntry.model_validate(raw)
        persona = dev.get(entry.customer_id)
        if persona is None:
            raise InvalidDemoCatalog(f"{entry.customer_id!r} is not a dev persona")
        pairs.append((entry, persona))
    return pairs


def resolve_customer_id(persona_id: str) -> str:
    """The customer behind a demo `persona_id`. Raises `NotFound` for any id
    outside the demo catalog, so the route can't be used to log in as anyone
    else.
    """
    if persona_id not in {entry.customer_id for entry, _ in load_demo_catalog()}:
        raise NotFound(f"persona {persona_id!r} is not in the demo catalog")
    return persona_id


async def list_demo_personas() -> list[DemoPersona]:
    pairs = load_demo_catalog()
    names = await customers_service.get_display_names([entry.customer_id for entry, _ in pairs])
    return [
        DemoPersona(
            persona_id=entry.customer_id,
            display_name=names.get(entry.customer_id, entry.customer_id),
            country=persona.traits["country"],  # type: ignore[arg-type]
            card_count=int(persona.traits.get("card_count") or 0),  # type: ignore[arg-type]
            chips=_chips(persona.traits),
            purpose=entry.purpose,
            prompts=entry.prompts,
        )
        for entry, persona in pairs
    ]
