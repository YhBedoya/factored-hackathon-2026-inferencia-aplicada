"""`NLUResult` adapter over a learned scorer (spec D9/D10, REQ-R1).

The scorer only says which label a clause looks like. Everything else the
`understand` node would produce is decided here in code, with the same clause
split, negation window and merge rules as `keyword_nlu` (ADR-005): the
classifier is a drop-in for it when the LLM is unavailable. It never returns
`injection_suspected`: that status is the LLM's, and a scorer cannot judge it.
"""

from typing import Literal, Protocol, cast

from app.domains.conversation.baseline.keyword_nlu import (
    lexicon_hits,
    qualified_block_kind,
    split_clauses,
)
from app.domains.conversation.classifier.scorers import Scorer
from app.domains.conversation.flows.card_block import (
    PERMANENT_BLOCK_LABEL,
    TEMPORARY_LOCK_LABEL,
)
from app.domains.conversation.intent_registry import load_registry
from app.domains.conversation.schemas import Intent, NLUResult, NLUSlots, Topic
from app.domains.conversation.state import Pending
from app.domains.localization import parse_card_mask
from app.domains.policy.registry import get_policies

__all__ = ["ClassifierAdapter", "IntentClassifier"]

BlockKind = Literal["temporary_lock", "permanent_block"]


class IntentClassifier(Protocol):
    """What `understand` needs from a classifier (spec §Contracts)."""

    version: str  # "intent_clf@v1"
    label_set_version: int

    def predict(
        self,
        text: str,
        *,
        pending: Pending | None,
        country: str | None,
        previous_language: str,
    ) -> NLUResult: ...


def _chip_block_kind(text: str) -> BlockKind | None:
    """The lock-vs-block quick reply, matched exactly against the flow's own labels."""
    label = text.strip()
    if label in TEMPORARY_LOCK_LABEL.values():
        return "temporary_lock"
    if label in PERMANENT_BLOCK_LABEL.values():
        return "permanent_block"
    return None


class ClassifierAdapter:
    def __init__(self, scorer: Scorer, *, tau: float, version: str, label_set_version: int) -> None:
        self._scorer = scorer
        self._tau = tau
        self.version = version
        self.label_set_version = label_set_version
        self._lexicon_keys = {r.intent: r.lexicon_key for r in load_registry().intents}

    def _clause_label(self, clause: str, scored_text: str) -> str | None:
        """The clause's label when it reaches tau and survives the negation rule (D10)."""
        scores = self._scorer.predict_proba([scored_text])[0]
        label, prob = max(scores.items(), key=lambda kv: kv[1])
        if prob < self._tau:
            return None
        key = self._lexicon_keys.get(label)
        hits = lexicon_hits(clause, key) if key else []
        # Drop only when every keyword hit is negated; a clause with no hit keeps its label.
        if hits and all(hits):
            return None
        return label

    def predict(
        self,
        text: str,
        *,
        pending: Pending | None,
        country: str | None,
        previous_language: str,
    ) -> NLUResult:
        # Imported lazily: `load_session` imports the graph, which imports this package.
        from app.domains.conversation.nodes.load_session import _guess_language

        # `country` and `previous_language` are part of the contract but unused: D9
        # takes `language` from the marker heuristic alone.
        del country, previous_language
        topics = get_policies().scope.topics
        clauses = split_clauses(text)
        # Clauses are accent-stripped; a single clause scores the original text instead.
        labels = [self._clause_label(c, text if len(clauses) == 1 else c) for c in clauses]
        found = list(dict.fromkeys(lbl for lbl in labels if lbl is not None))

        language = _guess_language(text)
        slots = NLUSlots(
            card_hint=(f"last4:{d}" if (d := parse_card_mask(text)) else None),
        )

        awaiting_kind = pending is not None and pending["awaiting_slot"] == "block_kind"
        chip = _chip_block_kind(text) if awaiting_kind else None
        kind = chip or (qualified_block_kind(text) if awaiting_kind else None)
        if chip:
            slots.block_kind = chip
            return NLUResult(language=language, intents=["card_block"], status="clear", slots=slots)

        market = next((t for t in found if t in topics and topics[t].kind == "out_of_market"), None)
        if market:
            slots.topic = cast("Topic", market)
            return NLUResult(language=language, intents=[], status="out_of_market", slots=slots)

        intents = [lbl for lbl in found if lbl not in topics]
        if "unrecognized_charge" in intents:
            intents = ["unrecognized_charge"]
        if intents:
            return self._in_scope(text, language, intents, slots, kind)

        scope = next((t for t in found if t in topics), None)
        if scope:
            slots.topic = cast("Topic", scope)
            return NLUResult(language=language, intents=[], status="out_of_scope", slots=slots)
        return NLUResult(language=language, intents=[], status="ambiguous", slots=slots)

    @staticmethod
    def _in_scope(
        text: str,
        language: Literal["es", "pt"],
        intents: list[str],
        slots: NLUSlots,
        kind: BlockKind | None,
    ) -> NLUResult:
        typed = cast("list[Intent]", intents)
        if "card_block" in intents:
            kind = kind or qualified_block_kind(text)
            if kind is None:
                return NLUResult(
                    language=language,
                    intents=typed,
                    status="ambiguous",
                    slots=slots,
                    clarification="lock_vs_block",
                )
            slots.block_kind = kind
        return NLUResult(language=language, intents=typed, status="clear", slots=slots)
