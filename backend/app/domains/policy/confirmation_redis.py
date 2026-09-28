"""`RedisConfirmationStore`: the `ConfirmationStore` contract (`04` §7, D8)
backed by Redis, replacing `InMemoryConfirmationStore` on the API path.

Bound to one customer + conversation at construction (R1), same as the
Protocol it implements structurally. It stores each plan as `conf:<id>` ->
JSON `{conversation_id, customer_id, steps: [{tool, args_hash}], cursor,
expires_at}` with a 300 s TTL (`EX`), and consumes a step with one Lua
script so the ownership check, the step-at-cursor check and the cursor
advance are atomic (D8: replacing a plain `GETDEL`). `args_hash` is computed
in Python (`policy.confirmation.args_hash`) and passed in as a plain string;
the script only ever compares opaque strings, never reimplements hashing.

Imports only the stdlib, pydantic (via `policy.confirmation`) and
`app.core.*` (`06` §2): this module must never import
`app.domains.conversation`.
"""

import json
import secrets
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from redis.exceptions import RedisError, ResponseError

from app.core.errors import ConfirmationRequired, ToolUnavailable
from app.core.redis import get_redis
from app.domains.policy.confirmation import ConfirmationPlan, PlanStep, ToolArgs, args_hash

__all__ = ["RedisConfirmationStore"]

_TTL = timedelta(minutes=5)
_TTL_SECONDS = int(_TTL.total_seconds())
_KEY_PREFIX = "conf:"

# One atomic check-and-advance (D8): `KEYS[1]` is `conf:<token_id>`, `ARGV`
# is `[customer_id, conversation_id, tool, args_hash]`. A Lua table returned
# with a single `err` field becomes a Redis error reply whose message is
# exactly that string (Redis scripting convention), so the Python side maps
# it back to a `ConfirmationRequired` reason without parsing free text.
_CONSUME_STEP_SCRIPT = """
local raw = redis.call('GET', KEYS[1])
if not raw then
  return {err = 'unknown_or_expired'}
end
local plan = cjson.decode(raw)
if plan.customer_id ~= ARGV[1] or plan.conversation_id ~= ARGV[2] then
  return {err = 'wrong_owner'}
end
local cursor = plan.cursor
local step = plan.steps[cursor + 1]
if step == nil or step.tool ~= ARGV[3] or step.args_hash ~= ARGV[4] then
  return {err = 'step_mismatch'}
end
plan.cursor = cursor + 1
if plan.cursor >= #plan.steps then
  redis.call('DEL', KEYS[1])
else
  redis.call('SET', KEYS[1], cjson.encode(plan), 'KEEPTTL')
end
return cursor
"""


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _key(token_id: str) -> str:
    return f"{_KEY_PREFIX}{token_id}"


class RedisConfirmationStore:
    """A `ConfirmationStore` backed by Redis (structural, D8/`04` §7)."""

    def __init__(self, customer_id: str, conversation_id: str) -> None:
        self._customer_id = customer_id
        self._conversation_id = conversation_id

    async def issue(self, steps: Sequence[PlanStep]) -> ConfirmationPlan:
        token_id = secrets.token_urlsafe(32)
        expires_at = _utcnow() + _TTL
        payload = {
            "conversation_id": self._conversation_id,
            "customer_id": self._customer_id,
            "steps": [
                {"tool": step.tool, "args_hash": args_hash(step.tool, step.args)} for step in steps
            ],
            "cursor": 0,
            "expires_at": expires_at.isoformat(),
        }
        try:
            await get_redis().set(_key(token_id), json.dumps(payload), ex=_TTL_SECONDS)
        except RedisError as exc:
            raise ToolUnavailable("confirmation store unavailable") from exc
        return ConfirmationPlan(token_id=token_id, steps=list(steps), expires_at=expires_at)

    async def consume_step(self, token_id: str, tool: str, args: ToolArgs) -> int:
        hashed = args_hash(tool, args)
        try:
            result = await get_redis().eval(
                _CONSUME_STEP_SCRIPT,
                1,
                _key(token_id),
                self._customer_id,
                self._conversation_id,
                tool,
                hashed,
            )
        except ResponseError as exc:
            reason = str(exc)
            if reason == "unknown_or_expired":
                raise ConfirmationRequired("unknown_or_expired") from exc
            if reason == "wrong_owner":
                raise ConfirmationRequired("wrong_owner") from exc
            if reason == "step_mismatch":
                raise ConfirmationRequired("step_mismatch") from exc
            raise ToolUnavailable("confirmation store unavailable") from exc
        except RedisError as exc:
            raise ToolUnavailable("confirmation store unavailable") from exc
        return int(result)

    async def cancel(self, token_id: str) -> None:
        try:
            await get_redis().delete(_key(token_id))
        except RedisError as exc:
            raise ToolUnavailable("confirmation store unavailable") from exc

    async def is_open(self, token_id: str) -> bool:
        try:
            raw = await get_redis().get(_key(token_id))
        except RedisError as exc:
            raise ToolUnavailable("confirmation store unavailable") from exc
        if raw is None:
            return False
        plan = json.loads(raw)
        return bool(
            plan.get("customer_id") == self._customer_id
            and plan.get("conversation_id") == self._conversation_id
        )
