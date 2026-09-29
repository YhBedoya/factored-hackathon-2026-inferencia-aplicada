"""Live HTTP chat client against the running API (D2-A, `07` D2 end-of-day
steps 2-4, A5; D3-A D18 adds the guardrail commands below).

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

Commands (D3-A D18; D4-B D7 adds `/pick`), in addition to a plain-text line
for a normal turn:
- `/otp <code>` -- `POST /auth/otp/verify {code}` (never prints the code),
  then, on `200`, runs the `resume: step_up` turn.
- `/confirm` / `/cancel` -- runs a turn against
  `/conversations/{id}/confirmations/{token_id}` for the last `ui.confirm`
  token seen, with `{"decision": "confirm"}` / `{"decision": "cancel"}`.
  Prints `no open confirmation` if no `ui.confirm` event has arrived yet.
- `/replay` -- re-posts the last token this script itself posted to the
  confirmations route with `{"decision": "confirm"}`, without opening a
  stream, to show the server rejects a reused token (R2).
- `/pick <n[,n...]>` -- posts `{"selection": {"tx_ids": [...]}}` for the
  1-based indices into the last `ui.transaction_list` seen, and runs the
  turn like a typed message (D7). Prints `no open transaction list` if no
  `ui.transaction_list` event has arrived yet, or `invalid pick` for a bad
  index -- the server, not this script, is the injection guard (R1).
"""

import argparse
import csv
import json
import sys
from dataclasses import dataclass
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


@dataclass
class _ChatState:
    """Cross-turn state D18's commands need: the last `ui.confirm` token
    seen (for `/confirm`, `/cancel`), the last token this script itself
    posted to the confirmations route (for `/replay`), and the last
    `ui.transaction_list`'s offered ids in the order printed (for `/pick`,
    D4-B D7). None is cleared on use -- the server is the single-use/
    injection enforcement point (R2, R1); this script only remembers what
    a later command refers back to.
    """

    last_confirm_token: str | None = None
    last_posted_token: str | None = None
    last_tx_options: list[str] | None = None


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


def _handle_event(event: str, data: dict[str, Any], state: _ChatState) -> bool:
    """Print one line for `(event, data)` (`04` §3 SSE events). Returns
    `True` once `done` is seen, so the caller stops reading the stream. A
    `ui.confirm` event also updates `state.last_confirm_token` (D18) for a
    later `/confirm` or `/cancel` line; a `ui.transaction_list` event prints
    each option with a 1-based index and updates `state.last_tx_options`
    (D4-B D7) for a later `/pick` line.
    """
    if event == "status":
        print(f"status {data['step']}")
    elif event == "message":
        print(f"bot: {data['text']}")
    elif event == "ui":
        print(f"ui {data['kind']}")
        if data["kind"] == "confirm":
            state.last_confirm_token = data["payload"]["token_id"]
        elif data["kind"] == "transaction_list":
            options = data["payload"]["options"]
            state.last_tx_options = [option["tx_id"] for option in options]
            for index, option in enumerate(options, start=1):
                print(f"  {index}. {option['label']}")
    elif event == "debug":
        _print_debug(data)
    elif event == "error":
        print(f"error {data['code']}")
    elif event == "done":
        return True
    return False


def _run_turn(
    client: httpx.Client,
    conversation_id: str,
    state: _ChatState,
    *,
    post_url: str,
    post_json: dict[str, Any],
) -> None:
    """One turn-starting post: open the stream, wait for `: connected`, post
    `post_json` to `post_url`, then print events until `done` (D14). Used
    for a plain-text message, the `resume: step_up` turn (`/otp`) and a
    confirmation decision (`/confirm`, `/cancel`) alike (D18) -- only
    `/replay` bypasses this, since it opens no stream. A `409` means another
    turn already holds this conversation's lock -- print `turn in progress`
    and stop, without posting anything else for this line.
    """
    stream_url = f"{_API_PREFIX}/conversations/{conversation_id}/stream"

    with client.stream("GET", stream_url) as response:
        lines = response.iter_lines()
        for line in lines:
            if line == _CONNECTED_LINE:
                break

        post_response = client.post(post_url, json=post_json, headers=_csrf_headers(client))
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
                if event is not None and _handle_event(event, data, state):
                    return
                event = None
            # A blank frame separator or an `: ping` keep-alive comment
            # carries no data; only `event:`/`data:` lines matter here.


def _response_detail(response: httpx.Response) -> Any:
    """The `detail` field of a JSON error/response body, or `None` if the
    body isn't JSON or carries no `detail` (a success body, e.g.).
    """
    try:
        body = response.json()
    except ValueError:
        return None
    return body.get("detail") if isinstance(body, dict) else None


def _run_otp(client: httpx.Client, conversation_id: str, state: _ChatState, code: str) -> None:
    """`/otp <code>`: verify the code and print only the status and
    `detail` -- never the code itself. On `200` the session is stepped up,
    so this runs the `resume: step_up` turn to let the paused flow continue
    (D6, D18).
    """
    response = client.post(
        f"{_API_PREFIX}/auth/otp/verify",
        json={"code": code},
        headers=_csrf_headers(client),
    )
    print(f"otp {response.status_code} {_response_detail(response)}")
    if response.status_code == 200:
        _run_turn(
            client,
            conversation_id,
            state,
            post_url=f"{_API_PREFIX}/conversations/{conversation_id}/messages",
            post_json={"resume": "step_up"},
        )


def _run_confirmation(
    client: httpx.Client, conversation_id: str, state: _ChatState, decision: str
) -> None:
    """`/confirm` or `/cancel`: post `decision` for the last `ui.confirm`
    token seen (D7). Prints `no open confirmation` if none has arrived yet.
    """
    token_id = state.last_confirm_token
    if token_id is None:
        print("no open confirmation")
        return
    state.last_posted_token = token_id
    _run_turn(
        client,
        conversation_id,
        state,
        post_url=f"{_API_PREFIX}/conversations/{conversation_id}/confirmations/{token_id}",
        post_json={"decision": decision},
    )


def _run_pick(client: httpx.Client, conversation_id: str, state: _ChatState, indices: str) -> None:
    """`/pick <n[,n...]>` (D4-B D7): map 1-based indices into
    `state.last_tx_options` and post `{"selection": {"tx_ids": [...]}}`,
    running the turn like a typed message. Prints `no open transaction
    list` if no `ui.transaction_list` has arrived yet, or `invalid pick`
    for a non-numeric or out-of-range index -- the route's own D7 gate is
    the actual guard against an id that was never offered (R1); this is
    just a convenience for reading a valid index off what was just printed.
    """
    if state.last_tx_options is None:
        print("no open transaction list")
        return
    try:
        picked = [int(piece.strip()) for piece in indices.split(",") if piece.strip()]
        tx_ids = [state.last_tx_options[index - 1] for index in picked]
    except (ValueError, IndexError):
        print("invalid pick")
        return
    _run_turn(
        client,
        conversation_id,
        state,
        post_url=f"{_API_PREFIX}/conversations/{conversation_id}/messages",
        post_json={"selection": {"tx_ids": tx_ids}},
    )


def _replay(client: httpx.Client, conversation_id: str, state: _ChatState) -> None:
    """`/replay`: re-post the last token this script posted to the
    confirmations route, with `{"decision": "confirm"}`, and print the raw
    result -- no stream, since the token is expected to be rejected (R2).
    """
    token_id = state.last_posted_token
    if token_id is None:
        print("no open confirmation")
        return
    response = client.post(
        f"{_API_PREFIX}/conversations/{conversation_id}/confirmations/{token_id}",
        json={"decision": "confirm"},
        headers=_csrf_headers(client),
    )
    print(f"replay -> {response.status_code} {_response_detail(response)}")


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
        state = _ChatState()
        messages_url = f"{_API_PREFIX}/conversations/{conversation_id}/messages"

        for line in sys.stdin:
            text = line.rstrip("\n")
            if not text:
                continue
            if text.startswith("/otp "):
                _run_otp(client, conversation_id, state, text[len("/otp ") :].strip())
            elif text == "/confirm":
                _run_confirmation(client, conversation_id, state, "confirm")
            elif text == "/cancel":
                _run_confirmation(client, conversation_id, state, "cancel")
            elif text == "/replay":
                _replay(client, conversation_id, state)
            elif text.startswith("/pick "):
                _run_pick(client, conversation_id, state, text[len("/pick ") :].strip())
            else:
                _run_turn(
                    client, conversation_id, state, post_url=messages_url, post_json={"text": text}
                )


if __name__ == "__main__":
    main()
