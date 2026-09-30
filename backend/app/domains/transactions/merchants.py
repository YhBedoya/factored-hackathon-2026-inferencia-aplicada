"""The 24 known merchant names and a fuzzy matcher for `tx_search`/
`tx_explain` (spec `d7-b-transactions-traceability-judge.md` A4).

`KNOWN_MERCHANTS` is a code constant (`01` §10): the data has no merchant id,
only free-text `merchant_name`, and matching against a fixed list is the only
way a flow builds `TxFilter.merchant_names` without ever letting the LLM
supply the value (R6, spec "Never"). Matching folds case and accents the same
way `policy/escalation.py::_fold` does, then scores with the stdlib
`difflib` ratio -- there is no `rapidfuzz` in this project (plan "Facts
checked against the repo"). Pure and side-effect free: no I/O, no LLM.
"""

import difflib
import unicodedata

__all__ = ["KNOWN_MERCHANTS", "match_merchant"]

# The 24 distinct `merchant_name` values in `latam_golden.bank.transactions`
# (plan "Facts checked against the repo" -- A4). Business names, not PII.
KNOWN_MERCHANTS: tuple[str, ...] = (
    "Boutique Moda",
    "Cable TV",
    "Centro Comercial",
    "Cine Premium",
    "Clínica Médica",
    "Conciertos Live",
    "Empresa Telefónica",
    "Estación de Servicio",
    "Farmacia Salud",
    "Ferretería",
    "Gasolinera Express",
    "Internet Plus",
    "Laboratorio Central",
    "Mercado Central",
    "Óptica Visión",
    "Restaurante El Buen Sabor",
    "Servicios Públicos",
    "Streaming Music",
    "Super Ahorro",
    "Taxi Seguro",
    "Teatro Nacional",
    "Tienda Don José",
    "Tienda General",
    "Uber",
)

# Below this ratio a candidate is treated as unrelated text, not a typo or a
# missing space: an unrelated merchant name never scores this high against
# any of the 24 (checked by hand for the closest pairs above), while "no
# space"/accent/case variants of the same name do.
_MATCH_CUTOFF = 0.8


def _fold(text: str) -> str:
    """Lowercase and strip accents so `Súper` matches `super`."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def match_merchant(text: str) -> list[str]:
    """Fuzzy-match `text` against `KNOWN_MERCHANTS` (A4).

    Returns the matching canonical names, best match first, or `[]` when
    nothing clears `_MATCH_CUTOFF`. Case and accents are folded on both
    sides before scoring, so `"super ahorro"`, `"Súper Ahorro"` and
    `"superahorro"` all resolve to `["Super Ahorro"]`.
    """
    folded_text = _fold(text)
    scored = [
        (difflib.SequenceMatcher(None, folded_text, _fold(name)).ratio(), name)
        for name in KNOWN_MERCHANTS
    ]
    matches = [(ratio, name) for ratio, name in scored if ratio >= _MATCH_CUTOFF]
    matches.sort(key=lambda pair: pair[0], reverse=True)
    return [name for _, name in matches]
