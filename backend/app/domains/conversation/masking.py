"""The runner's masking step (D4): typed text becomes tokens before it is graph input.

`02` §3's `mask_pii` node lives here as a plain function so the checkpoint never
holds a raw value in `user_text` (R5). The caller owns the vault, and `mask()`
flushes it by itself, so the tokens are persisted before the graph runs.
"""

from app.domains.conversation.tools import BankReadTools
from app.domains.safety.vault import PiiVault

__all__ = ["mask_user_text"]


async def mask_user_text(text: str, *, bank_tools: BankReadTools, vault: PiiVault) -> str:
    """Mask `text` once, using the session customer's own known values (R1: the
    profile is read through the session-bound tools, never by an id)."""
    known = await bank_tools.get_pii_profile()
    return await vault.mask(text, known)
