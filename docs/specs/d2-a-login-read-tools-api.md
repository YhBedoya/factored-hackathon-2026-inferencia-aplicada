# Spec: D2-A — login, read tools and hosting the agent (G4)

Card: `07-execution-plan.md` D2, Dev A track, rows A1–A6. Owner: Dev A. Branch `feat/d2-a-login-read-tools-api` → `develop`. The PR touches identity and tools, so Dev B approves it before merge (ADR-018).

## Objective

A persona logs in through the API and asks about their cards. The agent answers from Postgres and streams the reply. The card delivers:
- mock login for every customer (by document type + number), with `/auth/*`, a JWT cookie, CSRF and the `customer` role. There is no staff login on this card (D3)
- the persona catalog, checked against the golden DB
- Postgres read tools behind a registry v0 that binds `customer_id` from the session
- the conversation API with SSE and a Postgres checkpointer
- B's graph hosted with `BANK=postgres`
- `make client` and `make chat-api`

It serves the "Done when" lines of A1–A6 and D2 end-of-day test steps 1–4. Step 5 is B's (sandbox). If A falls behind, `/auth/refresh` and the login rate limit move to D3 (`07` D2 "If behind"). They are built last so they can be cut cleanly. *(Revision 2: neither was cut. Both shipped on this card, T15/T16; see D27.)*

## Decisions

| # | Decision | Why / trace |
|---|---|---|
| D1 | **Customers log in with `document_type` + `document_number` + password, not email.** `document_number` is non-null and unique across all 150,000 customers. The types are AR `DNI`, CO `CC`/`CE`/`Pasaporte`, MX `DNI`. Input is normalized before lookup: trim, drop spaces, dots and dashes, uppercase. Leading zeros are kept. **Amends `03` §6 `identity`, `03` §8 and ADR-008** (done in this spec's PR) | Human Q1. Dataset emails are not unique: 91,289 distinct emails over 147,016 non-null |
| D2 | **`document_number` is PII.** It never appears in plain text in logs, traces, rate-limit keys, audit, `identity.accounts` or API responses. Every account gets a `login_key` = HMAC-SHA256(`IDENTITY_HMAC_KEY`, `"doc:<TYPE>:<NUMBER>"`). The login lookup, the rate-limit key and the log fields use the `login_key` (logs show only its first 12 hex characters). Only the git-ignored export holds the plain number | Human Q1. `06` §4 (never log unmasked PII), R10 |
| D3 | **Amended (revision 1): no staff accounts or staff login on this card.** Login is customer-only. There is no `identity.staff_users` table, no staff seeding, no username login and no `kind` union on the login body. The staff panel will be a separate page with no login for now. How that page is protected is decided on the staff-panel card (D4 handoff; see Open questions). *Replaces the earlier D3 (staff log in with a username), which the human reversed.* | Human revision 1: "the staff panel would not have a login for the moment. The staff panel will be a different page" |
| D4 | Passwords come from a deterministic generator: base32 of HMAC(`CREDENTIALS_SEED`, account key), 12 characters. They are stored as stdlib PBKDF2-SHA256 with a per-account salt and 1,000 iterations, as `pbkdf2_sha256$<iter>$<salt_b64>$<hash_b64>`. No new dependency. The export is `data/secrets/credentials.csv` (git-ignored under `data/`) with columns `customer_id, document_type, document_number, password` | Assumption 2, D3. `03` §8 ("seeded generator, low-cost hash"), R10 |
| D5 | Provisioning (`python -m app.domains.identity.provision`) writes `identity.accounts` (customers only, D3) into `latam_golden`, then `demo-reset` re-clones `latam_app`. `make data` runs it after the load, and `make seed-identity` runs it alone. A rerun is idempotent: it truncates and rewrites. It refuses to run when `CREDENTIALS_SEED` or `IDENTITY_HMAC_KEY` is empty | Assumption 4 as amended by D3. `03` §7 (demo-reset clones golden) |
| D6 | **Session:** HS256 JWT signed with `JWT_SECRET`, in the httpOnly, SameSite=Lax cookie `session` (`Secure` only when `APP_ENV=prod`).<br>• Claims: `sub` (account_id), `role`, `customer_id`, `step_up_at` (null), `jti`, `exp`, with TTL `SESSION_TTL_MINUTES` (default 60).<br>• CSRF double-submit: a readable `csrf_token` cookie plus an `X-CSRF-Token` header, required on every non-GET request except `/auth/login` (and `/test-idp/sessions`).<br>• `get_session()` returns `Session{account_id, role, customer_id, step_up_at}`. `role` is always `"customer"` on this card. It stays because R13 requires every non-public router to declare its role through `require_role(...)`. The `agent`/`admin` roles arrive with the staff panel or `401 session_expired`. It also checks `identity.revoked_tokens`.<br>• Logout revokes the `jti`. Refresh re-issues the token when the current one is valid and not revoked | Assumption 5. ADR-008, ADR-025, R13 |
| D7 | **Login rate limit:** a Redis counter `rl:login:<login_key>`, window `LOGIN_WINDOW_SECONDS` (900), max `LOGIN_MAX_FAILURES` (5). Failures 1–5 return `401 invalid_credentials`. While the counter is at 5 or more, any attempt returns `429 too_many_attempts`, even with the right password. An unknown identifier returns the same 401 and also counts. A success doesn't reset the counter. Values live in Settings | Assumption 6. ADR-023. `07` D2 end-of-day step 1 |
| D8 | `/test-idp/sessions` is mounted only when `APP_ENV=eval` (ADR-025). `APP_ENV` is `dev \| eval \| prod`, default `dev`. `make chat-api PERSONA=<customer_id>` logs in through the real `/auth/login` with the document and password from the export | Assumption 7. ADR-025 |
| D9 | **`/auth/me` is customer-only and returns `MeResponse{role: "customer", login_hint, display_name (first_name only), country (MX/CO/AR), customer_status}`.** Amended (revision 1): it is flat, because the staff variant (`customer: null`) is gone.<br>• `login_hint` is **masked** for customers: `"<document_type> ••••<last 3>"`, for example `"DNI ••••462"`. The bullet count is always 4, so the length of the number doesn't leak. It is formatted in code.<br>• No document number, email, phone, address or last name is ever returned | Human Q5 (masked form picked), revision 1 (customer-only). R4-style formatting in code |
| D10 | **Registry v0:** `conversation/tools/registry.py` builds the `ToolContext` from the route's `Session` + `conversation_id` + `trace_id` (`actor="customer"`, `policy_version="unversioned"` until D3-A1). It then returns the read tools for `BANK=fake\|postgres` (Settings, default `postgres`). Nothing else constructs a `ToolContext` on the API path. No `ToolSpec` or allowlist yet (D3-A1) | Assumption 8. R1, ADR-025, `07` §1 (`BANK=fake\|postgres`) |
| D11 | **Postgres read tools** (`conversation/tools/postgres.py`, `PostgresBank`) implement `BankReadTools` by calling `customers`/`cards`/`transactions` **`service`** modules. `conversation` may not import any `repository` (import-linter). Behavior matches FakeBank: country labels, card kinds, `last4 = right(product_number, 4)`, `search_transactions` returns at most 10 rows, newest first. Every repository query binds the session `customer_id` as a parameter. `CardSummary/CardDetails.locked = False` until `app.card_controls` exists (D3-A3) | Assumption 8. `06` §2, K3 contracts, D1-B D17 |
| D12 | **Refused and logged:**<br>• A foreign `card_id` (in `get_card_details`, or `tx_filter.card_id`) raises `AccessDenied`, found by the same own-row-first, existence-probe-second pattern as FakeBank.<br>• It also writes one structlog warning `tool.access_denied` with fields `tool`, `requested_id` (the opaque `product_id`, never a card number), `conversation_id`, `trace_id`.<br>• An integration test proves it.<br>• In chat (end-of-day step 3), a foreign card number gets `card_select`'s existing "not among your cards" clarification with no tool call.<br>• D3-A5 moves the event to `audit.audit_events` | Human Q4(a) |
| D13 | **API mode has no write tools today:** `config["configurable"]["bank_write_tools"] = None`. **Contract for B:** a flow that reads `bank_write_tools` and finds `None` must route to the safe `fallback`/handoff template, with no confirmation issued and nothing reported as done. This lasts until the D3-A6 pairing | Human Q2(a). R2, R3 |
| D14 | **Conversation API:**<br>• `POST /messages` persists the customer message, takes the turn lock `turn:<conversation_id>` (Redis SET NX, TTL 120 s; if taken, `409 turn_in_progress`) and returns `202{turn_id}`.<br>• It runs the turn as an in-process asyncio task and publishes each event to Redis pub/sub `conv:<conversation_id>`. `GET /stream` subscribes, and clients open the stream before posting.<br>• Events per turn: one `status{step}` per graph node, then a `ui` per `UIEvent`, one `message{role:"bot", text, sources:[]}` with the full reply (no token streaming), `debug` (D15), and finally `done{turn_id}`. On failure the turn emits `error{code}` and then `done`.<br>• The bot message, with its `ui_payload`, is persisted before `done` | Assumption 9. ADR-007, `03` §6 Redis, `04` §3 |
| D15 | A **`debug{language, status, intents, slots, route, tools_called}`** SSE event, emitted only when `APP_ENV != prod`. It has the same fields as the sandbox `DebugInfo`. Documented in `04` §3 (done in this spec's PR) | Human Q6(a) |
| D16 | **Checkpointer:** `AsyncPostgresSaver` (`langgraph-checkpoint-postgres`, psycopg 3 pool, `search_path=langgraph`), `thread_id = conversation_id`, `setup()` at app lifespan start. "A restart loses nothing" means a restart **between** turns. A turn in flight when the process dies is not resumed | Assumption 10. ADR-007, `03` §6 |
| D17 | `app.messages.content` is plain text today. `content_masked` stays NULL until G6b (D5) adds the vault and Fernet | Assumption 11. `03` §6 |
| D18 | `GET /stream` is customer-only today. Agent access arrives with the live-takeover backend (D4 G10), because an agent doesn't own a conversation until a handoff exists | `04` §3 lists `customer, agent`. `07` D4 row A (takeover backend) |
| D19 | **Integration tests run locally only.** They live in `backend/tests/integration/`, run against the `make up` Postgres and Redis, and use a throwaway database `latam_it_<hex>` (created with `alembic upgrade head` and a few invented rows, dropped afterwards) plus Redis keys under a per-run prefix. They skip when Postgres is unreachable. `make test-integration` runs them. They are not in CI and not in `make check` | Human Q3(b) |
| D20 | **Personas:** B's 10 + about 20 more, chosen by query to cover the `03` §8 categories. `eval/personas.yaml` holds `customer_id` + traits only (no PII). The persona test runs each persona's trait predicates against `latam_golden` and is local only (skips when the DB is unreachable) | Human (assumption 12 amended to local). `07` A2, `03` §8, R10 |
| D21 | Secrets `JWT_SECRET`, `IDENTITY_HMAC_KEY`, `CREDENTIALS_SEED` are empty in `.env.example`. `make setup` fills any that are empty in `.env` with `secrets.token_urlsafe(32)`. The app refuses to start when `JWT_SECRET` or `IDENTITY_HMAC_KEY` is empty | R10. D1 end-of-day step 1 (`make setup && make up` on a fresh clone) |
| D22 | **Revision 2 (T5).** The `conversation-no-repository` import-linter contract gets a targeted `ignore_imports` for exactly `app.domains.conversation.tools.postgres -> app.domains.{customers,cards,transactions}.service`, with no `allow_indirect_imports`. Each service reaches its own `repository`, so the static import graph would otherwise flag D11's service calls. The dev compose publishes Redis on `127.0.0.1:6379` for the local integration tests (D19) | Human, mid-card T5. `06` §2 (conversation reaches bank data only through its tools; bank domains talk through `service`) |
| D23 | **Revision 2 (T6).** FastAPI dependencies use the `Annotated[X, Depends(...)]` style | Human, mid-card T6 |
| D24 | **Revision 2 (T12). Amends the Contracts "Dependencies" line and the Touch map:** `get_owned_conversation` lives in the API layer (`backend/app/api/v1/conversations.py`), not in `conversation/deps.py`. The reason is that `identity.deps` → `identity.service` statically reaches `identity.repository`/`customers.repository`, which would break `conversation-no-repository`. Conversation-domain code must not import `identity.deps` or `identity.service`. No new ignore was added. This corrects the ADR-025 file placement, and the decision log is amended to match | Human, mid-card T12. `06` §2, ADR-025 |
| D25 | **Revision 2 (T13).** The eval-only `/test-idp/sessions` router is mounted with `include_router` under `/api/v1`, only when `APP_ENV=eval` (D8). Route-introspection tests (R1, R13) walk routes with `fastapi.routing.iter_route_contexts`, because FastAPI 0.141 doesn't flatten included routers in `app.routes` | Human, mid-card T13. R1, R13 |
| D26 | **Revision 2 (T14).** The live end-of-day step 2 check used ES and PT **card-status** questions, because `balance_due` routes to `unsupported` in D1-B's `nodes/route.py`. Balance routing and formatting are Dev B's D2-B1, so the balance version of step 2 is **pending D2-B1**, not done (Open questions). A live reply showed a negative available credit (`"US$-862.59 disponible"`) for one credit card. That is also D2-B1's ("available credit computed in code") | Human, mid-card T14. `07` D2 row B1 |
| D27 | **Revision 2 (T15/T16). Both shipped, not cut to D3.**<br>• Login rate limit as in D7: `rl:login:<login_key>`, `429 too_many_attempts` once `login_max_failures` is reached, and the counter is not reset on a success.<br>• `POST /auth/refresh`: public (no role dependency) + CSRF. It re-issues the session and CSRF cookies, and the old `jti` is **not** revoked (it expires at its own `exp`).<br>• `make client` was re-run after T16, so `frontend/src/client` includes `/auth/refresh` | Human, mid-card T15/T16. D6, D7 |

## Contracts

Everything not listed here is in `04` (§1 tools, §3 routes, errors and SSE) and is unchanged.

**New dependencies** (`backend/pyproject.toml`): `pyjwt`, `langgraph-checkpoint-postgres`, `psycopg[binary,pool]`. Nothing else.

**Settings** (`core/config.py`): `app_env: Literal["dev","eval","prod"] = "dev"`, `bank: Literal["fake","postgres"] = "postgres"`, `jwt_secret`, `identity_hmac_key`, `credentials_seed`, `session_ttl_minutes = 60`, `login_max_failures = 5`, `login_window_seconds = 900`.

**Migration `0002`** (upgrade and downgrade):
- `identity.accounts(account_id uuid pk, role text not null default 'customer', customer_id text not null unique fk bank.customers, login_key text unique not null, password_hash text not null, status text default 'active', created_at)`. Staff columns are added by the staff-panel card if it needs them
- `identity.revoked_tokens(jti text pk, expires_at timestamptz)`
- `app.conversations(id uuid pk, customer_id text not null, channel text default 'web', language text, mode text default 'bot', status text default 'open', started_at, closed_at)`
- `app.messages(id uuid pk, conversation_id fk, turn_id uuid, role text, content text, content_masked text null, ui_payload jsonb null, created_at)`

**HTTP** (all under `/api/v1`):

| Route | Router role | Body → response |
|---|---|---|
| `POST /auth/login` | public | `{"document_type":"DNI\|CC\|CE\|Pasaporte","document_number":str,"password":str}` → `200 MeResponse` + `session` and `csrf_token` cookies · `401 invalid_credentials` · `429 too_many_attempts` |
| `POST /auth/logout` | any logged-in | → `204`, cookies cleared, `jti` revoked |
| `POST /auth/refresh` | public (no role; needs a valid cookie + CSRF) | → `200 MeResponse`, new cookies. The old `jti` is not revoked (D27) |
| `GET /auth/me` | any logged-in | → `MeResponse` (D9) |
| `POST /test-idp/sessions` | eval only (D8, D25: `include_router` under `/api/v1`) | `{customer_id}` → as login. The one route that takes a `customer_id`, and it is never mounted outside `eval` |
| `POST /conversations` | customer | `{language?: "es"\|"pt"}` → `201 {conversation_id}` |
| `POST /conversations/{id}/messages` | customer + `get_owned_conversation` | `{text: str (1–2000 chars)}` → `202 {turn_id}` · `409 turn_in_progress` |
| `GET /conversations/{id}/stream` | customer + `get_owned_conversation` | SSE, `event:` = the `04` §3 name, `data:` = JSON |

**Dependencies:** `identity/deps.py`: `get_session`, `require_role(*roles)`, `require_csrf`. `get_owned_conversation` (`404 not_found` unless it's the caller's conversation) lives in `backend/app/api/v1/conversations.py` (D24; originally planned for `conversation/deps.py`). Dependencies use `Annotated[X, Depends(...)]` (D23). ADR-025 layout.

**Run config for an API turn** (the K3/D2-K keys, unchanged): `thread_id`, `session` (the registry-built `ToolContext`), `bank_tools`, `llm`, `bank_write_tools = None` (D13).

**SSE `debug`:** `{language, status, intents, slots, route, tools_called}` (D15).

**Doc amendments shipped with this spec:** `03` §6 `identity` and §8 (document login, `login_key`), ADR-008 (amended 2026-09-28), `01` §6 identity bullet, `04` §3 (login body, `MeResponse`, `debug` event).

## Touch map

```
backend/pyproject.toml, uv.lock                         deps (Contracts)
backend/app/core/config.py                              Settings (Contracts)
backend/app/core/events.py                              new: Redis pub/sub publish/subscribe for conv:<id>
backend/app/alembic/versions/0002_identity_conversations.py  new
backend/app/domains/identity/{models,passwords,tokens,deps,service,repository,provision}.py  new (step_up.py untouched)
backend/app/domains/customers/{repository,service}.py   new
backend/app/domains/cards/{repository,service}.py       new
backend/app/domains/transactions/{repository,service}.py new
backend/app/domains/conversation/tools/{registry,postgres}.py  new
backend/app/domains/conversation/{store,hosting,runner}.py new (store, not "repository": import-linter forbids conversation → *.repository). No conversation/deps.py (D24)
backend/.importlinter                                   targeted ignore_imports on conversation-no-repository (D22)
docker/docker-compose.dev.yml                           Redis published on 127.0.0.1:6379 (D22)
backend/app/api/v1/{auth,conversations,test_idp}.py      new; api/v1/__init__.py mounts them (test_idp only when APP_ENV=eval)
backend/app/main.py                                     lifespan: checkpointer pool + setup, compiled graph
backend/scripts/chat_api.py                             new: make chat-api
backend/tests/unit/test_r1_routes.py, test_r13_routes.py, test_login_pii.py   new
backend/tests/integration/{conftest,test_auth,test_r1_postgres_tools,test_r13_ownership,test_restart,test_personas}.py  new
eval/personas.yaml                                      +~20 personas, trait vocabulary
Makefile                                                setup (fill secrets), data (+provision), seed-identity, chat-api, test-integration
.env.example                                            APP_ENV, BANK, JWT_SECRET, IDENTITY_HMAC_KEY, CREDENTIALS_SEED, session/login limits
frontend/src/client/                                    regenerated by make client (never hand-edited)
docs/solution-docs/{01,03,04,decision-log}.md           amendments (Contracts)
```

`flows/`, `nodes/`, `prompts/`, `fakebank.py` and `sandbox.py` are not touched.

## Test list

Fake LLM only (`ScriptedLLM`). Unit tests run in `make check`. Integration tests run with `make test-integration` (D19).

| Test | Proves |
|---|---|
| `unit/test_r1_routes.py::test_no_route_accepts_customer_id` | R1. With `APP_ENV=dev`, no request body, query or path parameter on any mounted route is named `customer_id` (walks routes with `fastapi.routing.iter_route_contexts`, D25, and the body models). `test_idp` isn't mounted, and the test asserts that |
| `unit/test_r13_routes.py::test_every_route_declares_role_and_ownership` | R13. Every route except `/health`, `/auth/login` and `/auth/refresh` carries a `require_role` dependency from its router. Every `/conversations/{id}/…` route depends on `get_owned_conversation` |
| `unit/test_login_pii.py::test_document_number_never_logged_or_keyed` | D2. A failed login (fake Redis, fake repo) produces log records and a rate-limit key that don't contain the document number, and the key equals the HMAC form |
| `integration/test_auth.py::test_me_returns_only_own_masked_profile` | A1 "Done when". Log in → `/me` has the D9 fields, `login_hint` is masked, and the body contains neither the document number nor any other customer's data. Without the cookie → 401 |
| `integration/test_auth.py::test_five_failures_then_429` | End-of-day step 1 (cuttable with D7). Five wrong passwords → 401 ×5, the sixth attempt → 429 |
| `integration/test_r1_postgres_tools.py::test_foreign_card_refused_and_logged` | A3 "Done when" + R1. `PostgresBank` bound to customer A: B's card → `AccessDenied` plus one `tool.access_denied` record with `requested_id`, `conversation_id` and `trace_id`. A's own card → details |
| `integration/test_r13_ownership.py::test_other_customer_conversation_is_404` | R13. Customer B posts to A's conversation and opens its stream → 404 on both |
| `integration/test_restart.py::test_restart_mid_conversation_continues` | A4 "Done when". Turn 1 leaves `card_select` pending ("which card?"). Then the app, pool and saver are rebuilt, and turn 2 ("la de crédito") answers for the credit card, from the checkpoint and messages |
| `integration/test_personas.py::test_personas_match_golden` | A2 "Done when". Each persona's traits hold in `latam_golden` |

A5 and A6 are proven by commands (Success criteria 6–7), not tests.

## Boundaries

- **Always:**
  - Build `ToolContext` only in the registry, from the route's `Session`.
  - Filter every bank query by the bound `customer_id`.
  - Use the HMAC `login_key` wherever a login identifier would be logged or keyed.
  - Keep `/test-idp` off outside `eval`.
  - Put a router-level role on every new router.
  - Regenerate the client instead of editing it.
- **Ask first:**
  - Any dependency beyond the three in Contracts.
  - Any `TurnState`/`GraphState` field.
  - Changing flows, nodes or prompts.
  - Adding CI service containers.
  - Changing the SSE event set beyond `debug`.
  - Storing `document_number` anywhere outside `bank.customers` and the export.
- **Never:**
  - Accept `customer_id` from a request body, query or path, except `/test-idp` in `eval`.
  - Log or return a full document number, password, JWT or CSRF token.
  - Commit `data/secrets/credentials.csv` or any secret.
  - Implement write tools, confirmation routes, the OTP route, `tools.yaml` or `audit_events` (D3).
  - Import an LLM SDK outside `core/llm`.
  - Touch `eval/scenarios/heldout/`.

## Success criteria

1. `make check` passes, with import-linter's contracts KEPT. The only change to them is D22's targeted `ignore_imports`, the three new unit tests green and the D1/D2-K tests unchanged.
2. With `make up` running, `make test-integration` passes all six integration tests above.
3. `make seed-identity` prints the account count (150,000 customers, no staff). `data/secrets/credentials.csv` exists, and `git status --ignored` shows it as ignored. `SELECT count(*) FROM identity.accounts` in `latam_app` returns 150000. `grep -c` of any seeded document number in `docker compose logs backend` returns 0 after a login.
4. **End-of-day step 1:** `/api/v1/docs` loads. `curl` login as a persona (document + password from the export) → 200 with cookies. `/auth/me` shows `login_hint` like `"DNI ••••462"` and that persona's first name only. Five wrong passwords, then a sixth attempt → 429.
5. **End-of-day steps 2–4:**
   - `make chat-api PERSONA=<multi-card customer_id>` answers an ES and a PT card-status question from Postgres, printing `status`, `message` and `debug` lines. *(Revision 2, D26: the balance question, "¿cuánto debo de mi tarjeta de crédito?", is pending D2-B1, because `balance_due` routes to `unsupported` today.)*
   - A foreign last 4 gets the "not among your cards" clarification.
   - `docker compose restart backend` between two turns, and the next message continues the pending flow.
6. **A5:** for the same persona, the card status / limit / balance answers in `make chat-api` match `make chat-sandbox`. Date-shifted fields may differ: Postgres is shifted, FakeBank reads raw CSVs.
7. **A6:** `make client` exits 0, and `git diff --stat frontend/src/client` shows the new auth and conversation operations.
8. `04` §3, `03` §6/§8, `01` §6 and ADR-008 read as in D1, D9 and D15. The PR is approved by Dev B and squash-merged.

## Open questions

| Question | Who decides |
|---|---|
| Whether browser reconnect (D3-B3) needs a `GET /conversations/{id}/messages` history route (pub/sub doesn't replay) | Dev B in D3-B3, with Dev A |
| Step-up window N and how `step_up_at` gets into the JWT (a re-issue on OTP verify) | Dev A in D3-A4 (decision-log deferred item) |
| How the separate staff panel page is protected (it has no login for now), including the `agent`/`admin` roles and the `04` §3 `/staff/*` routes | The staff-panel card (D4 handoff), not this card |
| The balance version of end-of-day step 2 ("¿cuánto debo…" in ES/PT), and the negative available credit seen live (`"US$-862.59 disponible"`). Pending, not done (D26) | Dev B in D2-B1 |
| How B5 flows detect `bank_write_tools is None` (a guard in each write node, or one shared helper) | Dev B in B5, reviewed by Dev A |
