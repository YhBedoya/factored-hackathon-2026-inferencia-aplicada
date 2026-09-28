"""Live HTTP chat client against the running API (D2-A, `07` D2 end-of-day
steps 2-4, A5).

Usage: `make chat-api PERSONA=<customer_id>` or directly
`cd backend && uv run python scripts/chat_api.py --persona <customer_id> [--base-url http://localhost]`.

Reads the persona's row from `<repo root>/data/secrets/credentials.csv`
(written by `make seed-identity`, D5, D8) once, to log in, and never prints
or logs the document number or password. Logs in through the real
`POST /api/v1/auth/login` (not `/test-idp/sessions`, D8) so this exercises
the whole stack: cookies, CSRF, Postgres-backed identity, the registry's
`ToolContext`, `PostgresBank`. Then it opens one conversation and, for each
non-empty stdin line, opens `GET .../stream`, waits for `: connected`, posts
the turn, and prints one line per SSE event until `done` -- the same
`status`/`bot:`/`ui`/`debug`/`error` shapes `04` §3 lists.

The `debug` line mirrors (not imports) `sandbox.py`'s own format, so A5 can
compare this output against `make chat-sandbox` on the same persona: dates
and card masks may differ (Postgres is date-shifted, `FakeBank` reads raw
CSVs), everything else should match.
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

import httpx

__all__ = ["main"]

# `backend/scripts/chat_api.py` -> repo root is two parents up (scripts, backend).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CREDENTIALS_CSV = _REPO_ROOT / "data" / "secrets" / "credentials.csv"

_API_PREFIX = "/api/v1"
_CONNECTED_LINE = ": connected"


class _PersonaNotSeeded(Exception):
    """No `credentials.csv` row for the requested persona (D5, D8)."""


def _load_persona(customer_id: str) -> tuple[str, str, str]:
    """`(document_type, document_number, password)` for `customer_id`, read
    once from the export. Never printed, returned to a caller that prints
    it, or logged.
    """
    if _CREDENTIALS_CSV.exists():
        with _CREDENTIALS_CSV.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row["customer_id"] == customer_id:
                    return row["document_type"], row["document_number"], row["password"]
    raise _PersonaNotSeeded(
        f"no credentials row for {customer_id!r}; run `make seed-identity` first"
    )


def _force_utf8_streams() -> None:
    """Mirror `sandbox.py`'s own guard (T14, orchestrator repair round 1):
    piped stdin/stdout otherwise default to the OS locale code page, which
    mangles the ES/PT accented text and card masks this script prints.
    """
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Live HTTP chat client against the running API.")
    parser.add_argument("--persona", required=True, help="customer_id, from the session (R1)")
    parser.add_argument("--base-url", default="http://localhost")
    return parser.parse_args(argv)


def _csrf_headers(client: httpx.Client) -> dict[str, str]:
    """`X-CSRF-Token` from the readable `csrf_token` cookie login set (D6).
    Read from the jar each call rather than cached once, in case a future
    caller adds a `/auth/refresh` round trip that rotates it.
    """
    token = client.cookies.get("csrf_token")
    return {"X-CSRF-Token": token} if token else {}


def _login(
    client: httpx.Client, *, document_type: str, document_number: str, password: str
) -> None:
    response = client.post(
        f"{_API_PREFIX}/auth/login",
        json={
            "document_type": document_type,
            "document_number": document_number,
            "password": password,
        },
    )
    response.raise_for_status()


def _create_conversation(client: httpx.Client) -> str:
    response = client.post(f"{_API_PREFIX}/conversations", json={}, headers=_csrf_headers(client))
    response.raise_for_status()
    conversation_id: str = response.json()["conversation_id"]
    return conversation_id


def _print_debug(data: dict[str, Any]) -> None:
    """The sandbox's own debug-line format (`sandbox.py`'s `_run_session`,
    mirrored here, not imported, same "mirror, not import" convention as
    `registry.RecordingBankTools`/`runner._BRANCH_NODES`). `slots` drops
    `None` entries the way `NLUSlots.model_dump(exclude_none=True)` would,
    since the wire form is a plain `model_dump(mode="json")` with nulls kept.
    """
    slots = {key: value for key, value in data["slots"].items() if value is not None}
    print(
        f"debug language={data['language']} status={data['status']} "
        f"intents={data['intents']} slots={slots} "
        f"route={data['route']} tools={data['tools_called']}"
    )


def _handle_event(event: str, data: dict[str, Any]) -> bool:
    """Print one line for `(event, data)` (`04` §3 SSE events). Returns
    `True` once `done` is seen, so the caller stops reading the stream.
    """
    if event == "status":
        print(f"status {data['step']}")
    elif event == "message":
        print(f"bot: {data['text']}")
    elif event == "ui":
        print(f"ui {data['kind']}")
    elif event == "debug":
        _print_debug(data)
    elif event == "error":
        print(f"error {data['code']}")
    elif event == "done":
        return True
    return False


def _run_turn(client: httpx.Client, conversation_id: str, text: str) -> None:
    """One turn: open the stream, wait for `: connected`, post the message,
    then print events until `done` (D14). A `409` means another turn already
    holds this conversation's lock -- print `turn in progress` and stop,
    without posting anything else for this line.
    """
    stream_url = f"{_API_PREFIX}/conversations/{conversation_id}/stream"
    messages_url = f"{_API_PREFIX}/conversations/{conversation_id}/messages"

    with client.stream("GET", stream_url) as response:
        lines = response.iter_lines()
        for line in lines:
            if line == _CONNECTED_LINE:
                break

        post_response = client.post(
            messages_url, json={"text": text}, headers=_csrf_headers(client)
        )
        if post_response.status_code == 409:
            print("turn in progress")
            return
        post_response.raise_for_status()

        event: str | None = None
        for line in lines:
            if line.startswith("event: "):
                event = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
                if event is not None and _handle_event(event, data):
                    return
                event = None
            # A blank frame separator or an `: ping` keep-alive comment
            # carries no data; only `event:`/`data:` lines matter here.


def main(argv: list[str] | None = None) -> None:
    """CLI entry point: `python scripts/chat_api.py --persona <customer_id>`."""
    _force_utf8_streams()
    args = _parse_args(argv)

    try:
        document_type, document_number, password = _load_persona(args.persona)
    except _PersonaNotSeeded as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

    with httpx.Client(base_url=args.base_url, timeout=60.0) as client:
        _login(
            client,
            document_type=document_type,
            document_number=document_number,
            password=password,
        )
        conversation_id = _create_conversation(client)

        for line in sys.stdin:
            text = line.rstrip("\n")
            if not text:
                continue
            _run_turn(client, conversation_id, text)


if __name__ == "__main__":
    main()
