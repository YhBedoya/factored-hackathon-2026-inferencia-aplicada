# Spec: Swip landing, banking home and Cardy's welcome

Card `landing-home-bienvenida` (not a row of `07`) · source: [`docs/requirements/landing-home-bienvenida.md`](../requirements/landing-home-bienvenida.md) (R1, R2, R3) · G5 Web app, owner Dev B, with a small read-only backend part · branch `feat/landing-home-bienvenida` (base `develop` e5add3e).

## Objective

The card delivers three things:

- **R3, the welcome:** every new chat opens with a warm welcome from Cardy. It comes from a template bank in code and never repeats the customer's previous welcome.
- **R2, the banking home:** after login the customer lands on a protected `/home`. It shows their cards, credit balance and transaction history through three new read-only `/api/v1/me/*` endpoints, plus alerts and quick actions that open Cardy in a side panel with a pre-filled composer.
- **R1, the landing:** `/` becomes the Swip landing built from the Claude Design export. This is the last task, and it is gated on the export being present. ~~Deferred (AM3)~~ **Reinstated (AM8):** the export arrived after verify, and T7 built the landing in this card, so it ships R1 + R2 + R3.

It serves every "Hecho cuando" line of R1, R2 and R3 in the requirements doc. The Success criteria below restate each one in a form you can check.

## Assumptions (accepted with the human answers)

- **A1: debit cards (ADR-020, revised by ADR-034 on 2026-10-01).** Debit cards show mask, status, expiry, transactions and their **available balance**: `/me` views return `current_balance`/`current_balance_display` for debit. Credit limit, available credit and days past due stay `null` for debit.
- **A2: welcome text (`docs/brand.md` §"Where the brand lives in code", R3 "Por qué plantillas").** Fixed ES/PT templates in code. No LLM call, and no digits in any template. PT is pending review by a native speaker.
- **A3: chat on `/home` (requirement R2 table).** The chat is a side panel, full screen on mobile. The chat body moves out of `routes/chat.tsx` into one shared component, which `/chat` (still a full page) and the panel both use. They share `conversationStore` (`sessionStorage`), so they continue the same conversation.
- **A4: the `/me` router (R13, `06` §2).** It is a new router with router-level `require_role("customer")` + `require_csrf`, and it calls `cards.service` and `transactions.service` directly. Both `AccessDenied` and `NotFound` map to `404 not_found`.
- **A5: transaction pages.** The home gets its own keyset-paginated service function. `transactions.search` (the LLM tool, at most 10 rows, `04` §1) does not change.
- **A6: storing the welcome.** It is saved as the conversation's first bot message, under its own `turn_id`, so the staff transcript and the traceability timeline show it.
- **A7: the first customer turn.** The graph and `smalltalk` don't change. A "hola" after the welcome still gets the `greeting` template.
- **A8: welcome language.** The welcome uses the create request's `language`, which is the UI language.
- **A9: route guard.** `/home` uses the same `beforeLoad` + `me()` guard as `/chat`.
- **A10: docs and client.** `04` §3 gets the new rows, then `make client` runs from a clean generated client (the working tree currently has uncommitted regenerated files and an untracked `openapi-ts-error-*.log`).
- **A11: tests.** Test budget as in the Test list; one Playwright spec for the home.

## Decisions

| # | Decision | Why |
|---|---|---|
| D1 | **Opt-in welcome.** `POST /conversations` takes `welcome: bool = false`. When it is `true`, the route builds the welcome, stores it, and returns it in `CreateConversationResponse.welcome`. When it is `false`, nothing changes. The eval driver and simulator keep sending `{}`. | Human Q1(a). Redis pub/sub has no replay, and the stream opens after the create call, so SSE can't carry it. Eval runs and turn counts stay comparable. |
| D2 | **Eager create.** The web chat (`/chat` and the `/home` panel) creates the conversation with `welcome: true` as soon as it opens without a stored conversation id, and again on "new conversation". With a stored id it reconnects the stream and does not create anything, so no welcome is shown. | Human Q1(a); R3 item 1 ("sin que el cliente escriba nada"). |
| D3 | **Welcome content.** At least 8 bodies per language in `templates.py`, plus a day-part salutation (morning / afternoon / evening) picked from the hour in the customer's country `BANK_TZ`. The salutation includes the first name when the profile has one. The text is 1–2 sentences, ends with an invitation to say what they need, and contains no digits. **Amended (AM5):** the 1–2 sentence limit applies to the body only; the day-part salutation in front of it does not count. | R3 items 2 and 4; `docs/brand.md` §"Voice and tone"; human Q6(a). |
| D4 | **"Always different."** Redis key `welcome:last:<customer_id>` holds the index of the body used last, with a 30-day TTL. The next pick is uniform among the other bodies. A missing key means any body. The day-part salutation does not count toward "different". | Human Q6(a); R3 item 3. |
| D5 | **Welcome persistence.** One `store.add_message(role="bot")` under a fresh `turn_id`. `content` is the filled text (encrypted by the store). `content_masked` is `PostgresPiiVault(conversation_id).mask(text, known_pii)`, the same masking the runner uses. The first name and country come through the `conversation.tools` registry (the same source as `load_session`), never from a bank repository. **Amended (AM2):** the registry gains `registry.session_profile(ctx)`, which the welcome uses as its profile source. | R3 item 5; R5; `06` §2 conversation contract; `runner.py` masking pattern. |
| D6 | **Routes.** The home lives at `/home`. Login always navigates to `/home`, and `/chat` stays reachable by URL. The 5 Playwright specs that wait for `**/chat` after login are updated: they wait for `**/home`, then `goto('/chat')`. | Human Q4(a). |
| D7 | **Formatting on the server.** `/me` responses carry raw values plus display strings from `localization.format`: `format_money(amount, currency, country)`, `format_date` of the local date in `BANK_TZ`, and `mask_card`. The frontend only translates the status and card-type enums through i18n. It never formats money or dates. | Human Q3(a); R4; `02` §7 (a per-country separator table that CLDR/`Intl` would contradict). |
| D8 | **Foreign cards are 404.** `GET /me/cards/{card_id}` and a `card_id` filter on `/me/transactions` both return `404 not_found`, the same body, for another customer's card and for an unknown one. | Requirement R2 "Backend nuevo"; R1; same shape as `get_owned_conversation` (R13). |
| D9 | **Transaction paging.** A new `transactions.service.list_page(customer_id, tx_filter, cursor, limit=20)`, ordered by `occurred_at desc, tx_id desc`, with an opaque cursor (url-safe base64 of `occurred_at` ISO + `tx_id`). It reuses `TxFilter`, including its 366-day window check. A bad cursor is `422`. The frontend uses "ver más" (append the next page). | Requirement R2 (`cursor=` parameter); A5. |
| D10 | **Home extras.** Every section has translated empty, loading (skeleton) and error states. Alerts: a blocked or suspended card; a credit card with `days_past_due > 0`; a recent declined transaction. Quick actions: lock/unlock, replacement, dispute a charge, "¿por qué me rechazaron?". An alert's "Preguntarle a Cardy" and every quick action open the Cardy panel with the composer **pre-filled** with a localized sentence (i18n `home.*`). The customer presses send, and NLU treats it as typed text. The frontend computes alerts from the three `/me` responses; there is no alerts endpoint. Transaction detail and hide-amounts are **out of scope**. | Human Q5(b); requirement R2 "Fuera de alcance" (no writes from home buttons; R2 confirmation still applies). |
| D11 | **Design source.** The human exports SwipLanding v2 to `docs/design/landing/SwipLanding-v2.html` + `docs/design/landing/assets/`. The landing task is the plan's last task and depends on that file. If the file is missing when the task comes up, R1 moves to a follow-up card and this card ships R2 + R3. `/home` has no design and is built from the `docs/brand.md` tokens. **Applied (AM3), then reversed (AM8):** the export arrived after verify, so R1 is back in this card. It is a decoded template with no image assets. | Human Q2(a); AM3; AM8. |
| D12 | **Recent-decline alert window.** The alert fires when the first transactions page has a `Declined` row dated within 7 days of `local_today(country)`. **Amended (AM1):** the frontend checks it against the browser clock, `occurred_at >= now − 7×24h`; `TxRow` gets no server-side flag. | Human answer at the spec gate; AM1 (plan gate). |
| D13 | ~~**Day-part boundaries**~~ **Superseded (AM9):** the salutation no longer depends on the time of day. `welcome.py` picks one of several salutations at random ("Hola, {name}.", "¡Qué bueno verte, {name}!"…), and every body speaks of the Swip universe ("te doy la bienvenida a este universo de posibilidades"), with no gendered "bienvenido/bienvenida". | Human request 2026-10-01 (Cardy greets with the universe concept). Refines D3. |

## Contracts (delta only)

**`POST /api/v1/conversations`** (`04` §3, amended):

```python
class CreateConversationRequest(BaseModel):   # extra="forbid"
    language: Literal["es", "pt"] | None = None
    welcome: bool = False                         # D1

class WelcomeMessage(BaseModel):              # frozen
    text: str                                     # filled, unmasked, for display only

class CreateConversationResponse(BaseModel):  # frozen
    conversation_id: UUID
    welcome: WelcomeMessage | None = None         # set only when the request had welcome=true
```

**`/api/v1/me/*`**: a new router in `backend/app/api/v1/me.py`, prefix `/me`, role `customer` + CSRF at router level. The response models live in the same file (the convention `conversations.py` follows). No route takes `customer_id` (R1).

| Method & path | Response | Errors |
|---|---|---|
| `GET /me/cards` | `list[CardView]`, every status | none beyond auth |
| `GET /me/cards/{card_id}` | `CardDetailsView` | `404 not_found` (foreign or unknown, D8) |
| `GET /me/transactions?card_id=&date_from=&date_to=&cursor=` | `TxPage` | `404 not_found` on a foreign or unknown `card_id`; `422` on a bad cursor or date window |

```python
class CardView(BaseModel):          # frozen
    card_id: str; kind: Literal["credit","debit"]; last4: str; mask: str   # mask_card
    status: Literal["Active","Blocked","Suspended","Closed"]; locked: bool

class CardDetailsView(CardView):
    currency: str
    expiration_date: date | None; expiration_date_display: str | None       # format_date
    credit_limit: Decimal | None; credit_limit_display: str | None          # null for debit
    current_balance: Decimal | None; current_balance_display: str | None    # debit: available balance (A1, ADR-034)
    available_credit: Decimal | None; available_credit_display: str | None  # null for debit
    days_past_due: int | None                                               # null for debit

class TxRow(BaseModel):             # frozen
    tx_id: str; card_id: str; card_mask: str | None                         # None if not a card product
    occurred_at: AwareDatetime; date_display: str                           # format_date(local date, BANK_TZ)
    amount: Decimal; currency: str; amount_display: str                     # format_money(.., country)
    merchant_name: str | None; type: str
    status: Literal["Approved","Declined","Pending","Reversed"]

class TxPage(BaseModel):            # frozen
    items: list[TxRow]              # at most 20, newest first
    next_cursor: str | None
```

The country used for formatting comes from `customers.service.get_profile(session customer_id)`. Status, type and kind labels are i18n keys on the frontend.

**`transactions.service.list_page`** (D9): `async def list_page(customer_id: str, tx_filter: TxFilter, cursor: str | None, limit: int = 20) -> tuple[list[TxView], str | None]`, backed by a new repository query. `search` and `fetch_transactions` do not change.

**Welcome** (`backend/app/domains/conversation/welcome.py`): `async def post_welcome(conversation_id, *, session, language) -> str` picks the body (D4), fills it (D3), persists it (D5) and returns the display text. The bodies and day-part salutations are new entries in `templates.py`.

**Redis:** `welcome:last:<customer_id>` → the body index as a string, TTL 30 days (D4).

**Frontend:**
- `createConversation(lang, {welcome: true})` returns `{conversationId, welcome}`.
- `Composer` gains a `prefill` prop.
- i18n adds `home.*` (sections, states, alerts, quick-action sentences) and `landing.*`, in both `es.json` and `pt.json`.

## Touch map

Backend:
- `backend/app/api/v1/me.py` (new) and `backend/app/api/v1/__init__.py` (mount it).
- `backend/app/api/v1/conversations.py`: the `welcome` flag and response field.
- `backend/app/domains/conversation/welcome.py` (new) and `backend/app/domains/conversation/templates.py` (welcome bodies and salutations).
- `backend/app/domains/transactions/service.py` and `backend/app/domains/transactions/repository.py`: `list_page`.
- Tests: see the Test list.

Frontend:
- `frontend/src/routes/home.tsx` (new), `login.tsx` (→ `/home`), `chat.tsx` (uses the shared chat component and eager create), `index.tsx` (landing, last task).
- `frontend/src/components/chat/ChatView.tsx` (new, extracted from `chat.tsx`) and `Composer.tsx` (`prefill`).
- `frontend/src/components/home/`: cards, balance, transactions, alerts, quick actions, Cardy launcher/panel.
- `frontend/src/components/landing/` (last task, T7).
- `frontend/src/components/layout/AppShell.tsx`: the "Cardy, de Swip" wordmark is removed on every page (AM14/AM15, approved scope extension).
- `frontend/src/lib/api.ts`, `frontend/src/lib/i18n/es.json`, `pt.json`.
- `frontend/src/client/` regenerated with `make client`.

E2E:
- `frontend/e2e/mock-api.ts`: `/me/*` and the welcome.
- The 5 login specs (`block.pt`, `card-info.es`, `session-expiry.es` ×2 waits, `unrecognized.es`).
- `frontend/e2e/home.es.spec.ts` (new).

Docs:
- `docs/solution-docs/04-contracts.md` §3: the `/me` rows and the `POST /conversations` amendment.

## Test list

| Test | Proves |
|---|---|
| `backend/tests/integration/test_r1_me_routes.py::test_other_customer_cannot_read` | R1 on all three endpoints. Customer B gets `404` on A's `card_id` (detail, and as a transactions filter), and B's `/me/cards` and `/me/transactions` contain none of A's ids. |
| `backend/tests/unit/test_r1_routes.py`, `test_r13_routes.py` (existing, must stay green) | The new router takes no `customer_id` and declares its role at router level (R1, R13). |
| `backend/tests/unit/test_me_views.py::test_display_strings_from_localization` | R4: `amount_display`, `*_display` and `mask` equal `localization.format` output for an MX and a CO (COP, no decimals) row. Debit rows have `current_balance = null`. |
| `backend/tests/unit/test_welcome.py::test_consecutive_welcomes_differ` | R3 "Dos chats seguidos … nunca la misma bienvenida": 20 successive picks for one customer never repeat the previous body. |
| `backend/tests/unit/test_welcome.py::test_first_turn_after_welcome_es` / `_pt` | R3 ES and PT with the fake LLM. After a `welcome=true` create, the welcome is stored as the first bot message in the UI language with the name masked in `content_masked` (R5), and the customer's first turn (a card-status question) completes as it does without a welcome. **Amended (AM6):** the first turn runs on the welcome's own `conversation_id`, with an ES turn in the ES test and a PT turn in the PT test. |
| `frontend/src/lib/uuid.ts` (T8, AM4) | No test. `newId()` uses `crypto.randomUUID`, and falls back to `crypto.getRandomValues` where it is missing. It is only a message key in the UI, not a safety rule. |
| `frontend/e2e/home.es.spec.ts` | R2 against the mock API: login → `/home` shows cards, balance and transactions; "Hablar con Cardy" opens the panel on `/home` with a welcome and a sent message gets a reply; visiting `/home` without a session → `/login`. |
| 5 updated login specs | `/chat` still works as a full page after the redirect change. |

## Boundaries

- **Always:**
  - `customer_id` comes from the session only.
  - Money, dates and masks are formatted in `localization.format`.
  - Every visible string goes through `es.json` and `pt.json`.
  - Quick actions and alerts only pre-fill the composer.
  - Run `make client` after any backend schema change.
- **Ask first:**
  - Any change to `transactions.search`, `TxFilter` or the graph.
  - A new endpoint beyond the three `/me` routes.
  - Making `welcome` the default for API callers.
  - Adding a colour or font outside the brand tokens.
- **Never:**
  - Execute a write from a home button.
  - Send the welcome or the `/me` data through the LLM or Langfuse.
  - Show a debit balance or a full card number.
  - Start the landing task without `docs/design/landing/SwipLanding-v2.html`.
  - Touch `eval/scenarios/heldout/`.
  - Hand-edit `frontend/src/client/`.

## Success criteria

1. `cd backend && uv run pytest tests/integration/test_r1_me_routes.py tests/unit/test_me_views.py tests/unit/test_welcome.py tests/unit/test_r1_routes.py tests/unit/test_r13_routes.py` passes.
2. `make check` passes, including import-linter.
3. `cd frontend && npm run lint && npm run typecheck` passes, and `npx playwright test` passes, including `home.es.spec.ts` and the 5 updated login specs.
4. Live stack (`make up`, persona login). **Amended (AM7):** checked by hand by the human, because the permission classifier blocks the verifier from using persona credentials:
   - Login lands on `/home`, which shows the persona's real cards (masked), the credit balance with a usage bar and `available_credit`, and transactions with "ver más", in ES and in PT via the toggle.
   - "Hablar con Cardy" opens the panel without leaving `/home`.
   - `/chat` still works as a full page.
5. Two new conversations in a row (`POST /conversations {"welcome": true}` twice, same customer) return different welcome bodies. The welcome is the first row in `GET /staff/conversations/{id}/messages`.
6. `curl` on `/api/v1/me/cards/<another customer's card_id>` with a customer session returns `404 {"detail":"not_found"}`. **Amended (AM7):** the two-customer integration test `test_r1_me_routes.py` skips on the Windows host, so it must pass on Linux/CI.
7. `docs/solution-docs/04-contracts.md` §3 lists the three `/me` routes and the `welcome` flag and response field.
8. **Reinstated (AM8; supersedes AM3):** R1 is in this card. `/` renders the landing sections from `frontend/src/components/landing/` in ES and PT, with no horizontal scroll at 360 px, and "Iniciar sesión" is a link to `/login`. Screenshots (desktop and mobile, ES and PT) are attached to the PR. Additional checks:
   - "Abre tu cuenta" and "Pide tu tarjeta" are disabled buttons with a "Próximamente" / "Em breve" badge (AM9).
   - "Iniciar sesión", "Probar Cardy", "Conoce a Cardy", "Ayuda con Cardy" and the floating Cardy entry all link to `/login` (AM10).
   - The footer team column reads "Yhorman Bedoya & Luisa Jiménez" (AM11).
   - No new colour or font tokens appear in `frontend/src/index.css` (AM12).

## Mid-card amendments

| # | When | Change |
|---|---|---|
| AM1 | Plan gate | The 7-day decline alert (D12) uses the browser clock against `occurred_at`. `TxRow` has no server flag for it. |
| AM2 | Plan gate | `registry.session_profile(ctx)` is added as the welcome's profile source (D5). This keeps `conversation` off the bank services, as import-linter requires. |
| AM3 | After T6 | R1 is deferred to a follow-up card, because the export `docs/design/landing/SwipLanding-v2.html` was not provided (D11, SC8). **Superseded by AM8.** |
| AM4 | After T6 | New task T8: `frontend/src/lib/uuid.ts` `newId()` falls back to `crypto.getRandomValues` when `crypto.randomUUID` is missing (insecure origin `http://nginx`). It is used in `ChatView` and staff `AgentChat`. |
| AM5 | Verify | D3's "1–2 sentences" applies to the welcome body. The day-part salutation in front does not count. |
| AM6 | Verify | The first-turn tests run the customer's first turn on the welcome's `conversation_id`, with an ES turn and a PT turn. |
| AM7 | Verify | The human checks the logged-in UI criteria (SC4) by hand, because the permission classifier blocks the verifier from using credentials. The two-customer R1 integration test skips on the Windows host and relies on Linux/CI. |
| AM8 | End of card | R1 is un-deferred. The export was saved at `docs/design/landing/SwipLanding-v2.html` after verify: a decoded template with no image assets. T7 builds its visuals in JSX and Tailwind (D11, SC8). |
| AM9 | End of card | "Abre tu cuenta" and "Pide tu tarjeta" render as disabled buttons with a "Próximamente" (PT "Em breve") badge, because no account-opening flow exists. |
| AM10 | End of card | "Iniciar sesión", "Probar Cardy", "Conoce a Cardy", "Ayuda con Cardy" and the floating Cardy entry all link to `/login`. |
| AM11 | End of card | The footer team column reads "Yhorman Bedoya & Luisa Jiménez". |
| AM12 | End of card | The export's colours and fonts are mapped to the existing brand tokens, with no new tokens. The mapping table is in the state file's T7 entry. |
| AM13 | End of card | The floating Cardy card shows only between the hero and the footer: it is hidden while at least 50% of the hero is visible or the footer is visible. The pill is always visible. Accepted: mid-page, the card may overlap the Cardy paragraph. |
| AM14 | End of card | `AppShell.tsx`'s wordmark truncates at 360 px, to meet the no-horizontal-scroll criterion. This is an approved scope extension. |
| AM15 | Final gate | The AppShell wordmark "Cardy, de Swip" is removed on every page (supersedes AM14). The landing nav "Swip" logo is kept and enlarged. |
| AM16 | Final gate | The landing gets an animated warp starfield (`WarpStarfield.tsx`, canvas, 500 stars, still frame under reduced motion). The hero cards get gold EMV chips, and the credit card a lighter cyan gradient, using brand tokens only. |
| AM17 | After push | Landing has no nav bar and no "Ayuda con Cardy" nav link: "Iniciar sesión" and the disabled "Abre tu cuenta" sit top-right at the content column edge, and ES/PT sits at the far right edge of the page. AppShell skips its header on `/`. The hero heading is the Swip logo (cyan square + "Swip") beside the cards, replacing "Tus tarjetas, claras y en tus manos." |
| AM18 | After push | The hero paragraph is the tagline "Tu universo financiero, a un Swip de distancia." (PT "Seu universo financeiro, a um Swip de distância."). The logo and tagline are enlarged (tagline in `text-foreground`), and the hero label "Tarjetas de crédito y débito · México, Colombia y Argentina" is removed. |
| AM19 | After push | The `#cardy` section copy is rewritten: title "Cardy, tu copiloto inteligente en el universo Swip", an intro, three bullets and a closing line (keys `landing.cardy.{body,item1,item2,item3,closing}`), with the CTA "Conoce a Cardy" (PT "Conheça a Cardy"). |
| AM20 | After push | The Cardy intro is styled like its bullets. The nav and hero fill the first screen (`min-h-svh`), so the Cardy section starts below the fold, and the hero components are scaled up on large screens. |

`04-contracts.md` §3, as updated by T3, is consistent with this spec. Its 422 detail codes (`invalid_filter`, `invalid_cursor`) are more specific than this spec's plain `422`, which is a refinement, not a contradiction.

## Open questions

- None. The export question is resolved by AM8.
