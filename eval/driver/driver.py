"""The B2 scripted HTTP driver (spec "Contracts" -> "B2: driver", D8-D10):
plays one `Case`'s turns against a running conversation API and returns a
raw `Transcript`, with no interpretation -- A3 derives every pass/fail check
from the transcript plus the DB clone (D9). It never reads the DB itself.

Per-turn shape mirrors `backend/scripts/chat_api.py`'s `_run_turn`/
`_run_otp`/`_run_confirmation`/`_run_pick` (mirror, not import: this module
runs outside `backend/app`, under the repo-root `eval` package, and the two
tools have different jobs -- that one is an interactive human REPL, this one
is a scripted batch runner with no stdin): open `GET .../stream`, wait for
`: connected`, then POST the turn, then collect `event:` frames until
`done`. The CSRF header comes from the `csrf_token` cookie `POST
/test-idp/sessions` sets (same shape `auth.py`'s login sets, `04` §3 "Auth
(ADR-025)"); that route itself is the one exception to R1's "no `customer_id`
argument" rule (eval-only, `test_idp.py`).

`confirm`/`cancel` resolve against the token of the last `ui.confirm` event
this run has seen; `select` needs a `ui.transaction_list` to have been
offered at some point. Neither replays server-side validation (R1/R2 are the
API's job, not this script's) -- an unmet precondition just ends the
transcript with `error`, the same way a real client with stale UI state
would get a `409` and give up.

D8/D9 session-expiry replay: for `setup.expire_session_before_turn: N` (the
same 0-based index as `enumerate(case.turns)`), `play_turn` drops the
`session`/`csrf_token` cookies right before turn N is attempted, so its
first request -- the stream GET or the POST, whichever the turn sends first
-- gets `401`. The driver then re-mints a session for the same persona
(`POST /test-idp/sessions`) and calls `GET /auth/me`; if `login_hint` and
`display_name` match the identity captured when the run's session first
opened, the turn is replayed exactly once (stream reopened, then POST). A
mismatch ends the transcript `error` (`identity_mismatch`) with nothing
resent; a second `401` on the replay ends it `error` (`session_expired`).
This module's own `RunnerState`, `open_session`, `play_turn`,
`ended_by_from_events` and `is_not_runnable` are public so a second driver
(the simulator, B3) can reuse them by import rather than by copy.
"""

import asyncio
import json
import time
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict

from eval.scenarios.schema import Case, Turn

__all__ = [
    "EventRecord",
    "RunnerState",
    "Transcript",
    "TurnInput",
    "TurnRecord",
    "ended_by_from_events",
    "is_not_runnable",
    "open_session",
    "play_turn",
    "run_case",
]

_API_PREFIX = "/api/v1"
_CONNECTED_LINE = ": connected"
_TURN_TIMEOUT_SECONDS = 60.0

TurnKind = Literal["say", "confirm", "cancel", "otp", "select"]
EndedBy = Literal["done", "handoff", "closed", "error", "max_turns", "not_runnable"]


class _TurnTimeout(Exception):
    """A turn's stream produced no `done` within `_TURN_TIMEOUT_SECONDS`,
    whether the 60 s watchdog (`asyncio.wait_for`) fired first or httpx's own
    per-request timeout did (`httpx.TimeoutException`, e.g. `ReadTimeout`
    while waiting on the SSE stream between events)."""


class _Unauthorized(Exception):
    """One attempt at a turn got `401` on its stream GET or its POST
    (D8/D9). `play_turn` catches this to drive the re-login/compare/replay
    sequence; it never reaches `run_case`."""


class _IdentityMismatch(Exception):
    """The re-login's `GET /auth/me` doesn't match the identity captured
    when the session first opened (D8): the held request is dropped, and
    `run_case` ends the transcript `error` (`identity_mismatch`)."""


class _SessionExpiredAgain(Exception):
    """The one D8/D9 replay attempt also got `401`: `run_case` ends the
    transcript `error` (`session_expired`)."""


class EventRecord(BaseModel):
    """One SSE frame (`04` §3 "SSE events"): the event name and its decoded
    `data` payload, verbatim -- this driver reads `kind`/`token_id`/`mode`
    off `data` but never reshapes it."""

    model_config = ConfigDict(frozen=True)

    event: str
    data: dict[str, Any]


class TurnInput(BaseModel):
    """What this turn sent: the case's own turn kind and the value that
    kind carries (the text, the confirm/cancel/otp flag, or the selected
    tx ids)."""

    model_config = ConfigDict(frozen=True)

    kind: TurnKind
    value: Any


class TurnRecord(BaseModel):
    """One played turn: what was sent, the posting call's status, every SSE
    frame collected before `done` (or before the turn gave up), and how
    long it took."""

    model_config = ConfigDict(frozen=True)

    index: int
    input: TurnInput
    http_status: int
    events: list[EventRecord]
    latency_ms: int


class Transcript(BaseModel):
    """The whole run of one `Case`: every `TurnRecord` played, and why it
    stopped. `conversation_id` is `None` only for `not_runnable` (D10),
    since that case never reaches `POST /conversations`. `stop_reason`
    is set only by the simulator driver (B3, D6): `"goal"`/`"abstention"`
    when its model calls `stop`; this driver never sets it."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    conversation_id: str | None
    turns: list[TurnRecord]
    ended_by: EndedBy
    error: str | None = None
    stop_reason: str | None = None


class RunnerState:
    """Cross-turn bookkeeping this run needs to resolve `confirm`/`cancel`/
    `select` against the last matching `ui.*` event seen (mirrors
    `chat_api.py`'s `_ChatState`), plus the tx ids the simulator (B3) needs
    to build a `select` value from. Never cleared on use: the server, not
    this driver, is the single-use/offer-membership enforcement point
    (R2/R1)."""

    def __init__(self) -> None:
        self.last_confirm_token: str | None = None
        self.tx_list_open = False
        self.last_tx_ids: list[str] = []


def _csrf_headers(client: httpx.AsyncClient) -> dict[str, str]:
    """`X-CSRF-Token` read from the `csrf_token` cookie each call, the same
    convention `chat_api.py`'s `_csrf_headers` uses."""

    token = client.cookies.get("csrf_token")
    return {"X-CSRF-Token": token} if token else {}


def _turn_input(turn: Turn) -> tuple[TurnKind, Any]:
    """The one populated action field on `turn` (`Turn`'s own validator
    guarantees exactly one)."""

    if turn.say is not None:
        return "say", turn.say
    if turn.confirm is not None:
        return "confirm", turn.confirm
    if turn.cancel is not None:
        return "cancel", turn.cancel
    if turn.otp is not None:
        return "otp", turn.otp
    if turn.select is not None:
        return "select", turn.select
    raise AssertionError("Turn has no populated action field; schema validation prevents this")


def _update_state(state: RunnerState, event: str, data: dict[str, Any]) -> None:
    if event == "ui" and data.get("kind") == "confirm":
        state.last_confirm_token = data["payload"]["token_id"]
    elif event == "ui" and data.get("kind") == "transaction_list":
        state.tx_list_open = True
        state.last_tx_ids = [option["tx_id"] for option in data["payload"]["options"]]


def ended_by_from_events(events: list[EventRecord]) -> Literal["handoff", "closed"] | None:
    """A `mode{human}` or `ui.conversation_closed` frame anywhere in a
    turn's events ends the whole transcript, not just that turn."""

    for record in events:
        if record.event == "mode" and record.data.get("mode") == "human":
            return "handoff"
        if record.event == "ui" and record.data.get("kind") == "conversation_closed":
            return "closed"
    return None


async def _post_and_collect_inner(
    client: httpx.AsyncClient,
    conversation_id: str,
    state: RunnerState,
    *,
    post_url: str,
    post_json: dict[str, Any],
) -> tuple[int, list[EventRecord]]:
    stream_url = f"{_API_PREFIX}/conversations/{conversation_id}/stream"
    events: list[EventRecord] = []

    async with client.stream("GET", stream_url) as response:
        if response.status_code == 401:
            # D8/D9: the stream open itself is the first request this turn
            # sends when the cookies were dropped before it -- caught here,
            # never a `done`-less transcript.
            raise _Unauthorized
        lines = response.aiter_lines()
        async for line in lines:
            if line == _CONNECTED_LINE:
                break

        post_response = await client.post(post_url, json=post_json, headers=_csrf_headers(client))
        if post_response.status_code == 401:
            raise _Unauthorized

        current_event: str | None = None
        async for line in lines:
            if line.startswith("event: "):
                current_event = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
                if current_event is not None:
                    events.append(EventRecord(event=current_event, data=data))
                    _update_state(state, current_event, data)
                    if current_event == "done":
                        current_event = None
                        break
                current_event = None
            # A blank frame separator or an `: ping` comment carries no
            # data; only `event:`/`data:` lines matter here.

    return post_response.status_code, events


async def _post_and_collect(
    client: httpx.AsyncClient,
    conversation_id: str,
    state: RunnerState,
    *,
    post_url: str,
    post_json: dict[str, Any],
) -> tuple[int, list[EventRecord]]:
    try:
        return await asyncio.wait_for(
            _post_and_collect_inner(
                client, conversation_id, state, post_url=post_url, post_json=post_json
            ),
            timeout=_TURN_TIMEOUT_SECONDS,
        )
    except (TimeoutError, httpx.TimeoutException) as exc:
        raise _TurnTimeout from exc


async def open_session(client: httpx.AsyncClient, persona: str) -> dict[str, Any]:
    """Test-IdP login for `persona` (D8's "logs in again", and the run's
    initial login): `POST /test-idp/sessions` sets the fresh
    `session`/`csrf_token` cookies on `client` (`test_idp.py`) and returns
    the `MeResponse` JSON body -- the same shape `GET /auth/me` returns, so
    it doubles as the identity captured when a session first opens."""

    response = await client.post(f"{_API_PREFIX}/test-idp/sessions", json={"customer_id": persona})
    response.raise_for_status()
    return dict(response.json())


async def _attempt_turn(
    client: httpx.AsyncClient,
    conversation_id: str,
    kind: TurnKind,
    value: Any,
    state: RunnerState,
    *,
    otp_code: str,
) -> tuple[int, list[EventRecord]]:
    """One try at playing the turn, with no session-expiry handling: raises
    `_Unauthorized` the moment either its stream GET or its POST gets
    `401`. `play_turn` is the D8/D9-aware wrapper around this."""

    messages_url = f"{_API_PREFIX}/conversations/{conversation_id}/messages"

    if kind == "say":
        return await _post_and_collect(
            client, conversation_id, state, post_url=messages_url, post_json={"text": value}
        )
    if kind == "select":
        return await _post_and_collect(
            client,
            conversation_id,
            state,
            post_url=messages_url,
            post_json={"selection": {"tx_ids": value}},
        )
    if kind == "otp":
        verify_response = await client.post(
            f"{_API_PREFIX}/auth/otp/verify",
            json={"code": otp_code},
            headers=_csrf_headers(client),
        )
        if verify_response.status_code == 401:
            raise _Unauthorized
        if verify_response.status_code != 200:
            return verify_response.status_code, []
        return await _post_and_collect(
            client,
            conversation_id,
            state,
            post_url=messages_url,
            post_json={"resume": "step_up"},
        )

    # confirm / cancel: the last `ui.confirm` token seen (checked by the
    # caller before this is reached).
    decision = "confirm" if kind == "confirm" else "cancel"
    confirm_url = (
        f"{_API_PREFIX}/conversations/{conversation_id}/confirmations/{state.last_confirm_token}"
    )
    return await _post_and_collect(
        client, conversation_id, state, post_url=confirm_url, post_json={"decision": decision}
    )


async def play_turn(
    client: httpx.AsyncClient,
    conversation_id: str,
    kind: TurnKind,
    value: Any,
    state: RunnerState,
    *,
    otp_code: str,
    persona: str,
    identity: dict[str, Any],
    expire_first: bool,
) -> tuple[int, list[EventRecord]]:
    """Play one turn, replaying once per D8/D9 after a session-expiry
    `401`.

    `expire_first` is `setup.expire_session_before_turn == index` (the
    caller's job to compute): when set, the `session`/`csrf_token` cookies
    are dropped before this turn is attempted at all, so its first request
    gets `401`. Either way -- expired on purpose or hit some other way --
    a `401` from `_attempt_turn` triggers the D8 sequence: re-mint a
    session for `persona`, call `GET /auth/me`, and compare its
    `login_hint`/`display_name` against `identity` (the identity captured
    when the run's session first opened). A match replays the turn exactly
    once (raises `_SessionExpiredAgain` on a second `401`); a mismatch
    raises `_IdentityMismatch` with nothing resent. Both exceptions are
    `run_case`'s to turn into the transcript's terminal `error`.
    """

    if expire_first:
        client.cookies.delete("session")
        client.cookies.delete("csrf_token")

    try:
        return await _attempt_turn(client, conversation_id, kind, value, state, otp_code=otp_code)
    except _Unauthorized:
        pass

    await open_session(client, persona)
    me_response = await client.get(f"{_API_PREFIX}/auth/me")
    me_response.raise_for_status()
    me = me_response.json()
    if me.get("login_hint") != identity.get("login_hint") or me.get("display_name") != identity.get(
        "display_name"
    ):
        raise _IdentityMismatch

    try:
        return await _attempt_turn(client, conversation_id, kind, value, state, otp_code=otp_code)
    except _Unauthorized as exc:
        raise _SessionExpiredAgain from exc


async def _run_case(
    case: Case, client: httpx.AsyncClient, *, otp_code: str, max_turns: int
) -> Transcript:
    state = RunnerState()
    identity = await open_session(client, case.persona)

    create_response = await client.post(
        f"{_API_PREFIX}/conversations", json={}, headers=_csrf_headers(client)
    )
    create_response.raise_for_status()
    conversation_id = str(create_response.json()["conversation_id"])

    records: list[TurnRecord] = []
    for index, turn in enumerate(case.turns):
        if index >= max_turns:
            return Transcript(
                case_id=case.case_id,
                conversation_id=conversation_id,
                turns=records,
                ended_by="max_turns",
            )

        kind, value = _turn_input(turn)

        if kind in ("confirm", "cancel") and state.last_confirm_token is None:
            return Transcript(
                case_id=case.case_id,
                conversation_id=conversation_id,
                turns=records,
                ended_by="error",
                error="no_open_confirmation",
            )
        if kind == "select" and not state.tx_list_open:
            return Transcript(
                case_id=case.case_id,
                conversation_id=conversation_id,
                turns=records,
                ended_by="error",
                error="no_open_selection",
            )

        started = time.monotonic()
        try:
            http_status, events = await play_turn(
                client,
                conversation_id,
                kind,
                value,
                state,
                otp_code=otp_code,
                persona=case.persona,
                identity=identity,
                expire_first=index == case.setup.expire_session_before_turn,
            )
        except _TurnTimeout:
            return Transcript(
                case_id=case.case_id,
                conversation_id=conversation_id,
                turns=records,
                ended_by="error",
                error="timeout",
            )
        except _IdentityMismatch:
            return Transcript(
                case_id=case.case_id,
                conversation_id=conversation_id,
                turns=records,
                ended_by="error",
                error="identity_mismatch",
            )
        except _SessionExpiredAgain:
            return Transcript(
                case_id=case.case_id,
                conversation_id=conversation_id,
                turns=records,
                ended_by="error",
                error="session_expired",
            )
        latency_ms = int((time.monotonic() - started) * 1000)

        records.append(
            TurnRecord(
                index=index,
                input=TurnInput(kind=kind, value=value),
                http_status=http_status,
                events=events,
                latency_ms=latency_ms,
            )
        )

        ended_by = ended_by_from_events(events)
        if ended_by is not None:
            return Transcript(
                case_id=case.case_id,
                conversation_id=conversation_id,
                turns=records,
                ended_by=ended_by,
            )

    return Transcript(
        case_id=case.case_id, conversation_id=conversation_id, turns=records, ended_by="done"
    )


def is_not_runnable(case: Case) -> bool:
    """`True` only for a non-empty `case.setup.faults` (D10): those
    fault-injection hooks aren't implemented by any driver yet, so the case
    never reaches the API. `expire_session_before_turn` is not one of these
    any more -- both drivers play it, per D8/D9."""

    return bool(case.setup.faults)


async def run_case(
    case: Case,
    *,
    base_url: str,
    otp_code: str,
    client: httpx.AsyncClient | None = None,
    max_turns: int = 12,
) -> Transcript:
    """Play `case` against `base_url` and return its `Transcript`.

    A non-empty `case.setup.faults` (`is_not_runnable`) returns
    `not_runnable` before any HTTP call is made (D10) -- a fault-injection
    hook no driver implements yet. A set `case.setup.expire_session_before_turn`
    is played, not skipped: `_run_case` drops the session cookies before
    that turn and replays per D8/D9.

    `client` lets a caller (a test, or a future runner amortizing
    connections across cases) supply its own `httpx.AsyncClient`; this
    function only opens and closes one of its own when `client` is `None`,
    with its timeout set to the per-turn budget (`_TURN_TIMEOUT_SECONDS`),
    not httpx's 5 s default -- the SSE stream can go tens of seconds
    between frames without that being a failure.
    """

    if is_not_runnable(case):
        return Transcript(
            case_id=case.case_id, conversation_id=None, turns=[], ended_by="not_runnable"
        )

    owns_client = client is None
    http_client = (
        client
        if client is not None
        else httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(_TURN_TIMEOUT_SECONDS))
    )
    try:
        return await _run_case(case, http_client, otp_code=otp_code, max_turns=max_turns)
    finally:
        if owns_client:
            await http_client.aclose()
