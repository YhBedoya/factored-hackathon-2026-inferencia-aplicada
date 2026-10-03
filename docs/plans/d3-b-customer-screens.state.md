# State: D3-B — customer screens
<!-- ORCHESTRATOR ZONE — you own this. Implementers never edit it. -->

## Card
Card D3-B (G5, owner B) · spec `docs/specs/d3-b-customer-screens.md` · plan `docs/plans/d3-b-customer-screens.md`
Branch `feat/d3-b-customer-screens`, based on `develop`.

## Conventions established for this card
- Facts checked against the repo: plan §"Facts checked against the repo". Read it before starting.
- Tasks run in parallel waves in the same checkout. Touch only the files in your task's list; never edit a sibling task's files or any lockfile unless your task owns it.
- Checkouts are CRLF (core.autocrlf=true). Frontend Verify reformats its own paths with Biome first.
- Never `git commit`, `git add` or push. The orchestrator commits at the gate.

## Human decisions taken mid-card
- Spec Q1a–Q4a: see spec D1–D8 (A2/A4 shapes proposed in 04 §3; mocked-API Playwright; click = label text; steps 3–7 at A6 pairing).
- Plan Q1b: all frontend commands (npm, Biome, tsc, Playwright) run in Docker; no host Node. Q2b: Makefile untouched, tsc only in CI. Q3a: OTP proven at A6 pairing.
- Verify: `make data` failed on the FK accounts→customers; human chose to fix it inside this card (T6, pipeline/load/postgres.py).
- Verify V4: block picker click re-asks (2 same-kind cards); human chose nlu@v4 inside this card (T7), proven with a live LLM call.

## Task board
| Task | Status | Agent | One-line result |
|---|---|---|---|
| T1 (wave 1) | done | a335acef | deps, shadcn, theme, ES/PT dict, api.ts, route stubs; build+typecheck green |
| T2 (wave 1) | done | adad7045 | card_picker + quick_replies events in 4 flows; 19 tests green |
| T3 (wave 2) | done | a0a1b8e9 | shell+stars, ES/PT toggle, logout, landing, RHF+zod login; biome+typecheck clean |
| T4 (wave 2) | done | aee088d0 | chat on SSE + picker, quick replies, confirm card, OTP modal; biome+typecheck clean |
| T5 (wave 3) | done | ab7deee1 | Playwright config, mock API + 5 SSE fixtures, 2 e2e specs green (2 passed), CI build + e2e jobs, actionlint clean |
| T6 (verify fix) | done | ac7015e5 | TRUNCATE also lists identity.accounts (only FK into bank.*); load + seed-identity exit 0 |
| T7 (verify fix) | done | adad7045 | nlu@v4: flow-agnostic pending card_hint rule; live card_block → last4:7723 (v3 gave "credit") |

<!-- IMPLEMENTER ZONE — append-only, written by the task agents. -->
## Task log

### T2 — Backend `card_picker`/`quick_replies` events + flow tests
Changed: `backend/app/domains/conversation/ui.py` (`PickerOption`, `CardPickerPayload`,
`CardPickerEvent`, `QuickRepliesPayload`, `QuickRepliesEvent`, added to `UIEvent`/`__all__`);
`flows/card_select.py` (`card_picker_event(outcome: Ask)` helper, added to `__all__`);
`flows/{card_info,card_block,card_unlock,replacement}.py` (each `Ask` branch adds
`"ui": [card_picker_event(outcome)]`; `card_block._ask_block_kind`'s clarify path adds
`QuickRepliesEvent(slot="block_kind", ...)`, its escalation path untouched);
`backend/tests/unit/test_card_info_flows.py` (`test_credit_balance_due` gains `es-mx-ask`/
`pt-mx-ask` cases, two-turn: `card_picker` labels checked, then posts the credit label as
turn-2 text); `backend/tests/unit/test_block_flows.py`
(`test_es_lock_clarify_confirm_readback` asserts `debug1.ui == ["quick_replies"]`, the
`block_kind` slot, two non-"cancel" labels, posts `labels[0]` as turn-2 text, asserts
`debug2.ui == ["confirm"]`). `docs/solution-docs/04-contracts.md` §3 already had the D1
shapes, the `quick_replies` kind and both payload lines (pre-existing uncommitted amendment
per plan's "Facts checked" note) — left as is, no content change needed.
Quick-reply labels (module constants in `card_block.py`, `_TEMPORARY_LOCK_LABEL`/
`_PERMANENT_BLOCK_LABEL`): ES "Bloqueo temporal" / "Reportar pérdida o robo"; PT "Bloqueio
temporário" / "Reportar perda ou roubo".
Facts the next tasks need: `card_picker_event(outcome)` lives in `flows/card_select.py`
and builds one `PickerOption` per `outcome.card_options` line; `ui` is a plain last-value
`GraphState` field (not a reducer), read via `(await graph.aget_state(config)).values["ui"]`.
Deviations: none.
Verify: `cd backend && uv run pytest tests/unit/test_card_info_flows.py tests/unit/test_block_flows.py tests/unit/test_card_select.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py -q && uv run ruff check ... && uv run ruff format --check ... && uv run mypy app/domains/conversation && uv run lint-imports && grep checks on 04-contracts.md` → 19 passed, all checks passed, no mypy issues, import-linter 4 kept/0 broken, all three greps matched.

### T1 — Frontend foundation
Changed: `frontend/package.json`/`package-lock.json` (deps + scripts), `components.json` (new,
shadcn `radix-nova` preset), `vite.config.ts` (`resolve.alias "@" -> ./src`), `tsconfig.json`/
`tsconfig.app.json` (`paths: {"@/*": ["./src/*"]}`, no `baseUrl` — TS ~6 deprecates bare
`baseUrl`, paths alone resolve relative to the tsconfig; `resolveJsonModule: true` added for
the i18n JSON imports), `biome.json` (`css.parser.tailwindDirectives: true` for the `@theme`/
`@apply` Tailwind v4 CSS syntax; ignores `test-results`/`playwright-report`), `src/index.css`
(brand `@theme` tokens + fonts, shadcn semantic vars mapped once onto the dark palette, no
`.dark` split — brand.md is a single always-dark theme), `src/main.tsx` (wraps in
`I18nProvider`), `.gitignore` (Playwright output dirs).
Created: `src/lib/i18n/{es.json,pt.json,index.tsx}`, `src/lib/api.ts`, `src/lib/utils.ts`
(shadcn `cn` re-export), `src/components/ui/{button,input,label,select,card,dialog}.tsx`,
`src/routes/{login,chat}.tsx` (stubs).
Facts the next tasks need:
- **Docker prefix confirmed working as written in the plan**, no mechanics fix needed:
  `MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W)/frontend:/app" -v d3b_frontend_node_modules:/app/node_modules[:ro] -w /app node:22.22-bookworm sh -c '<cmd>'`.
- `npm run typecheck` = `tsc -p tsconfig.app.json --noEmit`, no extra flags needed (writes
  nothing; `tsBuildInfoFile` in `tsconfig.app.json` is inert without `incremental`/`composite`).
- `@playwright/test` pinned to **1.63.0** (exact, `npm view` at install time).
- shadcn CLI is now `shadcn@4.21.0` ("Nova" registry), init command used:
  `npx shadcn@latest init -t vite -b radix -p nova -y` then
  `npx shadcn@latest add input label select card dialog -y`. It installs `cn` (shadcn's own
  clsx+tailwind-merge replacement, not separate `clsx`/`tailwind-merge` packages), `radix-ui`
  (one meta-package, not per-primitive `@radix-ui/*`), `class-variance-authority`,
  `lucide-react`, `tw-animate-css`, and `shadcn` itself as a runtime dep — all left as the CLI
  placed them. It also auto-added `@fontsource-variable/geist`, which was uninstalled (brand
  fonts are Inter/Plus Jakarta Sans, already installed manually per the task).
- `npm install <pkg>` needs `--legacy-peer-deps` in this repo right now: `@hookform/resolvers`
  pulls a peerOptional `@typeschema/zod@^3.23.8` while `@tanstack/router-plugin` pins
  `zod@^4.5.4` (already resolved). This is a real ERESOLVE, not a mistake — `@hookform/resolvers/zod` itself works with zod v4 directly. Once written into `package-lock.json`,
  plain `npm ci` (no flag) installs cleanly, so the Verify command's `npm ci` is unaffected.
- Final i18n key list (36 keys, identical in `es.json`/`pt.json`): `landing.title`,
  `landing.subtitle`, `landing.cta`, `lang.label`, `lang.es`, `lang.pt`, `login.title`,
  `login.document_type`, `login.document_type_options.DNI`, `login.document_type_options.CC`,
  `login.document_type_options.CE`, `login.document_type_options.Pasaporte`, `login.number`,
  `login.password`, `login.submit`, `shell.logout`, `shell.greeting` (`{name}`),
  `chat.placeholder`, `chat.send`, `chat.typing`, `chat.reconnecting`, `chat.closed_notice`,
  `chat.new_conversation`, `confirm.title`, `confirm.confirm`, `confirm.cancel`,
  `confirm.steps.lock_card`, `confirm.steps.block_card`, `confirm.steps.unlock_card`,
  `confirm.steps.order_replacement`, `otp.title`, `otp.description`, `otp.code`, `otp.submit`,
  `errors.invalid_credentials`, `errors.too_many_attempts`, `errors.generic`,
  `errors.required`, `errors.turn_failed`, `errors.turn_in_progress`,
  `errors.conversation_closed`, `errors.invalid_otp`. **Convention set**: every API/SSE error
  code (including OTP's) lives in one flat `errors.<code>` namespace, so a single
  `t(\`errors.${code}\`)` helper (fallback `errors.generic`) covers login, chat and the OTP
  modal — the spec's bare `invalid_otp` bullet was folded into this namespace as
  `errors.invalid_otp` rather than kept separate; T4 should read the OTP inline error from
  there, not a new `otp.invalid_otp` key.
- `src/lib/api.ts` exports: `ApiError{status,code}`, `login`, `logout`, `me`,
  `createConversation`, `postMessage`, `postResume`, `postConfirmation` (also exports
  `ConfirmationDecision = "confirm"|"cancel"`), `verifyOtp`, `conversationStore{get,set,clear}`.
  The three D1 wrappers go through `client.post` from `@/client/client.gen` with hand-typed
  response shapes; nothing in `src/client/` was touched. The CSRF interceptor is registered as
  a side effect of importing this module (`client.interceptors.request.use(...)`), so anything
  that calls the API must import from `@/lib/api`, not straight from `@/client`.
- shadcn `components.json` aliases: `ui -> @/components/ui`, `utils -> @/lib/utils` (the
  `cn` re-export), `components -> @/components`, `lib -> @/lib`.
Deviations: shadcn's current CLI output differs from the plan's illustrative package list
(`cn`/`radix-ui` meta-packages instead of `clsx`+`tailwind-merge`+individual `@radix-ui/*`);
kept as installed, see Facts above. `errors.invalid_otp` used instead of a bare `invalid_otp`
key (see Facts above) — a naming choice within "whatever keys the section needs", not a scope
change.
Verify: full Verify line run in Docker (`node:22.22-bookworm`, prefix unchanged from the plan)
→ `npm ci` clean, `biome check --write .` clean (0 fixes after the `css.parser.tailwindDirectives`
fix), `biome ci .` clean, `npm run build` green (routeTree.gen.ts has `/`, `/login`, `/chat`),
`npm run typecheck` clean and write-free; i18n key-diff script printed nothing (exit 0); all
four `--color-*` greps matched. `ALL_VERIFY_OK` printed.

### T3 — App shell, landing and login
Created: `src/components/layout/{AppShell,StarryBackground,LanguageToggle}.tsx`.
Changed: `src/routes/__root.tsx` (wraps `Outlet` in `AppShell`), `src/routes/index.tsx`
(landing page), `src/routes/login.tsx` (RHF + zod form, replaces the `null` stub).
`AppShell` owns the `me` `useQuery` under key `["me"]`, exported as
`ME_QUERY_KEY` for `login.tsx`'s post-login `invalidateQueries`; logout order is
`logout()` → `conversationStore.clear()` → `queryClient.setQueryData(ME_QUERY_KEY, null)` →
`navigate({to:"/login"})`. Login error mapping is a local `loginErrorMessage(t, code)`
helper (`invalid_credentials`/`too_many_attempts` → their dictionary string, anything
else → `errors.generic`), following T1's flat `errors.<code>` convention; T4 will need
its own copy for chat/OTP, there is no shared helper module.
No missing i18n keys: `landing.title` is reused as the header wordmark text (no new
"shell wordmark" key needed). `StarryBackground` is `fixed inset-0 z-0`, rendered once
in `AppShell` behind a `relative z-10` content wrapper — `index.tsx`/`login.tsx` don't
render their own stars, they inherit the shell's.
Deviations: none.
Verify: Biome `check --write` + `ci` on `src/routes/__root.tsx`, `src/routes/index.tsx`,
`src/routes/login.tsx`, `src/components/layout` (had to drop `role="group"`/`aria-label`
from `LanguageToggle`'s wrapper div — Biome a11y flagged both), plus the project-wide
`typecheck` filtered to those paths → clean, no errors in scope, `VERIFY_OK`/exit 0.

### T4 — Chat page, SSE stream, widgets
Created: `src/lib/sse.ts` (`openConversationStream`, exported types `PickerOption`,
`CardPickerPayload`/`Event`, `QuickRepliesPayload`/`Event`, `ConfirmStepView`,
`ConfirmPayload`, `ConfirmEvent`, `OtpRequiredPayload`/`Event`,
`ConversationClosedEvent`, `UiEvent` union, `StatusPayload`, `MessagePayload`,
`ErrorPayload`, `DonePayload`, `ConversationStreamHandlers`);
`src/components/chat/{MessageList,Composer,StatusIndicator,CardPicker,QuickReplies,
ConfirmCard,OtpModal}.tsx`. Changed (filled the T1 stub): `src/routes/chat.tsx`.
Real EventSource gotcha found and handled: the server's named `event: error` frame and
a genuine dropped connection both dispatch a DOM event of type `"error"` on
`EventSource` — `onerror` and `addEventListener("error", …)` would both fire for
either case, so `sse.ts` uses one `addEventListener("error", …)` that branches on
`event instanceof MessageEvent` (server frame → `onError`, else → `onReconnecting`);
`onopen` stays separate. `ui` events are held in a ref and attached to the next
`message`(role `"bot"`) as `TranscriptMessage.ui`; `otp_required`/`conversation_closed`
are still held there (per D12) but `MessageList` renders nothing for those two kinds —
they're surfaced instead by `OtpModal` (mounted on `otp_required`) and the
`new-conversation` banner (shown on `conversation_closed` or a `409 conversation_closed`
on `postMessage`/`postConfirmation`). `CardPicker`/`QuickReplies`/`ConfirmCard` each
disable themselves locally on first click (no parent-level "used" tracking needed).
`errorKey(code)` (local to `chat.tsx`, not shared with T3's `loginErrorMessage`, per
T3's note there's no shared helper module) maps `errors.<code>` with fallback
`errors.generic` for the same known set of D1 error/OTP codes.
Cut line: not needed — OtpModal shipped in this task, nothing deferred.
Facts the next tasks need: `sse.ts`'s `UiEvent` only covers the five kinds this card
renders (`card_picker`, `quick_replies`, `confirm`, `otp_required`,
`conversation_closed`); `transaction_list`/`handoff_banner` aren't typed yet, matching
backend `ui.py`. No i18n key was missing; all dictionary keys T4 needed were already in
T1's list.
Deviations: none.
Verify: Biome `check --write` + `ci` on `src/routes/chat.tsx`, `src/lib/sse.ts`,
`src/components/chat`, plus the project-wide `typecheck` filtered to those paths →
0 fixes on the second pass, no errors in scope, exit 0.

### T5 — Playwright config, mock, fixtures, e2e specs, CI
Created: `frontend/playwright.config.ts`; `frontend/e2e/mock-api.ts`
(`installMockApi(page, {password, fixtures, customer?})` → `{requests}`, a
stateful `page.route("**/api/v1/**", ...)` handler); `frontend/e2e/fixtures/
{card-info-ask,card-info-answer,block-clarify,block-confirm,block-verified}.sse`;
`frontend/e2e/{card-info.es.spec.ts,block.pt.spec.ts}`.
Changed: `.github/workflows/ci.yml` (`frontend` job gains a `build` step; new
`e2e` job, `container: mcr.microsoft.com/playwright:v1.63.0-noble`, `npm ci`
+ `npm run build` + `npx playwright test`).
Real bug found and fixed in this task's own files only: Playwright's Node 22
ESM loader needs an explicit import attribute for JSON imports in spec files
(`import es from "../src/lib/i18n/es.json" with { type: "json" }`), or it
throws `TypeError: needs an import attribute of "type: json"` at collection
time — Vite/`tsc` don't need this (`resolveJsonModule`), only Playwright's
own loader does. No i18n keys were missing (T3/T4 both recorded none), so
`es.json`/`pt.json` are untouched.
EventSource *is* intercepted by `page.route` on Chromium (plan's risk-6
open question): the mock fulfills every stream `GET` immediately with
`retry: 200\n\n: connected\n\n` + whatever `.sse` fixture text is queued
(maybe none), the finite body closes the connection, and `EventSource`'s
own reconnect drains newly-queued fixtures within ~200ms — no fake
`EventSource`, no deviation from D7.
Deviations: none.
Verify: full Verify line run — Node container (`npm ci`, `biome check --write`,
`biome ci .`, `npm run build`) clean, 2 files auto-fixed by Biome (the two
specs); i18n key-diff script printed nothing (exit 0); Playwright container
(`npm ci`, `npm run build`, `npx playwright test`) → `2 passed (3.2s)`;
`actionlint` on the repo → no findings, exit 0.

### T6 — Loader truncate fails on the FK from `identity.accounts` to `bank.customers`
Changed: `pipeline/load/postgres.py` (`copy_all`'s `TRUNCATE TABLE` statement
now also lists `identity.accounts`; docstring explains why).
FK scan of `latam_golden` (`pg_constraint`, `contype = 'f'`, whole DB): exactly
two FKs exist, `app.messages.conversation_id -> app.conversations.id` (unrelated)
and `identity.accounts.customer_id -> bank.customers.customer_id` — the only FK
into `bank.*`. Chose an explicit table list over `CASCADE`, since `CASCADE`
would silently follow any future FK too; the explicit list stays scoped to the
one FK found today.
Facts the next tasks need: `TABLES` (from `load/postgres.py`) is still exactly
the 13 `bank.*` tables; `identity.accounts` is appended only to the truncate
list, not to `copy_all`'s COPY loop or its return dict.
Deviations: none. Note for the orchestrator — `uv run python -m load` from a
bare shell needs `GOLDEN_DATABASE_URL`/`DATABASE_URL` exported from `.env`
first (`make data` gets these via the Makefile's `-include .env` + `export`);
this is a pre-existing env-loading fact, not a code change.
Verify: `cd pipeline && uv run ruff check load` → all checks passed;
`uv run python -m load` (env sourced from `.env`) → exit 0, row counts:
branches 350, customers 150000, daily_exchange_rates 13164,
marketing_campaigns 200, products 400000, service_agents 1200,
call_center_interactions 686296, call_transcripts 171321,
campaign_sends 1746801, complaints 67095, digital_events 15620994,
satisfaction_surveys 212759, transactions 4425008; `make seed-identity` → exit
0, last lines: `identity.accounts: 150000`, credentials.csv path printed,
`latam-cs-backend-1 Restarting` / `Started`.

### T7 — nlu@v4: flow-agnostic `card_hint` from a picker-label answer
Root cause confirmed live on `nlu@v3` (1 call): `card_block` pending +
"Crédito •••• 7723 · Activa" → `card_hint="credit"` (generic, ambiguous
between the persona's 2 credit cards), not `last4:7723`. `select_card`/
`_resolve_hint` (`card_select.py`) were already correct and flow-agnostic —
confirmed by direct call: `hint="last4:7723"` → `Selected`, `hint="credit"`
→ `Ask`. The only fix needed was in the NLU prompt.
Created: `backend/app/domains/conversation/prompts/nlu@v4.md` (v3 plus an
explicit flow-agnostic rule in "La pregunta pendiente" — a `card_hint`
answer containing `•••• NNNN` always gives `last4:NNNN`, whatever flow is
pending — and a new `card_block`-anchored worked example next to the
existing `card_info` one). `nlu@v3.md`/`v2`/`v1` left on disk untouched.
Changed: `backend/app/domains/conversation/nodes/understand.py`
(`_PROMPT = PromptRef("nlu", 4)`).
No test pinned `nlu@v3`/`PromptRef("nlu", 3)` (checked `backend/tests` and
`backend/scripts/nlu_smoke.py`); none needed updating. Note:
`scripts/nlu_smoke.py`'s `--dry-run` already pinned `PromptRef("nlu", 2)`
before this task (pre-existing drift from `nlu@v3`, not introduced here) —
left untouched, out of this task's file list.
Live calls used: 3 of 3 allowed (1 on v3 to confirm the hypothesis, 2 on v4
to prove the fix). No stack restart, no Redis/DB access (NLU is a pure LLM
call). Probe scripts were throwaway, run from the scratchpad, not added to
the repo.
Facts the next tasks need: `understand._PROMPT` is now `nlu@v4`; the prompt
loader (`prompts/__init__.py`) requires a matching `<name>@v<version>.md`
file to exist for every `PromptRef`, so any prompt bump must ship its file
before `understand.py` is bumped (they're commited together here).
Deviations: none.
Verify: `cd backend && uv run pytest tests/unit -q` → 59 passed; `uv run
ruff check app/domains/conversation/nodes/understand.py` (+ new prompt file,
markdown not ruff-checkable) → all checks passed; `uv run ruff format
--check app/domains/conversation/nodes/understand.py` → already formatted;
`uv run mypy app/domains/conversation/nodes/understand.py` → no issues;
`uv run lint-imports` → 4 kept, 0 broken. Live probe: `card_hint` observed
= `"credit"` (v3, card_block pending), `"last4:7723"` (v4, card_block
pending), `"last4:7723"` (v4, card_info pending, regression check).
