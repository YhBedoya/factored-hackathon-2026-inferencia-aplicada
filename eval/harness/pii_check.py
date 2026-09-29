"""PII scan over a run's LLM-call export (D20, R5).

Independent of `app.core.pii` on purpose: a bug in the masker must not blind
the check that audits it. Prints only `row_id kind`, never a value.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPORTS = Path(__file__).resolve().parents[1] / "reports"

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_CARD_RE = re.compile(r"(?<![\d⟨])(?:\d[ -]?){12,18}\d(?!\d)")
_PHONE_RE = re.compile(r"(?<![\w⟨])\+\d[\d ()-]{8,16}\d")
_MIN_NAME_LEN = 3


@dataclass(frozen=True)
class Hit:
    row_id: str
    kind: str


def _fold(text: str) -> str:
    """Lowercase and strip accents so `José` matches `jose`."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _word_re(value: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(_fold(value))}(?!\w)")


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _known_patterns(
    personas_pii: list[dict[str, Any]],
) -> list[tuple[str, re.Pattern[str]]]:
    out: list[tuple[str, re.Pattern[str]]] = []
    seen: set[tuple[str, str]] = set()
    for p in personas_pii:
        singles = {
            "DOC": p.get("document_number"),
            "EMAIL": p.get("email"),
            "PHONE": p.get("phone"),
        }
        for kind, value in singles.items():
            if value and (kind, _fold(str(value))) not in seen:
                seen.add((kind, _fold(str(value))))
                out.append((f"KNOWN_{kind}", _word_re(str(value))))
        for field in ("first_name", "last_name"):
            for word in str(p.get(field) or "").split():
                if len(word) >= _MIN_NAME_LEN and ("NAME", _fold(word)) not in seen:
                    seen.add(("NAME", _fold(word)))
                    out.append(("KNOWN_NAME", _word_re(word)))
    return out


def scan(rows: list[dict[str, Any]], personas_pii: list[dict[str, Any]]) -> list[Hit]:
    """One `Hit` per (row, kind) found in `input_text`."""
    known = _known_patterns(personas_pii)
    hits: list[Hit] = []
    for n, row in enumerate(rows, start=1):
        row_id = str(row.get("id") or row.get("row_id") or n)
        text = str(row.get("input_text") or "")
        folded = _fold(text)
        kinds: list[str] = [kind for kind, rx in known if rx.search(folded)]
        if _EMAIL_RE.search(text):
            kinds.append("EMAIL_PATTERN")
        if _PHONE_RE.search(text):
            kinds.append("PHONE_PATTERN")
        for m in _CARD_RE.finditer(text):
            digits = re.sub(r"\D", "", m.group())
            if 13 <= len(digits) <= 19 and _luhn(digits):
                kinds.append("CARD_PATTERN")
                break
        hits.extend(Hit(row_id, k) for k in dict.fromkeys(kinds))
    return hits


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _persona_ids(results: list[dict[str, Any]]) -> list[str]:
    ids = {
        str(r.get("persona") or r.get("customer_id"))
        for r in results
        if r.get("persona") or r.get("customer_id")
    }
    return sorted(ids)


def _load_personas_pii(customer_ids: list[str]) -> list[dict[str, Any]]:
    import psycopg  # lazy: only the CLI needs a database

    dsn = os.environ["GOLDEN_DATABASE_URL"].replace("+asyncpg", "")
    with psycopg.connect(dsn) as conn:
        cur = conn.execute(
            "SELECT document_number, email, mobile_phone, first_name, last_name "
            "FROM bank.customers WHERE customer_id = ANY(%s)",
            (customer_ids,),
        )
        return [
            {
                "document_number": d,
                "email": e,
                "phone": ph,
                "first_name": f,
                "last_name": ln,
            }
            for d, e, ph, f, ln in cur.fetchall()
        ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", required=True, help="run id under eval/reports/")
    args = ap.parse_args(argv)
    run_dir = REPORTS / args.run
    rows = _read_jsonl(run_dir / "llm_calls.jsonl")
    personas = _load_personas_pii(_persona_ids(_read_jsonl(run_dir / "results.jsonl")))
    hits = scan(rows, personas)
    for h in hits:
        print(f"{h.row_id} {h.kind}")
    print(f"{len(hits)} hits")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
