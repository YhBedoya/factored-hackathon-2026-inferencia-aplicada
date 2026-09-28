"""`AddressVault`: keeps a customer-typed delivery address out of the LLM,
`slots`, `facts`, `PlanStep.args` and the `ui` payload (D2-B D4, R5).

`put_address` is the only operation the rest of the graph needs: a flow
never reads a raw address back, it only carries the `"⟨ADDR_n⟩"` token
`order_replacement` accepts. This module imports only the stdlib -- it must
never import `app.domains.conversation` (`06` §2) -- so it stays swappable
for the real, Fernet-backed vault (D5) without the conversation graph
noticing the difference.
"""

from typing import Protocol

__all__ = ["AddressVault", "InMemoryAddressVault"]


class AddressVault(Protocol):
    def put_address(self, raw: str) -> str:
        """Store `raw` and return its opaque reference (`"⟨ADDR_n⟩"`)."""
        ...


class InMemoryAddressVault:
    """`AddressVault` bound to one conversation, in-memory only.

    `raw` never leaves this object: `put_address` returns only the token.
    Numbering starts at 1 and is private to the instance, so two
    conversations (two vaults) each start their own `⟨ADDR_1⟩`.
    """

    def __init__(self) -> None:
        self._addresses: dict[str, str] = {}

    def put_address(self, raw: str) -> str:
        ref = f"⟨ADDR_{len(self._addresses) + 1}⟩"
        self._addresses[ref] = raw
        return ref
