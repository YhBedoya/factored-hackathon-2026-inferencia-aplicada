"""`AddressVault`: keeps a customer-typed delivery address out of the LLM,
`slots`, `facts`, `PlanStep.args` and the `ui` payload (D2-B D4, R5).

`put_address` is the only operation the rest of the graph needs: a flow
never reads a raw address back, it only carries the `"⟨ADDR_n⟩"` token
`order_replacement` accepts. This module must never import
`app.domains.conversation` (`06` §2), so the graph can swap
`InMemoryAddressVault` for the Fernet-backed `PostgresPiiVault` (D5)
without noticing the difference.

`PiiVault` adds `mask`/`unmask` for the runner (D4): the same raw value in a
conversation always maps to the same `⟨KIND_n⟩` token, numbered per kind.
"""

import re
import uuid
from typing import Protocol

from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.db import get_engine
from app.core.errors import ToolUnavailable
from app.core.pii import TOKEN_RE, KnownPii, find_pii

__all__ = [
    "AddressVault",
    "InMemoryAddressVault",
    "InMemoryPiiVault",
    "PiiVault",
    "PostgresPiiVault",
    "decrypt_text",
    "encrypt_text",
]

_TOKEN_KIND_RE = re.compile(r"⟨([A-Z]+)_(\d+)⟩")
_MAX_UNMASK_DEPTH = 5  # nested tokens (an ADDR value holding a NAME token) resolve in a few passes


def _fernet() -> Fernet:
    # Empty or malformed key raises ValueError: the app refuses to start on it (D21).
    return Fernet(get_settings().pii_vault_key)


def encrypt_text(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_text(cipher: str) -> str:
    return _fernet().decrypt(cipher.encode()).decode()


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


class PiiVault(AddressVault, Protocol):
    async def mask(self, text: str, known: KnownPii) -> str:
        """Replace every PII match in `text` with its `⟨KIND_n⟩` token."""
        ...

    async def unmask(self, text: str) -> str:
        """Put raw values back for every known token, nested ones included."""
        ...

    async def flush(self) -> None:
        """Persist tokens buffered by `put_address`/`mask`."""
        ...


class InMemoryPiiVault:
    """`PiiVault` held in memory: the sandbox and unit tests. Stores plain text."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}  # token -> raw value
        self._pending: dict[str, str] = {}  # buffered, not yet persisted

    async def _load(self) -> None:
        return None

    async def _persist(self, tokens: dict[str, str]) -> None:
        return None

    def _token_for(self, kind: str, raw: str, fresh: dict[str, str]) -> str:
        for token, value in self._values.items():
            if value == raw and token.startswith(f"⟨{kind}_"):
                return token
        number = 1 + max(
            (
                int(m.group(2))
                for t in self._values
                if (m := _TOKEN_KIND_RE.fullmatch(t)) and m.group(1) == kind
            ),
            default=0,
        )
        token = f"⟨{kind}_{number}⟩"
        self._values[token] = raw
        fresh[token] = raw
        return token

    def _require_loaded(self) -> None:
        return None

    def put_address(self, raw: str) -> str:
        self._require_loaded()
        return self._token_for("ADDR", raw, self._pending)

    async def mask(self, text: str, known: KnownPii) -> str:
        await self._load()
        out = text
        for m in reversed(find_pii(text, known)):
            token = self._token_for(m.kind, text[m.start : m.end], self._pending)
            out = f"{out[: m.start]}{token}{out[m.end :]}"
        await self.flush()
        return out

    async def unmask(self, text: str) -> str:
        await self._load()
        out = text
        for _ in range(_MAX_UNMASK_DEPTH):
            nxt = TOKEN_RE.sub(lambda m: self._values.get(m.group(), m.group()), out)
            if nxt == out:
                break
            out = nxt
        return out

    async def flush(self) -> None:
        pending, self._pending = self._pending, {}
        if pending:
            await self._persist(pending)


class PostgresPiiVault(InMemoryPiiVault):
    """`PiiVault` bound to one conversation, rows in `app.pii_vault` (D5).

    Values are Fernet-encrypted at rest. The conversation's rows are read
    once (decrypted into memory) so "same value, same token" and the
    numbering continue across turns and processes. `put_address` is sync, so
    it only buffers; `flush()` persists (`mask` flushes on its own).
    """

    def __init__(self, conversation_id: uuid.UUID) -> None:
        super().__init__()
        self._conversation_id = conversation_id
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            async with get_engine().connect() as conn:
                rows = await conn.execute(
                    text("SELECT token, value_enc FROM app.pii_vault WHERE conversation_id = :c"),
                    {"c": self._conversation_id},
                )
                stored = {token: decrypt_text(enc) for token, enc in rows}
        except SQLAlchemyError as exc:
            raise ToolUnavailable("pii_vault") from exc
        # Rows first, so a token buffered before the first load keeps its number.
        self._values = {**stored, **self._values}
        self._loaded = True

    def _require_loaded(self) -> None:
        # Sync, so it can't read the rows: numbering would collide with earlier turns.
        # The runner always masks the turn's text first, which loads them.
        if not self._loaded:
            raise RuntimeError(
                "PostgresPiiVault.put_address before mask()/unmask() loaded the rows"
            )

    async def _persist(self, tokens: dict[str, str]) -> None:
        params = [
            {
                "c": self._conversation_id,
                "t": token,
                "k": token[1:].split("_", 1)[0],
                "v": encrypt_text(raw),
            }
            for token, raw in tokens.items()
        ]
        try:
            async with get_engine().begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO app.pii_vault (conversation_id, token, kind, value_enc) "
                        "VALUES (:c, :t, :k, :v) ON CONFLICT DO NOTHING"
                    ),
                    params,
                )
        except SQLAlchemyError as exc:
            raise ToolUnavailable("pii_vault") from exc
