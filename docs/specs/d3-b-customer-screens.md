# Spec: D3-B — G5 design and customer screens

Card: `07-execution-plan.md` D3, Dev B rows B1–B5. Owner: Dev B. Branch `feat/d3-b-customer-screens` → `develop`. Builds on D2-A (login, `/conversations` API, SSE), D2-B (flows, `ui.py` events) and `docs/brand.md`. It adds two `ui` event kinds to the conversation domain and proposes the A2/A4 request/response bodies, so Dev A reviews the backend part and confirms the `04` §3 shapes before building A2/A4 (ADR-018, human Q1).

## Objective

This card turns the empty frontend shell into the customer app. It delivers:
- **B1.** A Swip-branded theme, the landing, login and chat layouts, and the ES/PT text dictionary.
- **B2.** Login and logout with the cookie session.
- **B3.** A chat page that renders the SSE stream.
- **B4.** Four click widgets: card picker, pause/cancel chips, confirm buttons and the OTP modal. Each click is equivalent to typing.
- **B5.** Two Playwright specs, green in CI.

It serves the five B "Done when" lines of D3. End-of-day browser steps **1–2** are hard gates for this card. Steps **3–7** need Dev A's A2/A3/A4/A6 on the API path (today `runner.py` passes `bank_write_tools=None`) and are **verified at the A6 pairing** (human Q4). **Cut line** (`07` "If behind"): visual polish can wait, and the OTP modal moves to D4 morning.

## Decisions

| # | Decision | Why / trace |
|---|---|---|
| D1 | **A2/A4 shapes are proposed here and written into `04` §3:**<br>• `POST /conversations/{id}/confirmations/{token_id}` takes `{decision: confirm\|cancel}` and returns `202 {turn_id}`, with the same `409 turn_in_progress` / `409 conversation_closed` as `/messages`.<br>• `POST /auth/otp/verify` takes `{code}` and returns `204`, or `400 invalid_otp`.<br>• `POST /conversations/{id}/messages` takes exactly one of `{text}` or `{resume: "step_up"}`, otherwise `422`.<br>Dev A confirms these before building A2/A4. B4 codes against them now and regenerates the client when A merges | Human Q1(a). Closes the D2-B D1 open item ("the otp/verify route (or the frontend right after it) sends the same signal"). `04` §3 already says "the frontend runs the next turn with `resume`" |
| D2 | **OTP modal sequence.** Verify the code. On `204`, post `{resume:"step_up"}` to `/messages`. On `400 invalid_otp`, show an inline error and keep the modal open. The modal never posts the code as chat text | D1. `04` §3, D2-B D1 (the code is verified outside the chat, never in chat text or the LLM) |
| D3 | **New `ui.card_picker {options: [{label}]}`**, emitted wherever `card_select` returns `Ask` (the `card_info`, `card_block`, `card_unlock` and `replacement` Ask branches), through one helper in `card_select.py`. Each `label` is one line of the `card_options` string that code already builds (e.g. `"Crédito •••• 6475 · Activa"`) | Human Q3(a). `02` §4.1 already says `card_select` emits `ui.card_picker`. R4: labels are formatted in code |
| D4 | **New kind `ui.quick_replies {slot: "block_kind", options: [{label}]}`**, emitted by `card_block` with `clarify_lock_vs_block`. The labels are fixed ES/PT strings in code built from the lock/block lexicon, **not** "cancelar": `card_cancel` (Stretch) and `deny` are separate intents, and the word would collide with them | Human Q3(a). `02` §1 intent catalog, `02` §4.6 step 2 |
| D5 | **A picker or chip click posts its `label` as ordinary text** to `POST /messages`. It goes through `understand` exactly as if typed. Nothing new is added to `TurnInput` | Human Q3(a). B4 "Done when" ("works the same as typing") |
| D6 | **Confirm buttons** post `decision` to the D1 confirmations route with the event's `token_id`. The card lists every `steps[]` entry, with the title taken from `summary_key` in the dictionary and the `facts` values shown as received. Buttons are gold (needs confirmation). Both buttons disable after the first click | `04` §7 ("the frontend lists every step"), `brand.md` (gold; confirm and cancel are always real buttons), assumption 6 |
| D7 | **B5 is Playwright against the built frontend, with the API mocked** by `page.route` and scripted SSE fixture files that mirror the real event shapes (the fixtures are the fake LLM). There are two specs, and a new CI job runs them. The real-stack proof is the manual end-of-day test | Human Q2(a). CLAUDE.md "always with a fake LLM", `06` §6 E2E |
| D8 | **Sequencing.** B1 → B4 are built against D1; confirm and OTP are exercised only through the B5 mocks until A merges. End-of-day steps 3–7 are run at the A6 pairing | Human Q4(a) |
| D9 | **Theme and components.** shadcn/ui components are copied into `components/ui/`. The brand tokens (`bg`, `cyan`, `gold`, `alert`) go in Tailwind v4 `@theme` in `index.css`. Plus Jakarta Sans (headings) and Inter (body) are self-hosted via `@fontsource`. Stars appear on the landing and outside the chat panel only | `brand.md` §Visual identity, `06` §4 (Radix + Tailwind v4 CSS-first tokens), assumption 1 |
| D10 | **i18n.** A hand-rolled dictionary (`lib/i18n/{es,pt}.json` + a React context) covers every UI string. The default comes from `navigator.language` (`pt*` → PT, else ES). The ES \| PT toggle is persisted in localStorage and changes only the UI chrome. Its current value is sent as `language` on `POST /conversations` | ADR-022, `brand.md` §"Where the brand lives in code" item 4, assumption 2 |
| D11 | **Session handling.** Login is an RHF + Zod form: `document_type` (DNI\|CC\|CE\|Pasaporte), number and password. The client sends `X-CSRF-Token` from the `csrf_token` cookie on every non-GET request. On a `401`, it calls `/auth/refresh` once, then redirects to `/login`. `invalid_credentials` and `too_many_attempts` map to dictionary strings | `04` §3 "Login and `/me`", D2-A CSRF (double submit), assumption 3 |
| D12 | **Stream handling.** The chat uses a native `EventSource` on `/stream` (GET, so no CSRF is needed), opened before the first `POST /messages`.<br>• It shows the customer bubble optimistically.<br>• Every `status` maps to one "Cardy está escribiendo / digitando" indicator.<br>• `ui` events attach to the next `message`.<br>• `debug` is ignored.<br>• `done` re-enables input.<br>• `error` shows a dictionary string.<br>• `ui.conversation_closed` offers "new conversation".<br>• On a dropped stream it shows "reconectando" and relies on EventSource auto-reconnect; there is no replay.<br>• `conversation_id` is kept in sessionStorage. A reload shows an empty transcript (no history route) | `04` §3 SSE events, D2-A stream contract (`: connected`, pings), assumptions 4–5 |
| D13 | **No Vitest.** Frontend tests are the two B5 specs only. The backend additions are proven by extending the existing flow tests | CLAUDE.md "Keep tests minimal", `wave-run` test budget, assumption 7 |

## Contracts

**`04` §3 (updated in this card; Dev A confirms, D1):**
```
POST /api/v1/conversations/{id}/confirmations/{token_id}   customer, CSRF, get_owned_conversation
  body   ConfirmationRequest{decision: "confirm" | "cancel"}          (extra="forbid")
  202    PostMessageResponse{turn_id}
  409    turn_in_progress | conversation_closed      404 not_found
  → runs a turn with TurnInput{user_text: "", confirmation: {token_id, decision}, resume: None}

POST /api/v1/auth/otp/verify                                customer, CSRF
  body   OtpVerifyRequest{code: str}
  204    step-up window opened in the session
  400    invalid_otp

POST /api/v1/conversations/{id}/messages                    (amended)
  body   PostMessageRequest{text?: str (1..2000), resume?: "step_up"}  exactly one → else 422
  → resume turn: TurnInput{user_text: "", confirmation: None, resume: "step_up"}
```
Implementation of the first two routes and the `resume` field is **Dev A's (A2/A4)**. This card only writes the shapes into `04` and codes the frontend against them.

**`ui.py` (this card):**
```python
class PickerOption(BaseModel):          # frozen
    label: str                          # code-formatted, e.g. "Crédito •••• 6475 · Activa"

class CardPickerPayload(BaseModel):     # frozen
    options: list[PickerOption]

class CardPickerEvent(BaseModel):       # frozen
    kind: Literal["card_picker"]
    payload: CardPickerPayload

class QuickRepliesPayload(BaseModel):   # frozen
    slot: Literal["block_kind"]
    options: list[PickerOption]

class QuickRepliesEvent(BaseModel):     # frozen
    kind: Literal["quick_replies"]
    payload: QuickRepliesPayload

UIEvent = Annotated[ConfirmEvent | OtpRequiredEvent | ConversationClosedEvent
                    | CardPickerEvent | QuickRepliesEvent, Field(discriminator="kind")]
```
The `04` §3 SSE `ui.kind` list gains `quick_replies`, and the payload lines gain `card_picker {options: [{label}]}` and `quick_replies {slot, options: [{label}]}`.

**Frontend UI strings:** `lib/i18n/es.json` and `lib/i18n/pt.json` have identical key sets. The `summary_key` values used today are `lock_card`, `block_card`, `unlock_card` and `order_replacement` (the `card_block`, `card_unlock` and `replacement` flows).

## Touch map

```
backend/app/domains/conversation/ui.py                  + CardPicker*, QuickReplies*, PickerOption; UIEvent union
backend/app/domains/conversation/flows/card_select.py   + card_picker_event(outcome: Ask) helper
backend/app/domains/conversation/flows/{card_info,card_block,card_unlock,replacement}.py
                                                        Ask branches append card_picker; card_block clarify appends quick_replies
backend/tests/unit/test_card_info_flows.py, test_block_flows.py   extend existing ES/PT cases
docs/solution-docs/04-contracts.md                      §3 (D1 shapes, new ui kinds/payloads)
frontend/package.json, components.json                 shadcn/Radix, RHF, zod, @fontsource/*, @playwright/test
frontend/src/index.css                                  @theme brand tokens, fonts
frontend/src/lib/{api.ts (client config: CSRF, 401→refresh), i18n/, sse.ts}
frontend/src/components/ui/                             shadcn copies
frontend/src/components/layout/                         app shell, starry background, language toggle
frontend/src/components/chat/                           MessageList, Composer, StatusIndicator, CardPicker, QuickReplies, ConfirmCard, OtpModal
frontend/src/routes/{__root,index,login,chat}.tsx       landing, login, chat (chat guarded by /auth/me)
frontend/src/client/                                    regenerated only (make client), never hand-edited
frontend/e2e/{playwright.config.ts, fixtures/*.sse, card-info.es.spec.ts, block.pt.spec.ts}
.github/workflows/ci.yml                                frontend job: tsc + build; new e2e job (playwright)
```

## Test list

| Test | Proves |
|---|---|
| `test_card_info_flows.py::test_credit_balance_due[es,pt]` (extended with a multi-card persona) | D3. An `Ask` turn emits exactly one `card_picker` whose labels equal the masked option lines, in ES and PT (R4: no label from the LLM) |
| `test_block_flows.py::test_es_lock_clarify_confirm_readback` (extended) | D4. The `clarify_lock_vs_block` turn emits `quick_replies{slot:"block_kind"}` with two labels. A follow-up turn whose text is the temporary-lock label (the scripted NLU returns `temporary_lock`) reaches `ui.confirm` |
| `e2e/card-info.es.spec.ts` | B2, B3, B4 picker, B1 language (end-of-day steps 1–2). An `es-ES` browser shows the ES UI. Login → chat → a balance question → a click on a picker option sends a `POST /messages` whose body is that label → the mocked stream's answer renders. The toggle switches the chrome to PT. Logout returns to `/login` |
| `e2e/block.pt.spec.ts` | B4 chips and confirm, D1 shape (PT happy path). A `pt-BR` browser. Login → "quero bloquear meu cartão" → the chip click posts the label → `ui.confirm` renders a gold card listing its step → the confirm click hits `POST …/confirmations/{token_id}` with `{decision:"confirm"}` → the verified reply renders in cyan |

R1/R2/R3/R13 are untouched: the routes that enforce them are A's, and so are their tests. The existing R6 scan and the D2 tests must stay green.

## Boundaries

**Always**
- Every UI string lives in `es.json`/`pt.json`. Money, dates and masks come only from the server payloads and are rendered as-is (R4).
- Confirm and cancel are real buttons. Confirmation goes only through the D1 route with the event's `token_id`.
- The OTP code goes only to `/auth/otp/verify`. It is never shown in the transcript and never logged.
- Regenerate `src/client/` with `make client`. Never hand-edit it.

**Ask first**
- Any change to the D1 shapes after Dev A reviews them. Any backend change beyond `ui.py`, the helper and the Ask/clarify emissions.
- Adding a history route, a new `TurnInput` field, or a staff screen.

**Never**
- Send `customer_id` from the frontend (R1). Show a full document number (only `login_hint`).
- Parse bot text to build widgets.
- Call an LLM from the frontend or from Playwright. Put real persona credentials in e2e fixtures or the repo.
- Touch `eval/scenarios/heldout/`.

## Success criteria

1. **B1.** `frontend/src/index.css` defines the four `brand.md` colors as `@theme` tokens. `es.json` and `pt.json` have identical key sets (a one-line `node -e` key diff prints nothing). Dev A signs off on the screens at the midday check (recorded in the PR).
2. **B2.** With `make up`, logging in as a seeded persona in the browser lands on `/chat`. A wrong password shows the `invalid_credentials` string. Logout returns to `/login`, and `/chat` then redirects to `/login`.
3. **B3.** With `make up` and a multi-card persona, "¿cuánto debo de mi tarjeta de crédito?" in the browser shows the status indicator, then the balance answer. Killing and restarting the backend container shows "reconectando", and the next message is answered.
4. **B4.** Picking a card by click gives the same answer as typing its label. The `card_picker`/`quick_replies` pytest assertions pass. Confirm and OTP match the D1 shapes (checked by the e2e spec and, after A merges, by end-of-day steps 3–4).
5. **B5.** `npx playwright test` passes locally, and the CI `e2e` job is green on the PR.
6. `make check` is green (Biome, tsc, backend lint, types, import-linter, unit tests). `04` §3 contains the D1 shapes and the two new `ui` kinds.
7. End-of-day steps 1–2 pass in the browser. Steps 3–7 are marked "verified at A6 pairing" in the PR.

## Open questions

- **Dev A:** confirm or amend the D1 shapes before building A2/A4. If A amends them, this spec's D1 and `04` §3 get amended together.
- **Dev A (A4):** the step-up window length is still the decision-log deferred item. It doesn't affect the UI.

## Amendments during build

Mid-card human decisions. None of them changes a contract in `04` (the NLU output schema in `04` §2 is unchanged; only the prompt version moves), so `04` is untouched.

| # | Amendment | Source |
|---|---|---|
| A1 | Every frontend command (npm, Biome, tsc, Playwright) runs in Docker. There is no host Node | Plan Q1b |
| A2 | The Makefile is untouched. tsc runs only in CI | Plan Q2b |
| A3 | The OTP modal is proven at the A6 pairing, not by a B5 spec. This narrows Success criterion 4 for OTP | Plan Q3a |
| A4 | Scope addition: `make data` failed because the TRUNCATE on `bank.*` was blocked by the FK `identity.accounts → bank.customers`. `pipeline/load/postgres.py` now also truncates `identity.accounts`, as an explicit table list, not `CASCADE` | T6, human chose to fix it in this card |
| A5 | Scope addition: clicking a card-picker label in the block flow re-asked which card for a customer with two cards of the same kind. Confirmed live: `nlu@v3` returned `card_hint="credit"` in `card_block` context. Fix: `prompts/nlu@v4.md` adds a flow-agnostic rule that an answer to a pending `card_hint` containing `•••• NNNN` yields `last4:NNNN`, and `understand.py` uses `PromptRef("nlu", 4)`. This is needed for D5 ("a click works the same as typing") | T7, live check |

**Known issues outside this card (notes only, not fixed here):**
- `test_personas` fails on the `load_date` edge. Owner: D2-A.
- The integration tests can't run on Windows: the `localhost` → `::1` Redis ping times out, and psycopg needs a `SelectorEventLoop`.
- `scripts/nlu_smoke.py --dry-run` pins nlu v2.
- The card-info `compose` reply says "Tu cuenta no está activa" for an active card (D2 compose content).
