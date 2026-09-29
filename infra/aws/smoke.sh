#!/usr/bin/env bash
# Prod smoke test over HTTPS: bash infra/aws/smoke.sh HOST
# Needs SMOKE_DOC_TYPE, SMOKE_DOC, SMOKE_PASSWORD, SMOKE_STAFF_USER, SMOKE_STAFF_PASSWORD
# in the environment. Never prints them.
set -euo pipefail

HOST="${1:?usage: smoke.sh HOST}"
BASE="https://$HOST/api/v1"
JAR="$(mktemp)"
trap 'rm -f "$JAR" "$JAR.staff"' EXIT
fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }

code="$(curl -s -o /dev/null -w '%{http_code}' "$BASE/health")"
[ "$code" = 200 ] || fail "health returned $code"
echo "ok health"

body="$(jq -n --arg t "${SMOKE_DOC_TYPE:?}" --arg d "${SMOKE_DOC:?}" --arg p "${SMOKE_PASSWORD:?}" \
  '{document_type:$t,document_number:$d,password:$p}')"
code="$(curl -s -o /dev/null -w '%{http_code}' -c "$JAR" -H 'Content-Type: application/json' \
  -d "$body" "$BASE/auth/login")"
[ "$code" = 200 ] || fail "persona login returned $code"
echo "ok persona login"

csrf="$(awk '$6=="csrf_token"{print $7}' "$JAR")"
[ -n "$csrf" ] || fail "no csrf cookie"

conv="$(curl -s -b "$JAR" -H "X-CSRF-Token: $csrf" -H 'Content-Type: application/json' \
  -d '{"language":"es"}' "$BASE/conversations" | jq -r .conversation_id)"
[ -n "$conv" ] && [ "$conv" != null ] || fail "conversation not created"

# Open the stream first (D14), then post the turn; wait for `done`.
STREAM_OUT="$(mktemp)"
trap 'rm -f "$JAR" "$JAR.staff" "$STREAM_OUT"' EXIT
curl -sN --max-time 90 -b "$JAR" "$BASE/conversations/$conv/stream" > "$STREAM_OUT" &
stream_pid=$!
for _ in $(seq 1 20); do grep -q ': connected' "$STREAM_OUT" && break; sleep 0.5; done
code="$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" -H "X-CSRF-Token: $csrf" \
  -H 'Content-Type: application/json' -d '{"text":"Hola, ¿cuál es el estado de mi tarjeta?"}' \
  "$BASE/conversations/$conv/messages")"
[ "$code" = 202 ] || fail "post message returned $code"
for _ in $(seq 1 180); do grep -q '^event: done' "$STREAM_OUT" && break; sleep 0.5; done
kill "$stream_pid" 2>/dev/null || true
grep -q '^event: done' "$STREAM_OUT" || fail "chat turn did not reach done"
echo "ok chat turn streamed to done"

code="$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
  -d '{}' "$BASE/test-idp/sessions")"
[ "$code" = 404 ] || fail "test-idp returned $code (want 404)"
echo "ok test-idp closed"

body="$(jq -n --arg u "${SMOKE_STAFF_USER:?}" --arg p "${SMOKE_STAFF_PASSWORD:?}" \
  '{username:$u,password:$p}')"
code="$(curl -s -o /dev/null -w '%{http_code}' -c "$JAR.staff" -H 'Content-Type: application/json' \
  -d "$body" "$BASE/auth/staff/login")"
[ "$code" = 200 ] || fail "staff login returned $code"
echo "ok staff login"
echo "SMOKE PASS"
