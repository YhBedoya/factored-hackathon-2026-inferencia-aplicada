"""Streamlit test page for the sandbox (T14, `07` D1 end-of-day step 4).

    cd backend && uv run streamlit run scripts/sandbox_ui.py

A thin UI over the same session-building code the CLI uses
(`build_sandbox_session` in `app.domains.conversation.sandbox`). The sidebar
picks the customer -- a persona from `eval/personas.yaml` or a free-text
customer id -- and that is the *only* source of `customer_id` (R1); nothing
typed in the chat box is ever read as one. Each chat turn runs through
`run_turn`, and the reply is followed by an expander with that turn's
`DebugInfo` (language, status, intents, slots, route, tools called).

`streamlit run` puts `scripts/` on `sys.path`, not `backend/`; the same fix
`scripts/nlu_smoke.py` uses (insert `backend/` before importing `app.*`)
runs here first.
"""

import asyncio
import sys
from pathlib import Path
from typing import Any

import streamlit as st
import yaml

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.core.llm import LLMSettings  # noqa: E402
from app.domains.conversation.graph import run_turn  # noqa: E402
from app.domains.conversation.sandbox import build_sandbox_session  # noqa: E402

_REPO_ROOT = _BACKEND_ROOT.parent
_PERSONAS_FILE = _REPO_ROOT / "eval" / "personas.yaml"
_DATA_DIR = _REPO_ROOT / "data"

# `07` D1 end-of-day step 4, verbatim.
_EOD_UTTERANCES = [
    "hola, ¿cuál es el estado de mi tarjeta?",
    "la de crédito",
    "qual é o status do meu cartão?",
    "¿me podés decir si mi tarjeta está activa?",
    "quiero pagar con Pix",
]

_FREE_TEXT_CHOICE = "(free text)"


def _load_personas() -> list[dict[str, Any]]:
    raw = yaml.safe_load(_PERSONAS_FILE.read_text(encoding="utf-8"))
    personas = raw.get("personas") if isinstance(raw, dict) else None
    return list(personas) if isinstance(personas, list) else []


def _persona_label(persona: dict[str, Any]) -> str:
    """`id + traits` per the acceptance line -- no other persona field is shown."""
    kinds = "/".join(persona.get("card_kinds", []))
    blocked = ", blocked" if persona.get("blocked") else ""
    country, count = persona["country"], persona["card_count"]
    return f"{persona['customer_id']} ({country}, {count} {kinds}{blocked})"


def _missing_prereqs() -> str | None:
    """A clear error if `data/` or the API key is missing, else `None`."""
    if not _DATA_DIR.is_dir():
        return (
            f"`{_DATA_DIR}` not found. This page reads the real bank data, same as the CLI "
            "sandbox (see `CLAUDE.md`); it will not fall back to the test fixture."
        )
    settings = LLMSettings()
    if settings.llm_provider == "anthropic" and settings.anthropic_api_key is None:
        return (
            "`ANTHROPIC_API_KEY` is not set. Add it to the repo-root `.env` (see `.env.example`)."
        )
    if settings.llm_provider == "bedrock" and settings.aws_region is None:
        return "`AWS_REGION` is not set for the `bedrock` provider."
    return None


def _event_loop() -> asyncio.AbstractEventLoop:
    """One event loop for the whole browser session, not a fresh one per turn.

    `asyncio.run` opens and closes a loop on every call; the provider's async
    HTTP client binds its transport to whichever loop it first ran on, so a
    second turn on a *different*, closed loop would break it. Keeping one
    loop in `st.session_state` means every rerun of this script reuses it.
    """
    loop = st.session_state.get("event_loop")
    if loop is None:
        loop = asyncio.new_event_loop()
        st.session_state.event_loop = loop
    return loop


def _start_conversation(customer_id: str) -> None:
    """New `conversation_id`, new `MemorySaver` thread (T14 acceptance)."""
    graph, config, bank_tools = build_sandbox_session(customer_id, _DATA_DIR)
    st.session_state.customer_id = customer_id
    st.session_state.graph = graph
    st.session_state.config = config
    st.session_state.bank_tools = bank_tools
    st.session_state.messages = []


def _send(text: str) -> None:
    st.session_state.messages.append(("user", text, None))
    loop = _event_loop()
    st.session_state.bank_tools.calls.clear()
    reply, debug = loop.run_until_complete(
        run_turn(st.session_state.graph, text, config=st.session_state.config)
    )
    st.session_state.messages.append(("assistant", reply, debug))


def _render_sidebar(personas: list[dict[str, Any]]) -> str:
    with st.sidebar:
        st.header("Session")
        labels = [_persona_label(p) for p in personas]
        choice = st.selectbox("Persona", [_FREE_TEXT_CHOICE, *labels])
        if choice == _FREE_TEXT_CHOICE:
            previous = st.session_state.get("customer_id", "")
            customer_id = st.text_input("Customer id", value=previous)
        else:
            customer_id = str(personas[labels.index(choice)]["customer_id"])

        new_clicked = st.button("New conversation")
        changed = customer_id and customer_id != st.session_state.get("customer_id")
        if customer_id and (new_clicked or changed or "graph" not in st.session_state):
            _start_conversation(customer_id)
    return customer_id


def _render_history() -> None:
    for role, text, debug in st.session_state.get("messages", []):
        with st.chat_message(role):
            st.write(text)
            if debug is not None:
                with st.expander("debug"):
                    st.json(debug.model_dump())


def _render_eod_buttons() -> str | None:
    st.caption("End-of-day utterances (`07` D1 step 4)")
    clicked: str | None = None
    for col, utterance in zip(st.columns(len(_EOD_UTTERANCES)), _EOD_UTTERANCES, strict=True):
        if col.button(utterance, key=f"eod-{utterance}"):
            clicked = utterance
    return clicked


def main() -> None:
    st.set_page_config(page_title="Card-support sandbox")
    st.title("Card-support sandbox")

    error = _missing_prereqs()
    if error:
        st.error(error)
        return

    customer_id = _render_sidebar(_load_personas())
    if not customer_id or "graph" not in st.session_state:
        st.info("Pick a persona or type a customer id in the sidebar to start.")
        return

    _render_history()
    eod_text = _render_eod_buttons()
    typed_text = st.chat_input("Message")
    text = eod_text or typed_text
    if text:
        _send(text)
        st.rerun()


if __name__ == "__main__":
    main()
