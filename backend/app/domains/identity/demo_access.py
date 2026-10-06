"""Judges' quick-access catalog (ADR-036).

`eval/demo_personas.yaml` (path from `DEMO_PERSONAS_PATH`) lists the 10
personas the landing page's quick-access panel offers. Each one must be a
`dev` persona of the main catalog (`personas.load_catalog()`), so this can
never open a session for an arbitrary customer or a held-out persona. Traits
come from that catalog, turned here into a closed set of chip codes the
frontend translates. The display name is read from `bank.customers` at
request time and is never logged.

The routes are mounted only when `DEMO_QUICK_LOGIN=true`
(`app/api/v1/demo_access.py`), and each call must carry `DEMO_ACCESS_CODE`
(`check_access_code`). Wrong codes count against `rl:demo:<client>`, the
same D7 counter shape as login, so the short code can't be guessed.
"""

import hmac
from typing import Any, Literal

import structlog
import yaml
from pydantic import BaseModel, ConfigDict

from app.core.config import Settings, get_settings
from app.core.errors import NotFound
from app.domains.customers import service as customers_service
from app.domains.identity import personas
from app.domains.identity import service as identity_service
from app.domains.identity.service import LoginLimiter, TooManyAttempts

__all__ = [
    "DemoCodeInvalid",
    "DemoCodeRequired",
    "DemoPersona",
    "InvalidDemoCatalog",
    "Localized",
    "LocalizedList",
    "check_access_code",
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


_logger = structlog.get_logger()

_RATE_LIMIT_KEY_PREFIX = "rl:demo:"


class InvalidDemoCatalog(ValueError):
    """`demo_personas.yaml` names an id that is not a `dev` persona."""


class DemoCodeRequired(Exception):
    """The call carried no access code. Not counted: every landing-page load
    asks for the catalog without one.
    """


class DemoCodeInvalid(Exception):
    """The access code didn't match `DEMO_ACCESS_CODE`; counted as a failure."""


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


def _normalize(code: str) -> str:
    # Judges type or paste it: case and stray spaces don't matter.
    return code.strip().lower()


async def check_access_code(
    code: str | None,
    client: str,
    *,
    limiter: LoginLimiter | None = None,
    settings: Settings | None = None,
) -> None:
    """Pass when `code` matches `DEMO_ACCESS_CODE` (or none is set, dev only).

    Raises `DemoCodeRequired` for a missing code, `DemoCodeInvalid` for a
    wrong one (counted against `rl:demo:<client>`), and `TooManyAttempts`
    once that counter is at `login_max_failures`, even for the right code.
    Neither the code nor `client` is ever logged.
    """
    settings = settings or get_settings()
    expected = _normalize(settings.demo_access_code)
    if not expected:
        return
    given = _normalize(code or "")
    if not given:
        raise DemoCodeRequired("demo access code missing")

    limiter = limiter or identity_service._default_limiter
    key = f"{_RATE_LIMIT_KEY_PREFIX}{client}"
    if await limiter.get_failures(key) >= settings.login_max_failures:
        _logger.warning("demo.code_throttled")
        raise TooManyAttempts("too many wrong demo access codes")
    if not hmac.compare_digest(given.encode(), expected.encode()):
        await limiter.record_failure(key, window_seconds=settings.login_window_seconds)
        _logger.warning("demo.code_failed")
        raise DemoCodeInvalid("demo access code did not match")
