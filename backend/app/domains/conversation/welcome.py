"""Cardy's proactive welcome (landing-home-bienvenida D3, D4, D5).

`post_welcome` picks a body different from the customer's last one (Redis
`welcome:last:<customer_id>`, 30-day TTL), prefixes a day-part salutation
(local time in the customer's country, D13), persists the bot message and
returns the display text. No LLM: the text is hand-written (R3, R4), and the
first name only reaches `content`, while `content_masked` is tokenized the
same way the runner masks a customer message (R5).

Bank data comes only through the `tools` registry (`session_profile`,
`known_pii`), never a bank service or repository.
"""

import random
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from app.core.redis import get_redis
from app.core.telemetry import get_trace_id
from app.domains.conversation import store
from app.domains.conversation.templates import (
    WELCOME_BODIES,
    WELCOME_SALUTATIONS,
    DayPart,
    Language,
)
from app.domains.conversation.tools import registry
from app.domains.identity.models import Session
from app.domains.localization.format import BANK_TZ, Country
from app.domains.safety.vault import PostgresPiiVault

__all__ = ["day_part", "pick_body", "post_welcome"]

_LAST_TTL_SECONDS = 30 * 24 * 3600


class _Rng(Protocol):
    def choice(self, seq: list[int], /) -> int: ...


def day_part(now_utc: datetime, country: Country) -> DayPart:
    """Morning 05:00-12:00, afternoon 12:00-19:00, evening otherwise (D13),
    by the local hour in `BANK_TZ[country]`."""
    hour = now_utc.astimezone(BANK_TZ[country]).hour
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 19:
        return "afternoon"
    return "evening"


def pick_body(last_index: int | None, count: int, rng: _Rng) -> int:
    """Uniform among the indices other than `last_index`; any index when it is
    `None` (D4). With a single body there is nothing else to pick."""
    candidates = [i for i in range(count) if i != last_index] or [0]
    return rng.choice(candidates)


async def post_welcome(conversation_id: UUID, *, session: Session, language: Language) -> str:
    """Build, store and return the welcome text for this conversation."""
    ctx = registry.build_tool_context(session, conversation_id, get_trace_id())
    profile = await registry.session_profile(ctx)

    redis = get_redis()
    key = f"welcome:last:{ctx.customer_id}"
    raw_last = await redis.get(key)
    # The index is language-agnostic: ES and PT keep the same body count.
    count = len(WELCOME_BODIES[language])
    index = pick_body(int(raw_last) if raw_last is not None else None, count, random)
    await redis.set(key, str(index), ex=_LAST_TTL_SECONDS)

    salutations = WELCOME_SALUTATIONS[language][day_part(datetime.now(UTC), profile.country)]
    if profile.first_name:
        salutation = salutations["named"].format(customer_name=profile.first_name)
    else:
        salutation = salutations["plain"]
    text = f"{salutation} {WELCOME_BODIES[language][index]}"

    masked = await PostgresPiiVault(conversation_id).mask(text, await registry.known_pii(ctx))
    await store.add_message(
        conversation_id, uuid4(), role="bot", content=text, content_masked=masked
    )
    return text
