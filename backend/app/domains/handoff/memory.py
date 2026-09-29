"""`InMemoryHandoffPort`: the `HandoffPort` fake this card wires everywhere.

Used by the B2 flow tests, the sandbox and (until A3's Postgres/Redis port
lands) the API runner (D1). It fills `request` from the fixed
`handoff_request` template instead of calling an LLM, and always sets
`sentiment=None` -- A's real port decides both.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domains.conversation.templates import get_template
from app.domains.handoff.schemas import HandoffDraft, HandoffPacket, HandoffRef
from app.domains.localization.format import queue_label

__all__ = ["InMemoryHandoffPort"]


class InMemoryHandoffPort:
    """Bound to one `(conversation_id, policy_version)` per turn (D1, D19).

    Structurally satisfies `HandoffPort` (checked where it is registered,
    same pattern as `FakeBankWrites`/`PostgresBankWrites` against
    `BankWriteTools`), rather than inheriting from the Protocol. `.packets`
    accumulates every `HandoffPacket` created through this instance, for
    tests and the sandbox to inspect.
    """

    def __init__(self, conversation_id: UUID, policy_version: str) -> None:
        self._conversation_id = conversation_id
        self._policy_version = policy_version
        self.packets: list[HandoffPacket] = []

    async def create(self, draft: HandoffDraft) -> HandoffRef:
        request = get_template("handoff_request", draft.language).format(
            queue_label=queue_label(draft.queue, draft.language)
        )
        handoff_id = uuid4()
        created_at = datetime.now(UTC)
        packet = HandoffPacket(
            **draft.model_dump(),
            handoff_id=handoff_id,
            conversation_id=self._conversation_id,
            request=request,
            sentiment=None,
            policy_version=self._policy_version,
            created_at=created_at,
        )
        self.packets.append(packet)
        return HandoffRef(handoff_id=handoff_id, queue=draft.queue, created_at=created_at)
