"""The checkpointer's msgpack serde is strict and covers every checkpointed model."""

from typing import get_args, get_type_hints

from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel

from app.domains.conversation.graph import GraphState
from app.domains.conversation.hosting import CHECKPOINT_TYPES, checkpoint_serde
from app.domains.conversation.ui import (
    CardPickerEvent,
    CardPickerPayload,
    HandoffBannerEvent,
    HandoffBannerPayload,
    PickerOption,
    UIEvent,
)


def _state_models() -> set[type]:
    found: set[type] = set()

    def walk(annotation: object) -> None:
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            found.add(annotation)
        for arg in get_args(annotation):
            walk(arg)

    for annotation in get_type_hints(GraphState, include_extras=True).values():
        walk(annotation)
    return found


def test_serde_allowlist_is_strict_and_complete() -> None:
    allowed = checkpoint_serde()._allowed_msgpack_modules
    assert isinstance(allowed, (set, frozenset))
    ui_members = set(get_args(get_args(UIEvent)[0]))
    assert ui_members
    for model in ui_members | _state_models():
        assert (model.__module__, model.__qualname__) in allowed, model
    assert set(CHECKPOINT_TYPES) >= ui_members


def test_checkpoint_round_trips_typed_models() -> None:
    serde = checkpoint_serde()
    saver = MemorySaver(serde=serde)
    ui = [
        HandoffBannerEvent(
            kind="handoff_banner",
            payload=HandoffBannerPayload(
                handoff_id="h1", reference="R-1", queue="atencion", queue_label="Atención"
            ),
        ),
        CardPickerEvent(
            kind="card_picker",
            payload=CardPickerPayload(options=[PickerOption(label="Visa 1234")]),
        ),
    ]
    restored = saver.serde.loads_typed(saver.serde.dumps_typed({"ui": ui}))["ui"]
    assert [type(e) for e in restored] == [HandoffBannerEvent, CardPickerEvent]
