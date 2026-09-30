# State: landing-home-bienvenida — Swip landing, banking home and Cardy welcome
<!-- ORCHESTRATOR ZONE — you own this. Implementers never edit it. -->

## Card
Card REQ landing-home-bienvenida (G5, owner B) · requirements `docs/requirements/landing-home-bienvenida.md` · spec `docs/specs/landing-home-bienvenida.md` · plan `docs/plans/landing-home-bienvenida.md`
Branch `feat/landing-home-bienvenida`, based on `develop` (e5add3e).

## Conventions established for this card
- Binding facts live in the plan's §"Settled after the spec gate" and §"Facts checked against the repo". Read only the parts your task names.
- No migration; alembic head stays `0008`.
- Client regeneration: `docker exec -w /app latam-cs-frontend-1 npx @hey-api/openapi-ts -i http://nginx/api/v1/openapi.json` (host has no `npx`).
- Welcome exports: `WELCOME_BODIES`, `WELCOME_SALUTATIONS` in `conversation/templates.py`.

## Human decisions taken mid-card
- (plan gate) T3 may discard the CRLF-only diffs in `frontend/src/client/` and delete `frontend/openapi-ts-error-1790775270071.log`.
- (plan gate) The 7-day decline alert uses the browser clock (now − 7×24h); no server flag on `TxRow`.
- (after T6) T7 landing deferred to a follow-up card (export missing). Add T8: UUID fallback for insecure origin in ChatView + staff AgentChat.
- (final gate) Credit card lightened: bg-muted + cyan/35 gradient + cyan/40 border (tokens only).
- (final gate) Hero cards get gold EMV chips (Chip in Hero.tsx, gold token gradient + contact lines).
- (final gate) Landing gets animated warp starfield (canvas, 500 stars, perspective, reduced-motion = still frame) in components/landing/WarpStarfield.tsx; no bg images.
- (final gate) Remove "Cardy, de Swip" wordmark from AppShell on all pages (orchestrator edit). Landing Nav "Swip" logo kept, enlarged to text-3xl/sm:text-4xl.
- (after T7 repair) Floating card shown only between hero and footer; may cover Cardy paragraph mid-page, human accepted.
- (after T7) Keep AppShell.tsx wordmark truncate (scope ext). Floating Cardy bubble shows only after scrolling past hero.
- (after verify) Export saved (decoded template). T7 resumed: "Abre tu cuenta"/"Pide tu tarjeta" = disabled "Próximamente"; Cardy CTAs + floating bubble → /login; footer team = Yhorman Bedoya & Luisa Jiménez; colors/fonts mapped to brand tokens.
- (spec gate) Decline alert window 7 days; day parts 05–12 / 12–19 / 19–05 country local time.

## Task board
| Task | Status | Agent | One-line result |
|---|---|---|---|
| T1 | done | aa5d9d35 | /me router + views + list_page; R1 (2 integ) + R4 unit pass |
| T2 | done | ad3821b8 | Welcome bank (8 ES/8 PT), post_welcome, session_profile, welcome flag; 4 tests pass |
| T3 | done | a95a8693 | 04 §3 synced, client regenerated, live welcome/404/paging proof passed |
| T4 | done | a3617d47 | Shared ChatView, eager welcome create, Composer prefill; 5 e2e pass |
| T5 | done | a512cbd2 | /home with cards, balance, tx, alerts, quick actions, Cardy panel; typecheck/biome/build clean |
| T6 | done | a5b8641c | Login→/home, /me mock, home.es spec; 8 e2e pass; live SC4 pass |
| T7 | done | a0ba5ad0 | Landing in 6 components, 20 landing.* keys ES/PT, 360px no scroll; AppShell wordmark truncate (pending OK) |
| T8 | done | a6539f34 | newId() helper; chat works on http://nginx; 4 e2e pass |

<!-- IMPLEMENTER ZONE — append-only, written by the task agents. -->
## Task log

### T2 — Cardy's welcome
Created: `backend/app/domains/conversation/welcome.py` (`post_welcome`, `day_part`, `pick_body`), `backend/tests/unit/test_welcome.py`.
Changed: `templates.py` (`WELCOME_BODIES`, `WELCOME_SALUTATIONS`, `DayPart`; 8 bodies per language), `tools/registry.py` (`session_profile`), `api/v1/conversations.py` (`welcome: bool`, `WelcomeMessage`, `CreateConversationResponse.welcome`).
Facts the next tasks need: the welcome text is `"<salutation> <body>"`; route passes `body.language or "es"`; Redis key `welcome:last:<customer_id>`. OpenAPI changed (client regen is T3's).
Deviations: ES/PT first-turn tests are one parametrized `test_first_turn_after_welcome[es|pt]`.
Verify: pytest test_welcome + test_r1_routes -> 4 passed; digit check, ruff check/format, mypy all clean.

### T1 — `/me` read API
Created: `backend/app/api/v1/me.py` (router + `CardView`, `CardDetailsView`, `TxRow`, `TxPage`; pure `card_view`, `card_details_view(details, country)`, `tx_row(tx, country, masks)`), `tests/unit/test_me_views.py`, `tests/integration/test_r1_me_routes.py`.
Changed: `api/v1/__init__.py` (mounts `me_router`); `transactions/repository.py` (`_build_where` extracted, `_build_query` SQL unchanged; new `fetch_transactions_page`); `transactions/service.py` (`list_page`, `InvalidCursor(ValueError)`, cursor = urlsafe b64 of `<iso>|<tx_id>`).
Facts the next tasks need: 422 bodies are `{"detail":"invalid_filter"}` / `{"detail":"invalid_cursor"}`; 404 is `{"detail":"not_found"}`; `card_mask` comes from `list_cards`. Keyset with a cursor is not exercised by any test (fixtures have few rows); T3 live proof should page once.
Deviations: none.
Verify: unit 3 passed; integration `test_r1_me_routes` + `test_r1_postgres_tools` 2 passed; ruff check/format and mypy clean.

### T3 — Contract sync and live proof
Changed: `docs/solution-docs/04-contracts.md` §3 (amended `POST /conversations`; rows `GET /me/cards`, `/me/cards/{card_id}`, `/me/transactions`); `frontend/src/client/{index,sdk.gen,types.gen}.ts` regenerated (`WelcomeMessage`, `welcome`, 3 `/api/v1/me` URLs). Removed `frontend/openapi-ts-error-*.log`.
Facts the next tasks need: regeneration rewrites the other `client/` and `core/` files with LF only (CRLF-only noise), so I reverted those with `git checkout`; only the 3 files above differ. Run docker exec with `MSYS_NO_PATHCONV=1` under Git Bash.
Live proof (one persona, scratchpad script, nothing printed but statuses): two `{"welcome":true}` -> texts differ; `{}` -> `welcome: null`; first `app.messages` row role=`bot` (count 1) for both; foreign card -> `404 {"detail":"not_found"}`, unknown card -> same; `/me/cards` 200 (3 cards); `/me/transactions` page1 20 rows + next_cursor, page2 20 rows, tx_id overlap 0; `cursor=garbage` -> `422 {"detail":"invalid_cursor"}`.
Deviations: none.
Verify: lint-imports 4 kept, 0 broken; greps pass; `npm run typecheck` clean.

### T4 — Shared ChatView with eager welcome
Created: `frontend/src/components/chat/ChatView.tsx` (`ChatView({prefill?, className = "h-dvh"})`, exported).
Changed: `routes/chat.tsx` (guard + `<ChatView/>`); `Composer.tsx` (`prefill?`, effect replaces value, never sends); `lib/api.ts` (`createConversation(lang, {welcome?})` -> `{conversationId, welcome: string|null}`); `e2e/mock-api.ts` (exports `WELCOME_TEXT`; welcome only when body `welcome: true`); `session-expiry.es.spec.ts` (fresh chat: 1 bot, 0 customer).
Facts the next tasks need: create goes through `startConversation(withWelcome)` with an in-flight promise ref; mount with no stored id and "new conversation"/mismatch call it with welcome; lazy `ensureConversation` calls it without. `className` replaces the height class (layout classes are the host's). Only caller of `createConversation` was chat.tsx.
Deviations: none.
Verify: typecheck, biome ci, build clean; playwright 5 passed (4 specs).

### T5 — Banking home `/home`
Created: `frontend/src/routes/home.tsx`; `components/home/{HomeView,AlertsSection,CardsSection,BalanceSection,TransactionsSection,CardyPanel,Section,queries}.tsx` (`HomeView` is the route component; `queries.tsx` holds the shared TanStack hooks).
Changed: `lib/api.ts` (`listMyCards`, `getMyCard`, `listMyTransactions({cardId?,dateFrom?,dateTo?,cursor?})`); `i18n/es.json` + `pt.json` (57 `home.*` keys each, incl. `home.ask.*` prefill sentences).
Facts the next tasks need: test ids `home-cards`, `home-card`, `home-balance`, `home-transactions`, `home-tx-row`, `home-tx-more`, `home-alert`, `home-quick-action`, `cardy-launcher`, `cardy-panel`. `home-balance` card and tx/alert sections render regardless of state (states: skeleton `role=status`, error `role=alert`, empty text). Launcher hides while the panel is open; panel has a "Cerrar" button. Card/date filters are native selects/date inputs. `routeTree.gen.ts` is git-ignored and regenerated only by `npm run build`/dev server (run the build before typecheck after adding routes). The new files are LF; es/pt.json are LF in the working tree (git warns CRLF conversion).
Deviations: none.
Verify: typecheck, biome ci, build clean; grep for postMessage|postConfirmation|postSelection|Intl.|toLocale empty.

### T6 — Login to /home, e2e mock and home spec, live proof
Created: `frontend/e2e/home.es.spec.ts` (3 tests).
Changed: `routes/login.tsx` (navigates to `/home`); `e2e/mock-api.ts` (`/me/cards`, `/me/cards/{id}` 404 on unknown, `/me/transactions` with cursor -> page 2 -> `next_cursor: null`; credit `•••• 6475` $1,250.00, debit, blocked; Declined row dated now-24h); 5 login waits in block.pt, card-info.es, session-expiry.es (x2), unrecognized.es now `waitForURL("**/home")` + `goto("/chat")`.
Facts the next tasks need: live proof via `@playwright/test` chromium inside `latam-cs-frontend-1` against `http://nginx` (one DNI persona, nothing printed): lands on /home PASS; 2 masked cards PASS; balance section + usage elements PASS; 20 tx rows, "ver más" -> 40 PASS; PT toggle stays on /home, cards intact, button "Ver mais" PASS; launcher opens panel on /home with 1 welcome `message-bot` PASS; `/chat` full page with composer PASS. The running vite dev server had a stale route tree (no `/home`) until `docker restart latam-cs-frontend-1`. `crypto.randomUUID` is undefined on insecure `http://nginx` (works on localhost/https), so ChatView/AgentChat throw there; the proof polyfilled it in the harness only.
Deviations: none. Out of scope: `crypto.randomUUID` needs a secure context (pre-existing in staff AgentChat; chat path now also hits it on `http://nginx`).
Verify: typecheck + biome ci + build clean; playwright 8 passed (home x3, card-info, block.pt, unrecognized, session-expiry x2).

### T8 — Insecure-origin-safe UUID
Created: `frontend/src/lib/uuid.ts` (`newId()`).
Changed: `components/chat/ChatView.tsx` (4 calls), `components/staff/AgentChat.tsx` (2 calls) now use `newId()`; `randomUUID` remains only in `lib/uuid.ts`.
Facts the next tasks need: after editing, the vite dev server kept serving the stale transform until `docker restart latam-cs-frontend-1`.
Live proof (headless chromium in `latam-cs-frontend-1` against `http://nginx`, no polyfill, `typeof crypto.randomUUID` = undefined, one DNI persona): /chat shows 1 welcome `message-bot`, 0 console errors mention randomUUID -> PASS (1 unrelated console error, not investigated).
Deviations: playwright MCP not used; headless chromium used instead.
Verify: build + typecheck + biome ci (3 files) clean; playwright 4 passed; `! grep randomUUID --include=*.tsx` passes.

### T2 fix — welcome body 3 sentence count
Changed: `templates.py` body index 3 (ES and PT) shortened to 1 sentence plus no invitation question removed? No: now 1 sentence, "...tus movimientos." / "...suas transações." kept before nothing; see note below.
(Correction to the T2 fix note just above, which was malformed: body index 3 is now 2 sentences in ES and PT, "Soy Cardy, de Swip, y puedo ayudarte con tus tarjetas y tus movimientos. ¿Qué necesitas?" and its PT equivalent; the invitation is kept; all 16 bodies checked at 2 sentences.)
Verify: test_welcome + test_r1_routes -> 4 passed; digit check, ruff, mypy clean.

### T2 fix 2 — first-turn-after-welcome test rewritten
Changed: `backend/tests/unit/test_welcome.py` only. `test_first_turn_after_welcome[es|pt]` now posts the welcome with the SAME conversation_id as the `make_session` graph, runs the ES / PT card-status turn (NLU language = variant), asserts the expected card-status reply, debug.route/language, and stored roles [bot, customer, bot].
Facts: the graph keeps state in the checkpoint, not the message list, so no production seam was needed; the customer and bot-reply rows are written by the test through the patched `store.add_message` (the runner itself needs DB/Redis/audit and isn't driven).
Verify: test_welcome + test_r1_routes -> 4 passed; digit check, ruff, mypy clean.

### T7 — Swip landing at / (SwipLanding v2)
Created: `frontend/src/components/landing/{Nav,Hero,CardyShowcase,Footer,FloatingCardy,SoonButton}.tsx`; no assets (cards/stars/bubble are JSX+Tailwind), so no `public/landing/`.
Changed: `routes/index.tsx` (composes the sections only); `i18n/es.json` + `pt.json` (+20 `landing.*` keys each; `landing.title/subtitle/cta` kept; PT "Iniciar sesión" = existing `landing.cta` "Entrar"); `components/layout/AppShell.tsx` (wordmark `min-w-0 truncate`).
Token mappings for the PR (export -> token): #070B1A -> `bg-background`/`bg-bg`; #122038 -> `bg-card`; #0B1328 (cardy section) -> `bg-card/50`; #26385A -> `border-border`; #3DD6E0 -> `cyan`/`bg-primary`; #F5C66B -> `gold`; #A9B4CC -> `text-muted-foreground`; #F2F4FF -> `text-foreground`; #0F3440 -> `bg-cyan/20`. Plus Jakarta Sans -> `font-heading`; Inter -> `font-sans`. No Google Fonts link.
"Abre tu cuenta"/"Pide tu tarjeta" = disabled buttons + "Próximamente"/"Em breve" badge (`SoonButton`); all other CTAs are `<Link to="/login">`; floating Cardy is a link + static bubble (bubble hidden < sm), not a toggle; footer team "Yhorman Bedoya & Luisa Jiménez"; disclaimer kept.
Facts: the language toggle and starfield come from AppShell (landing has no second toggle). Landing nav sits below AppShell header.
Deviations: edited `AppShell.tsx` (not in task Files): its header overflowed 15px at 360px (scrollWidth 375) on every route; truncating the wordmark fixes it (now shows "Cardy, ..." at 360).
Screenshots (fullPage): C:/Users/USUARIO/AppData/Local/Temp/claude/c--Users-USUARIO-factored-hackathon-2026-inferencia-aplicada/0078ae58-15a8-4dd6-ba93-9e9b65c268d7/scratchpad/landing-{desktop,mobile}-{es,pt}.png (1280 and 360 px).
Verify: typecheck, biome ci, build clean; preview 4173 script: scrollWidth 360 at 360px (ES+PT), nav "Iniciar sesión" href "/login", 2 disabled buttons, 7 /login links. Preview has no API, so the header shows a bogus "Hola, {name}" there; not a landing issue.

### T7 repair — floating bubble vs hero bubble
Changed: `components/landing/FloatingCardy.tsx` only. An IntersectionObserver on `#inicio` (hero) hides the bubble (opacity-0, pointer-events-none, aria-hidden) while >= 50% of the hero is visible; 300ms opacity transition with `motion-reduce:transition-none`. The pill stays always visible and is still `<Link to="/login">`. 50% (not "any overlap") so a short desktop page can still reach the shown state.
Screenshots (scratchpad, non-fullPage 1280x800 ES): `landing-fold-es-top.png` (bubble hidden, no overlap), `landing-fold-es-scrolled.png` (bubble shown, hero bubble out of the way). The 4 fullPage shots were regenerated.
Verify: biome ci, typecheck, build clean; preview script: bubble opacity 0 at top, 1 after scroll; scrollWidth 360 at 360px (ES+PT); 7 /login links; 2 disabled buttons.

### T7 repair 2 — bubble hidden over the footer
`FloatingCardy.tsx` now also hides the bubble while the footer (`id="pie"` added in `Footer.tsx`) intersects; shown only between hero and footer. Verify re-run clean; bubble opacity top 0 / mid-page 1 / bottom 0; screenshots `landing-fold-es-{top,scrolled,bottom}.png` (scrolled = 1280x600, scroll 500).
