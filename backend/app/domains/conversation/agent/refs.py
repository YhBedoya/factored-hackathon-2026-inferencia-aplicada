"""This turn's reference book: what Cardy may cite, formatted once in code (D18, R4).

Cardy sees each fact as a `{reference, value}` line inside a data fence and writes
`{reference}` placeholders; `checks.fill_reply` puts the value back. A reference is
`<handle>_<fact key>` (`c1_card_mask`), which matches the placeholder pattern `\\w+`.
Nothing here outlives the turn.
"""

import json
from typing import Any

from app.domains.conversation.nodes.compose import _HIDDEN_KEYS, Country, format_fact
from app.domains.conversation.state import Fact
from app.domains.conversation.templates import Language

__all__ = ["TurnRefs"]


class TurnRefs:
    def __init__(self, language: Language, country: Country) -> None:
        self._language = language
        self._country = country
        self._values: dict[str, str] = {}
        self._facts: dict[str, list[tuple[str, str]]] = {}  # handle -> [(reference, value)]
        self._cards: dict[str, str] = {}  # handle -> card id
        self._txs: dict[str, str] = {}
        # Plain dict the read tools may fill; the node merges it into the graph update.
        self.graph_update: dict[str, Any] = {}
        # Set by `scope_facts`: the node reads them for the `nlu_result` status.
        self.scope_topic: str | None = None
        self.scope_kind: str | None = None

    def add_card(self, card_id: str, facts: list[Fact]) -> str:
        handle = self._handle_for(self._cards, card_id, "c")
        self._register(handle, facts)
        return handle

    def add_tx(self, tx_id: str, facts: list[Fact]) -> str:
        handle = self._handle_for(self._txs, tx_id, "t")
        self._register(handle, facts)
        return handle

    def add_group(self, prefix: str, facts: list[Fact]) -> str:
        """Facts that belong to no card or transaction (`scope_facts`, a list summary)."""
        self._register(prefix, facts)
        return prefix

    def add_value(self, fact: Fact) -> str:
        """One fact under its own key as the reference (`close_balance`), for a value that
        belongs to no card handle. The value is formatted by code like any other (R4)."""
        text = format_fact(
            fact.key, {fact.key: fact}, language=self._language, country=self._country
        )
        self._values[fact.key] = text
        return self.render_value(fact.key)

    def render_value(self, reference: str) -> str:
        line = json.dumps(
            {"reference": reference, "value": self._values[reference]}, ensure_ascii=False
        )
        return "\n".join(["```", line, "```"])

    def card_id(self, handle: str) -> str | None:
        return self._cards.get(handle)

    def tx_id(self, handle: str) -> str | None:
        return self._txs.get(handle)

    def keys(self) -> list[str]:
        return list(self._values)

    def value(self, reference: str) -> str:
        return self._values[reference]

    def render(self, handle: str) -> str:
        """The data-fenced text Cardy sees for one handle (R6)."""
        lines = [
            json.dumps({"reference": ref, "value": value}, ensure_ascii=False)
            for ref, value in self._facts.get(handle, [])
        ]
        return "\n".join(["```", *lines, "```"])

    @staticmethod
    def _handle_for(known: dict[str, str], item_id: str, letter: str) -> str:
        for handle, existing in known.items():
            if existing == item_id:
                return handle
        handle = f"{letter}{len(known) + 1}"
        known[handle] = item_id
        return handle

    def _register(self, handle: str, facts: list[Fact]) -> None:
        by_key = {fact.key: fact for fact in facts}
        entries: list[tuple[str, str]] = []
        for key in by_key:
            if key in _HIDDEN_KEYS:
                continue
            text = format_fact(key, by_key, language=self._language, country=self._country)
            reference = f"{handle}_{key}"
            self._values[reference] = text
            entries.append((reference, text))
        self._facts[handle] = entries
