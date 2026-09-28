# Plan: D3-B — G5 design and customer screens

Spec: [`docs/specs/d3-b-customer-screens.md`](../specs/d3-b-customer-screens.md) · Branch: `feat/d3-b-customer-screens`

## Human decisions taken at plan time

- **Q1 = (b), all frontend commands run in containers.** npm, Biome, tsc and Playwright run in Docker, with no host Node. The human starts Docker Desktop. See the "Containers" fact for the exact prefixes.
- **Q2 = (b), the Makefile is unchanged.** tsc runs only in the CI `frontend` job (`npm run build`). The verifier runs the container build by hand next to `make check`.
- **Q3 = (a), the Test list is unchanged.** The OTP shapes are pinned by the typed wrappers in `lib/api.ts`, and OTP is proven at the A6 pairing (end-of-day steps 3–4).

## Waves

| Wave | Tasks (parallel) | Why they can share the checkout |
|---|---|---|
| 1 | T1 ∥ T2 | T1 touches only `frontend/**` and the root `.gitignore`. T2 touches only `backend/**` and `04-contracts.md`. T1 runs npm/vite and T2 runs uv/pytest, so there is no shared cache, port or output dir. |
| 2 | T3 ∥ T4 | They have disjoint files. T1 owns every lockfile, dictionary, `api.ts`, `index.css`, `main.tsx` and the route stubs. Neither task runs `npm run build`, a dev server or `npm install`, so `dist/`, `routeTree.gen.ts` and `node_modules` are never written. Each task filters the project-wide typecheck to its own paths. |
| 3 | T5 | Serial. It needs both screens, it runs the only build and the e2e run, and it edits `ci.yml`. |

## Facts checked against the repo

- **Starting point.** The branch HEAD is `1f8e17b`, the same commit as `origin/develop` (PR #8 merged, which includes D2-A and D2-B). The working tree has `docs/solution-docs/04-contracts.md` **already amended but uncommitted**. It covers the D1 shapes for `/auth/otp/verify`, `/messages` (`{text}` xor `{resume:"step_up"}`) and `/confirmations/{token_id}` (`{decision}` → `202 {turn_id}`), the `ui.kind` list with `quick_replies`, and the `card_picker`/`quick_replies` payload lines. T2 only checks and commits it.
- **Environment.** `core.autocrlf=true`, so files are checked out with CRLF (`frontend/src/main.tsx` and `backend/.../ui.py` are CRLF on disk). Biome's formatter defaults to LF, so run `npx biome check --write <paths>` on the paths a task touched before `npx biome ci <paths>`. Git normalizes the line endings on commit, so this creates no content diff. GNU make 4.4.1 and uv are on PATH. For Node and Docker, see Q1.
- **Containers (Q1b).** Run everything from the repo root in Git Bash, with `MSYS_NO_PATHCONV=1` and `$(pwd -W)` (on Linux, `$PWD`).
  - **NODE (read-write)** is `MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W)/frontend:/app" -v d3b_frontend_node_modules:/app/node_modules -w /app node:22.22-bookworm sh -c '<cmd>'`. `node_modules` lives in the named volume `d3b_frontend_node_modules`, never in host `frontend/node_modules`.
  - **Only T1 and T5 write the volume**, and both are serial. T3 and T4 mount it `:ro`. Containers are unnamed (`--rm`), and no Verify publishes a port, so wave-2 siblings can run their container Verifies at the same time.
  - **Every dependency change goes through NODE** (`npm install <pkg>` / `npx shadcn@latest ...` inside the container). It writes `package*.json` through the bind mount.
  - **Playwright** runs in `mcr.microsoft.com/playwright:v<exact @playwright/test version>-noble`, with its own anonymous `/app/node_modules` volume and `npm ci` inside.
  - **The i18n key diff** runs on the host through `uv run --no-project python` (equivalent to the spec's `node -e` diff, since there is no host Node).
- **Backend: `ui.py`** (`app/domains/conversation/ui.py`). It has `ConfirmStepView{tool, summary_key, facts: list[Fact]}`, `ConfirmPayload{token_id, steps}`, `OtpRequiredPayload{tool}`, `ConfirmEvent`, `OtpRequiredEvent` and `ConversationClosedEvent`. All are frozen, and they are listed in `__all__`. `UIEvent = Annotated[ConfirmEvent | OtpRequiredEvent | ConversationClosedEvent, Field(discriminator="kind")]`. The module docstring says `card_picker` "arrive[s] with the cards that emit" it, and that line needs updating.
- **Backend: the `ui` channel.**
  - `nodes/load_session.py` resets `"ui": []` every turn. `ui` is a plain last-value field in `GraphState`.
  - `run_turn` returns `(reply, DebugInfo)`. `DebugInfo.ui` is this turn's list of kinds, read from the updates stream.
  - A test reads the payloads with `(await session.graph.aget_state(session.config)).values["ui"]` right after the turn, as `test_block_flows.py` does for `confirmation_token_id`.
  - `runner.py` publishes each `ui` event, then `message {role:"bot", text, sources:[]}`, then `debug` (outside prod), then `done {turn_id}`. On failure it publishes `error {code:"turn_failed"}` and then `done`. It publishes `status {step}` once per graph node.
- **Backend: `card_select.py`.** `Ask{options, card_options: str (newline-joined "Crédito •••• 6475 · Activa" lines), failures}`, built by `_build_card_options` from `kind_label`/`mask_card`/`status_label`. `ask_which_card_text(action, outcome, language)` exists.
- **Backend: `Ask` branches** (each returns `pending`/`clarification_failures`/`segments`):
  - `card_info.py` around line 103
  - `card_block.py` line 106
  - `card_unlock.py` line 102
  - `replacement.py` line 109
- **Backend: `clarify_lock_vs_block`.** The only emitter is `_ask_block_kind` in `card_block.py` (lines 145–158), reached from the Selected-without-`block_kind` path and from `_resume_block_kind`. `BlockKind = Literal["temporary_lock", "permanent_block"]`. The template text is in `templates.py` line 258. There is **no** `localization/lexicon/` directory on disk, so the two quick-reply labels are ES/PT string constants in `card_block.py`.
- **Backend: `summary_key` values.** `lock_card` and `block_card` (`card_block.py`), `unlock_card` (`card_unlock.py`) and `order_replacement` (`replacement.py`). The block confirm facts today are `[Fact(key="card_mask", value="•••• 6475", source=…)]`. `Fact` is `{key, value, source}`.
- **Backend: test harness.** `tests/conftest.py` has `ScriptedLLM({"nlu": [...], "compose": [...]})` and `make_session(customer_id, fakebank_dir, llm)`. Tests use no pytest-asyncio; they call `asyncio.run(...)`.
  - The multi-card persona is `CLI-TFMULTI00001`: credit `6475` Active (`PRD-TFM1CRED0001`), debit `1203` Active, and debit `9001` Closed. That gives two eligible options.
  - `test_card_info_flows.py::test_credit_balance_due` is parametrized over `es-mx-fx` (TFMULTI with `card_hint="credit"`, so Selected), `pt-co` and `pt-ar-dpd` (single-card personas). It already imports `kind_label`, `mask_card` and `status_label`.
  - `test_block_flows.py::test_es_lock_clarify_confirm_readback` turn 2 is `"quiero un bloqueo temporal"`, with scripted NLU `block_kind="temporary_lock"`.
- **API behaviour the frontend relies on** (on disk).
  - Errors are `{"detail": "<code>"}`: `401 invalid_credentials`, `429 too_many_attempts`, `401 session_expired`, `404 not_found`, `409 conversation_closed`, `409 turn_in_progress`.
  - CSRF means the `X-CSRF-Token` header must equal the `csrf_token` cookie on non-GET requests. Login is exempt.
  - Cookies are `SameSite=Lax`, with `Secure` in prod only.
  - SSE (`GET /api/v1/conversations/{id}/stream`) sends `: connected`, then `event: <name>\ndata: <json>\n\n` frames and `: ping` comments. The headers already include `X-Accel-Buffering: no`.
  - Dev Nginx serves the app and the API same-origin (`/` → Vite, `/api/` → backend).
- **Generated client** (`frontend/src/client/`, never hand-edited, excluded from Biome). The SDK has login, refresh, logout, me, createConversation (`{language?: 'es'|'pt'}` → `{conversation_id}`, `201`), postMessage (`PostMessageRequest{text}` only), stream and health.
  - It has **no** confirmations or otp-verify function, and no `resume`.
  - `client` is exported from `src/client/client.gen.ts`, with `baseUrl: false`, so URLs are relative.
  - This card does **not** run `make client`: SSE payloads aren't in OpenAPI, and the A2/A4 routes aren't on `develop`. `lib/api.ts` wraps the D1 routes by hand through the generic `client.post({url, body})` until A merges.
- **Frontend today.**
  - Stack: Vite 8, React 19, TanStack Router (file routes; the Vite plugin regenerates the **gitignored** `src/routeTree.gen.ts` on dev and build; `autoCodeSplitting`), TanStack Query, Tailwind v4 via `@tailwindcss/vite`, TypeScript `~6.0.2` (pinned because `@hey-api/openapi-ts` breaks on TS 7), and Biome 2.5 (tabs, double quotes, excludes `src/client` and `src/routeTree.gen.ts`).
  - `src/index.css` is only `@import "tailwindcss";`. The routes are `__root.tsx` (bare `<Outlet/>`) and `index.tsx` (`null`).
  - There is no `@/` alias, no `components.json`, no shadcn/Radix, no RHF/zod, no `@fontsource`, and no `@playwright/test`.
  - The scripts are `dev`, `build` (`vite build && tsc -b`) and `lint`, with no `preview` or `typecheck` script. `vite.config.ts` sets `server.port 5173` and `hmr.clientPort 80`.
- **CI and Makefile.** In `.github/workflows/ci.yml`, the `frontend` job runs `npm ci` then `npx biome ci .`, and there is no build or e2e job. Makefile `check` runs `cd frontend && npx biome ci .` last. The root `.gitignore` has `frontend/dist/` and `frontend/src/routeTree.gen.ts`, and no Playwright output dirs.
- **Brand** (`docs/brand.md` §Visual identity). The tokens are `bg #070B1A`, `cyan #3DD6E0` (Cardy, and verified actions), `gold #F5C66B` (needs confirmation) and `alert #FF6B6B`. Headings use Plus Jakarta Sans and body text uses Inter. Stars appear outside the chat area only.

## Components

1. **Backend UI events** (`backend/app/domains/conversation/ui.py`, `flows/card_select.py`, the four flows). They add the `card_picker` and `quick_replies` events, the `card_picker_event(outcome: Ask)` helper, and the emissions. They depend on the existing `Ask` and `_ask_block_kind`.
2. **Frontend foundation** (`frontend/`). It covers the deps and scripts, the `@/` alias, shadcn copies in `src/components/ui/`, brand `@theme` tokens and self-hosted fonts in `src/index.css`, and the full ES/PT dictionary with its React context in `src/lib/i18n/`. It also has `src/lib/api.ts`, the API wrapper: CSRF header, 401 → refresh once → `/login`, typed errors, the D1 wrappers and conversation-id storage. It includes the `/login` and `/chat` route stubs, so the route tree is fixed before wave 2.
3. **Shell, landing and login** (`src/routes/{__root,index,login}.tsx`, `src/components/layout/`). They depend on 2.
4. **Chat and widgets** (`src/routes/chat.tsx`, `src/lib/sse.ts`, `src/components/chat/`). They depend on 2, and are coded to the payload shapes in the spec's Contracts, not to 1 at runtime.
5. **E2E and CI** (`frontend/playwright.config.ts`, `frontend/e2e/`, `.github/workflows/ci.yml`). This depends on 3 and 4.

**Cross-task hooks.** These `data-testid` names are shared by T3, T4 and T5, so no task needs to read another task's files:
- Login (T3): `login-document-type`, `login-document-number`, `login-password`, `login-submit`, `login-error`.
- Shell (T3): `logout`, `lang-toggle` (one button or a two-option switch whose options are `lang-es` and `lang-pt`).
- Chat (T4): `composer-input`, `composer-send`, `status-indicator`, `reconnecting`, `message-customer`, `message-bot`, `card-picker-option`, `quick-reply-option`, `confirm-card`, `confirm-step`, `confirm-accept`, `confirm-cancel`, `otp-modal`, `otp-input`, `otp-submit`, `otp-error`, `new-conversation`.
- Colors: `message-bot` has a border in the `cyan` token (`rgb(61, 214, 224)`), and `confirm-card` has a border in the `gold` token (`rgb(245, 198, 107)`). T5 asserts both with `toHaveCSS("border-color", …)`.

## Build order

1. **T1 and T2 in parallel.** T1 is the foundation: every later frontend task imports its `api.ts`, i18n, shadcn copies and aliases, and relies on its route stubs and lockfile. T2 is independent backend work.
2. **T3 and T4 in parallel.** Both need T1, and neither needs the other. The chat guard and logout share only T1's `api.ts`/conversation store.
3. **T5** needs both screens and their test ids to run the e2e specs, and it runs the one full build.

## Touch map

| File | New / modified | Task | Change |
|---|---|---|---|
| `backend/app/domains/conversation/ui.py` | M | T2 | `PickerOption`, `CardPicker{Payload,Event}`, `QuickReplies{Payload,Event}`, the union, `__all__`, docstring |
| `backend/app/domains/conversation/flows/card_select.py` | M | T2 | `card_picker_event(outcome: Ask) -> CardPickerEvent` |
| `backend/app/domains/conversation/flows/{card_info,card_block,card_unlock,replacement}.py` | M | T2 | `Ask` branches add `"ui": [card_picker_event(outcome)]`. `card_block._ask_block_kind` adds `quick_replies` |
| `backend/tests/unit/test_card_info_flows.py`, `test_block_flows.py` | M | T2 | Extended cases |
| `docs/solution-docs/04-contracts.md` | M (already in the tree) | T2 | Check and commit |
| `frontend/package.json`, `package-lock.json`, `components.json` | M, M, new | T1 | Deps, `preview`/`typecheck` scripts, shadcn config |
| `frontend/vite.config.ts`, `tsconfig.json`, `tsconfig.app.json`, `biome.json` | M | T1 | `@/` alias, Playwright-output ignores |
| `.gitignore` | M | T1 | `frontend/test-results/`, `frontend/playwright-report/` |
| `frontend/src/index.css`, `src/main.tsx`, `src/lib/utils.ts` | M, M, new | T1 | `@theme` tokens and fonts, `I18nProvider`, shadcn `cn` |
| `frontend/src/lib/i18n/{es.json,pt.json,index.tsx}`, `src/lib/api.ts` | new | T1 | Dictionary and context, API wrapper |
| `frontend/src/components/ui/*` | new | T1 | shadcn copies (button, input, label, select, card, dialog) |
| `frontend/src/routes/login.tsx`, `chat.tsx` | new (stubs) | T1 | Filled by T3 and T4 |
| `frontend/src/routes/{__root,index,login}.tsx`, `src/components/layout/*` | M/new | T3 | Shell, stars, toggle, logout, landing, login form |
| `frontend/src/routes/chat.tsx`, `src/lib/sse.ts`, `src/components/chat/*` | M/new | T4 | Chat page, stream, widgets |
| `frontend/playwright.config.ts`, `frontend/e2e/**` | new | T5 | Config, mock helper, SSE fixtures, 2 specs |
| `.github/workflows/ci.yml` | M | T5 | `frontend` job gains `npm run build`, plus a new `e2e` job. The Makefile is unchanged (Q2b) |

## Risks and mitigations

1. **There is no host Node, and the Docker daemon must be up.** Per Q1b, every frontend Verify runs in containers (see the "Containers" fact). A concurrent install into the shared `node_modules` is avoided because only T1 and T5 write the volume, and T3 and T4 mount it read-only.
2. **CRLF checkouts make `biome ci` fail on untouched formatting.** Every frontend Verify runs `biome check --write` on its own paths first (see Facts).
3. **Parallel siblings clobber each other's build output.** A `vite build` regenerates `routeTree.gen.ts` and `dist/`. T1 creates every route file as a stub so the tree is final. T3 and T4 run **no** build or dev server, only Biome on their own paths and `npm run typecheck` filtered to their own paths. T5 runs the single build.
4. **The project-wide typecheck sees a sibling's half-written files.** T3 and T4 fail only on typecheck lines under their own paths (the `grep` in their Verify). Neither imports the other's modules. T5 runs the unfiltered build.
5. **A lockfile or dictionary edit in wave 2 races the sibling.** T1 installs every dep (including `@playwright/test`, pinned exactly) and writes every dictionary key. T3 and T4 must not touch `package*.json`, `es.json`/`pt.json`, `api.ts`, `index.css` or `main.tsx`. A key they find missing goes into the state file, and T5 adds it.
6. **EventSource under `page.route`.** `route.fulfill` delivers the whole body, and then the stream ends and EventSource reconnects, which would replay events. T5's mock is stateful: each mocked `POST` enqueues its fixture, and each stream `GET` drains the queue, with a short `retry:`. T4 keeps the composer gated on `done`, not on the stream being open, and "reconectando" is a non-blocking banner. If Chromium doesn't route EventSource through `page.route` at all, T5 stops and reports it, because a fake `EventSource` would deviate from spec D7.
7. **The D1 routes aren't in the generated client.** `api.ts` has hand-typed `postConfirmation`, `verifyOtp` and `postResume` over `client.post`, each commented "replace with the generated SDK after `make client` once A2/A4 merge". Nobody edits `src/client/`.
8. **The Playwright package and image versions drift apart.** T1 pins `@playwright/test` to an exact version and records it. T5 uses `mcr.microsoft.com/playwright:v<that>-noble` both locally and in the CI `container:`.
9. **R4/Boundaries: widgets built from bot text, or labels coming from the LLM.** T2 builds labels only from `Ask.card_options` and fixed constants, and its test asserts they equal the code-formatted lines. T4 renders only `ui` payload fields and never parses `message.text`.
10. **A quick-reply label collides with `deny`/`card_cancel`.** T2's test asserts that no `quick_replies` label contains `cancel` (case-insensitive).
11. **The OTP code leaks.** T4 keeps the code in modal-local state only. It is not added to the transcript, not put in sessionStorage and not logged. It is sent only to `verifyOtp`.
12. **Real credentials end up in e2e fixtures.** T5's mocks accept any input, and the specs type obviously fake values (`12345678`, `demo-pass`). gitleaks runs in CI.
13. **A stale `ui` in the checkpoint misleads a test.** T2 reads `values["ui"]` immediately after the turn under test and asserts `debug.ui` for the kinds.

## Tests

| Test | Task |
|---|---|
| `backend/tests/unit/test_card_info_flows.py::test_credit_balance_due` (new ES and PT multi-card `Ask` cases) | T2 |
| `backend/tests/unit/test_block_flows.py::test_es_lock_clarify_confirm_readback` (extended) | T2 |
| `frontend/e2e/card-info.es.spec.ts` | T5 |
| `frontend/e2e/block.pt.spec.ts` | T5 |

Proofs for the manual criteria (the verifier and human run them, and no test is written):
- **Criterion 1:** the key diff and the four `--color-*` greps, both in T1's Verify.
- **Criteria 2 and 3:** `make up`, then log in in the browser at `http://localhost/` as a seeded persona. Check the wrong-password path and logout. For criterion 3, `docker compose ... restart backend` shows "reconectando" and the next message is answered.
- **Criterion 7:** the end-of-day steps 1–2 in the browser. Steps 3–7 are marked "verified at A6 pairing" in the PR.

## Tasks

- [ ] T1 (wave 1, parallel with T2): Frontend foundation: deps, shadcn, alias, brand theme and fonts, the full ES/PT dictionary and context, the API wrapper, and route stubs
  - Depends on: nothing. Docker Desktop is running (Q1b).
  - Read exactly these: `docs/brand.md` (§Voice and tone, §Language rules, §Visual identity); spec §Decisions D1, D9–D12 and §Contracts; `frontend/src/client/client.gen.ts` + `frontend/src/client/sdk.gen.ts` (the generated `client` and SDK function names)
  - Acceptance:
    - **Deps** (`npm install`, which is the only lockfile change in the card):
      - `react-hook-form`, `zod`, `@hookform/resolvers`, `@fontsource/inter` and `@fontsource/plus-jakarta-sans`.
      - `@playwright/test`, pinned to an **exact** version with no caret. Write the version to the state file.
      - Whatever `npx shadcn@latest init` / `add button input label select card dialog` adds (cva, clsx, tailwind-merge, lucide-react, tw-animate-css, Radix).
      - Scripts `"preview": "vite preview"` and `"typecheck": "tsc -p tsconfig.app.json --noEmit"`. `typecheck` must write nothing: it runs over a read-only `node_modules` in T3 and T4. If TS rejects `tsBuildInfoFile` without `incremental`, add `--incremental false` or whatever flag makes it pass and write-free, and record the working command in the state file.
    - **Alias.** `@/*` → `src/*` in `tsconfig.json`, `tsconfig.app.json` and `vite.config.ts` (`resolve.alias`). `components.json` points at `src/components/ui` and `src/lib/utils.ts`.
    - **Theme** (`src/index.css`). Tailwind v4 `@theme` defines `--color-bg: #070B1A`, `--color-cyan: #3DD6E0`, `--color-gold: #F5C66B`, `--color-alert: #FF6B6B`, `--font-heading` (Plus Jakarta Sans) and `--font-sans` (Inter). The shadcn CSS variables are mapped onto a dark brand theme, and fonts are imported from `@fontsource`. There are no star styles here; T3 owns the stars.
    - **i18n** (`src/lib/i18n/es.json`, `pt.json`, `index.tsx`).
      - The dictionaries are flat, with identical key sets and values in the brand voice. `{name}`-style placeholders are allowed.
      - The keys cover:
        - landing: title, subtitle, CTA
        - lang toggle: label, `ES`, `PT`
        - login: title, document type label, the four document-type option labels, number, password, submit, `errors.invalid_credentials`, `errors.too_many_attempts`, `errors.generic`, required-field validation
        - shell: logout, greeting with `{name}`
        - chat: placeholder, send, typing ("Cardy está escribiendo…" / "Cardy está digitando…"), `reconnecting`, `errors.turn_failed`, `errors.turn_in_progress`, `errors.conversation_closed`, closed notice, new conversation
        - confirm: title, confirm, cancel, and `confirm.steps.lock_card|block_card|unlock_card|order_replacement`
        - OTP: title, description, code label, submit, `invalid_otp`
      - `index.tsx` exports `I18nProvider` and `useI18n()` → `{lang, setLang, t(key: TKey, vars?)}`, where `TKey = keyof typeof es`. The default language comes from `navigator.language` (`pt*` → `pt`, else `es`) unless localStorage `swip.lang` is set, and `setLang` persists it.
      - Record the final key list in the state file.
    - **API wrapper** (`src/lib/api.ts`).
      - It configures the generated `client` with a request interceptor that sets `X-CSRF-Token` from the `csrf_token` cookie on non-GET requests.
      - `ApiError{status, code}` takes its `code` from `detail`.
      - A 401 on anything except login and refresh calls `/auth/refresh` once and retries. A second 401 goes to `/login` (`window.location.assign`).
      - Typed exports: `login(body)`, `logout()`, `me(): Promise<MeResponse | null>` (`null` on 401, with no redirect), `createConversation(lang)`, `postMessage(id, text)`, and the hand-typed D1 wrappers `postResume(id)` (`{resume:"step_up"}`), `postConfirmation(id, tokenId, decision)` and `verifyOtp(code)`.
      - It also exports `conversationStore{get,set,clear}` over sessionStorage key `swip.conversation_id`.
    - **Wiring.** `main.tsx` wraps the app in `I18nProvider`.
    - **Route stubs.** `src/routes/login.tsx` and `src/routes/chat.tsx` exist as `createFileRoute("/login")` / `("/chat")` with a `null` component.
    - **Ignores.** `biome.json` and the root `.gitignore` ignore `frontend/test-results` and `frontend/playwright-report`.
    - **Verify results.** `npm run build` regenerates `routeTree.gen.ts` with `/`, `/login` and `/chat`, and the build is green.
  - Verify: `cd "$(git rev-parse --show-toplevel)" && MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W)/frontend:/app" -v d3b_frontend_node_modules:/app/node_modules -w /app node:22.22-bookworm sh -c 'npm ci && npx biome check --write . && npx biome ci . && npm run build && npm run typecheck' && uv run --no-project python -c "import json;a=json.load(open('frontend/src/lib/i18n/es.json',encoding='utf-8'));b=json.load(open('frontend/src/lib/i18n/pt.json',encoding='utf-8'));d=sorted(set(a)^set(b));print(*d,sep='
');raise SystemExit(1 if d else 0)" && grep -Eqi -- '--color-bg: *#070B1A' frontend/src/index.css && grep -Eqi -- '--color-cyan: *#3DD6E0' frontend/src/index.css && grep -Eqi -- '--color-gold: *#F5C66B' frontend/src/index.css && grep -Eqi -- '--color-alert: *#FF6B6B' frontend/src/index.css`
  - Files: `frontend/package.json`, `package-lock.json`, `components.json`, `vite.config.ts`, `tsconfig.json`, `tsconfig.app.json`, `biome.json`, `src/index.css`, `src/main.tsx`, `src/lib/{api.ts,utils.ts,i18n/*}`, `src/components/ui/*`, `src/routes/{login,chat}.tsx`, `.gitignore`. This is over five files by design: it is the one serial scaffolding task, so later tasks never touch shared files.

- [ ] T2 (wave 1, parallel with T1): Backend `card_picker` and `quick_replies` events with their flow tests, and commit the `04` §3 amendment
  - Depends on: nothing
  - Read exactly these: `backend/app/domains/conversation/ui.py`; `backend/app/domains/conversation/flows/card_select.py`; `backend/tests/unit/test_block_flows.py` (its first and last tests show the harness and the `aget_state` pattern)
  - Acceptance:
    - `ui.py` adds `PickerOption{label}`, `CardPickerPayload{options}`, `CardPickerEvent{kind: "card_picker"}`, `QuickRepliesPayload{slot: Literal["block_kind"], options}` and `QuickRepliesEvent{kind: "quick_replies"}`. All are frozen, as in spec §Contracts. They are added to `UIEvent` and `__all__`, and the docstring is updated.
    - `card_select.card_picker_event(outcome: Ask) -> CardPickerEvent` makes one `PickerOption` per line of `outcome.card_options`, and is added to `__all__`.
    - Each `Ask` branch in `card_info.py`, `card_block.py`, `card_unlock.py` and `replacement.py` adds `"ui": [card_picker_event(outcome)]`. `card_block._ask_block_kind` adds `"ui": [QuickRepliesEvent(...slot="block_kind", options=[temporary-lock label, permanent-block label])]` on its clarify path only, not on the escalation path.
    - The labels are module constants per language, worded from the `clarify_lock_vs_block` template (for example "Bloqueo temporal" / "Reportar pérdida o robo", and "Bloqueio temporário" / "Reportar perda ou roubo"). They never contain "cancel". Record the four strings in the state file.
    - **Card-info test.** `test_credit_balance_due` gains ES and PT cases for `CLI-TFMULTI00001` with no hint. Turn 1 asserts `debug.ui == ["card_picker"]`, and that the labels in `values["ui"][0].payload.options` equal the lines built with `kind_label`/`mask_card`/`status_label` for the two eligible cards (6475 credit, 1203 debit). Turn 2's text is the credit label, scripted NLU returns `card_hint="credit"`, and it asserts the same balance reply as the existing case.
    - **Block test.** `test_es_lock_clarify_confirm_readback` turn 1 asserts `debug1.ui == ["quick_replies"]`, `slot == "block_kind"`, two labels, and that no label contains "cancel". Turn 2's text is the temporary-lock label, not `"quiero un bloqueo temporal"`, and it asserts `debug2.ui == ["confirm"]`.
    - `04-contracts.md` §3 already contains the D1 shapes and the two kinds. Check it and commit it with this task, with no content change unless something is missing.
  - Verify: `cd backend && uv run pytest tests/unit/test_card_info_flows.py tests/unit/test_block_flows.py tests/unit/test_card_select.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py -q && uv run ruff check app/domains/conversation tests/unit/test_card_info_flows.py tests/unit/test_block_flows.py && uv run ruff format --check app/domains/conversation tests/unit/test_card_info_flows.py tests/unit/test_block_flows.py && uv run mypy app/domains/conversation && uv run lint-imports && grep -q "quick_replies" ../docs/solution-docs/04-contracts.md && grep -q 'resume: "step_up"' ../docs/solution-docs/04-contracts.md && grep -q "decision: confirm" ../docs/solution-docs/04-contracts.md`
  - Files: `backend/app/domains/conversation/ui.py`, `flows/card_select.py`, `flows/{card_info,card_block,card_unlock,replacement}.py`, `backend/tests/unit/test_card_info_flows.py`, `test_block_flows.py`, `docs/solution-docs/04-contracts.md`. These are small edits to one component plus its two tests, so they stay one task.

- [ ] T3 (wave 2, parallel with T4): App shell with stars, the language toggle and logout, plus the landing and the login form
  - Depends on: T1, for `@/components/ui/*`, `useI18n`, the `api.ts` exports (`login`, `logout`, `me`, `ApiError`, `conversationStore`) and the `/login` and `/chat` route stubs. The real names and the dictionary key list are in the state file.
  - Read exactly these: `docs/brand.md` §Visual identity; spec §Decisions D9–D11; this plan's §Components "Cross-task hooks"
  - Acceptance:
    - **`__root.tsx`** renders the shell with the `components/layout/*` pieces:
      - a starry background (CSS or SVG) behind the page. The chat panel from T4 is opaque, so the stars stay outside it.
      - a header with the Swip/Cardy wordmark in the heading font.
      - the ES | PT toggle (`lang-toggle`, `lang-es`, `lang-pt`), which calls `setLang`. It changes the chrome only.
      - when `me()` returns a customer, `display_name` and a `logout` button. Logout calls `logout()`, then `conversationStore.clear()`, then navigates to `/login`.
    - **`index.tsx`** is the landing page (title, subtitle, CTA to `/login`) with the stars.
    - **`login.tsx`** is an RHF + zod form:
      - Fields: `document_type` (DNI | CC | CE | Pasaporte, labels from the dictionary), number and password.
      - On success, invalidate the `me` query and navigate to `/chat`.
      - `invalid_credentials` / `too_many_attempts` / other errors show the dictionary string in `login-error` with the `alert` color.
      - No document number is shown anywhere except `login_hint`.
    - Every string comes from `t()`. Don't touch any T1-owned file (`package*.json`, the dictionaries, `api.ts`, `index.css`, `main.tsx`). If a key is missing, record it in the state file.
    - Don't run `npm run build`, `npm run dev` or `npm install`.
  - Verify: `cd "$(git rev-parse --show-toplevel)" && MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W)/frontend:/app" -v d3b_frontend_node_modules:/app/node_modules:ro -w /app node:22.22-bookworm sh -c 'npx biome check --write src/routes/__root.tsx src/routes/index.tsx src/routes/login.tsx src/components/layout && npx biome ci src/routes/__root.tsx src/routes/index.tsx src/routes/login.tsx src/components/layout && (npm run -s typecheck > .tc-t3.txt 2>&1; ! grep -E "src/(routes/(__root|index|login)\.tsx|components/layout/)" .tc-t3.txt) && rm .tc-t3.txt'`
  - Files: `frontend/src/routes/__root.tsx`, `src/routes/index.tsx`, `src/routes/login.tsx`, `src/components/layout/{AppShell,StarryBackground,LanguageToggle}.tsx`

- [ ] T4 (wave 2, parallel with T3): Chat page on the SSE stream, with the card picker, quick replies, confirm card and OTP modal
  - Depends on: T1, for `@/components/ui/*`, `useI18n`, the `api.ts` exports (`me`, `createConversation`, `postMessage`, `postResume`, `postConfirmation`, `verifyOtp`, `ApiError`, `conversationStore`) and the `/chat` route stub. The real names and the dictionary key list are in the state file.
  - Read exactly these: spec §Decisions D2–D6 and D12, §Contracts, §Boundaries; `docs/solution-docs/04-contracts.md` §3 "SSE events" paragraph and the `ui.confirm` payload line; this plan's §Components "Cross-task hooks"
  - Acceptance:
    - **Guard.** `chat.tsx` has `beforeLoad` redirect to `/login` when `me()` is `null`. It renders an opaque chat panel with the brand bg.
    - **Conversation.** Reuse `conversationStore.get()`, or `createConversation(lang)` on first send (`lang` from `useI18n`) and store it. Open the stream before the first `postMessage`.
    - **Stream** (`lib/sse.ts`). A typed native `EventSource` on `/api/v1/conversations/{id}/stream` with listeners for `status`, `message`, `ui`, `error` and `done`. `debug` and `mode` are ignored. `onerror` shows `reconnecting` and `onopen` clears it. EventSource reconnects by itself, with no replay. It exports TS types for the five `ui` kinds, mirroring spec §Contracts and `04` §3.
    - **Transcript.**
      - The customer bubble (`message-customer`) is added optimistically.
      - Any `status` shows one typing indicator (`status-indicator`) until `message`.
      - `ui` events are held and attached to the next `message`.
      - A bot bubble (`message-bot`) has a cyan border.
      - `done` re-enables the composer. The composer is gated on `done`, not on the stream being open, and `reconnecting` is a non-blocking banner.
      - `error` and the `409` codes show dictionary strings.
      - On `ui.conversation_closed` or `409 conversation_closed`, show `new-conversation`, which clears the store and starts fresh.
    - **Widgets.**
      - `CardPicker` (`card-picker-option`) and `QuickReplies` (`quick-reply-option`) render the payload `label`s. A click sends that label exactly as typed text, with the same optimistic bubble, then disables the widget.
      - `ConfirmCard` (`confirm-card`, gold border) lists every `steps[]` entry (`confirm-step`). The title is `t("confirm.steps."+summary_key)`, and the `facts` values are shown as received.
      - `confirm-accept` / `confirm-cancel` are real buttons that call `postConfirmation(id, token_id, decision)`, and both disable after the first click.
      - `OtpModal` (`otp-modal`, `otp-input`, `otp-submit`, `otp-error`) opens on `ui.otp_required`. It calls `verifyOtp(code)`: on success it calls `postResume(id)` and closes, and on `invalid_otp` it shows the inline error and stays open. The code never enters the transcript or storage, and is never logged.
    - Never parse `message.text` to build a widget. Every string comes from `t()`. Don't touch T1-owned files. If a key is missing, record it in the state file.
    - Don't run `npm run build`, `npm run dev` or `npm install`.
    - **Cut line:** if behind, `OtpModal` is the part that moves to D4 morning. Record that in the state file.
  - Verify: `cd "$(git rev-parse --show-toplevel)" && MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W)/frontend:/app" -v d3b_frontend_node_modules:/app/node_modules:ro -w /app node:22.22-bookworm sh -c 'npx biome check --write src/routes/chat.tsx src/lib/sse.ts src/components/chat && npx biome ci src/routes/chat.tsx src/lib/sse.ts src/components/chat && (npm run -s typecheck > .tc-t4.txt 2>&1; ! grep -E "src/(routes/chat\.tsx|lib/sse\.ts|components/chat/)" .tc-t4.txt) && rm .tc-t4.txt'`
  - Files: `frontend/src/routes/chat.tsx`, `src/lib/sse.ts`, `src/components/chat/{MessageList,Composer,StatusIndicator,CardPicker,QuickReplies,ConfirmCard,OtpModal}.tsx`. This is over five files, but they are one component that is small per file. It stays one task per the minimum-tasks rule.

- [ ] T5 (wave 3): Playwright config, API mock and SSE fixtures, the two e2e specs, the CI build and e2e jobs, and the full frontend proof
  - Depends on: T1, for the pinned `@playwright/test` version, the `preview` script and the dictionary files. It also needs T3 and T4, for the screens and the test ids in §Components. Real names and any missing dictionary keys are in the state file.
  - Read exactly these: spec §Decisions D1, D6, D7 and D12, and §Test list; this plan's §Components "Cross-task hooks" and §Risks items 6, 8 and 12; `.github/workflows/ci.yml`
  - Acceptance:
    - **Config.** `playwright.config.ts` sets `testDir: "e2e"`, chromium only, `baseURL: http://localhost:4173`, `webServer: npm run preview -- --port 4173 --strictPort` (with `reuseExistingServer: !process.env.CI`), `forbidOnly: !!process.env.CI` and no retries.
    - **Mock** (`e2e/mock-api.ts`). A stateful `page.route` mock of `/api/v1/**`:
      - `/auth/me` is `401` until login, then `MeResponse` (`login_hint: "DNI ••••678"`).
      - `/auth/login` returns `200` and sets `csrf_token` through `context.addCookies`. A configurable password answers `401 invalid_credentials`.
      - `/auth/logout` returns `204`, `POST /conversations` returns `201`, and `/messages` and `/confirmations/*` return `202 {turn_id}`, each enqueuing the next `.sse` fixture.
      - The stream `GET` fulfills `text/event-stream` with `retry: 200`, `: connected` and the drained queue.
      - It records request bodies for assertions.
    - **Fixtures** (`e2e/fixtures/*.sse`) mirror the real frames (`event: <name>\ndata: <json>`): `status`, then `ui`, then `message`, then `done`.
    - **`card-info.es.spec.ts`** (`locale: "es-ES"`). The UI is in ES (compare against `es.json` values imported in the spec). Log in, reach `/chat`, and send "¿cuánto debo de mi tarjeta de crédito?". The picker appears. Clicking `card-picker-option` "Crédito •••• 6475 · Activa" sends a recorded `POST /messages` body equal to `{text: <label>}`, and the answer renders. `lang-pt` switches the chrome to the `pt.json` strings. `logout` leads to `/login`, and `/chat` then redirects to `/login`.
    - **`block.pt.spec.ts`** (`locale: "pt-BR"`). Log in and send "quero bloquear meu cartão". Clicking the `quick-reply-option` sends its label. Then `confirm-card` renders with a gold border and one `confirm-step`. Clicking `confirm-accept` hits `POST …/confirmations/<fixture token_id>` with `{decision:"confirm"}`. The verified reply renders in a `message-bot` with a cyan border.
    - Fixtures use fake values only. No LLM or network is involved.
    - **CI** (`ci.yml`). The `frontend` job gains `npm run build`. A new `e2e` job runs in `container: mcr.microsoft.com/playwright:v<pinned>-noble` with `npm ci`, `npm run build` and `npx playwright test`.
    - Add any dictionary keys T3 or T4 recorded as missing, to both files.
  - Verify: `cd "$(git rev-parse --show-toplevel)" && MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W)/frontend:/app" -v d3b_frontend_node_modules:/app/node_modules -w /app node:22.22-bookworm sh -c 'npm ci && npx biome check --write e2e playwright.config.ts && npx biome ci . && npm run build' && uv run --no-project python -c "import json;a=json.load(open('frontend/src/lib/i18n/es.json',encoding='utf-8'));b=json.load(open('frontend/src/lib/i18n/pt.json',encoding='utf-8'));d=sorted(set(a)^set(b));print(*d,sep='
');raise SystemExit(1 if d else 0)" && MSYS_NO_PATHCONV=1 docker run --rm --ipc=host -v "$(pwd -W)/frontend:/app" -v /app/node_modules -w /app mcr.microsoft.com/playwright:v$(uv run --no-project python -c "import json;print(json.load(open('frontend/package.json'))['devDependencies']['@playwright/test'])")-noble sh -c 'npm ci && npm run build && npx playwright test' && MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W):/repo" -w /repo rhysd/actionlint:latest -color`
  - Files: `frontend/playwright.config.ts`, `frontend/e2e/{mock-api.ts,card-info.es.spec.ts,block.pt.spec.ts,fixtures/*.sse}`, `.github/workflows/ci.yml`, and the i18n files only when a missing key was recorded

- [ ] T6 (added at verify, human decision): Loader truncate fails on the FK from `identity.accounts` to `bank.customers`
  - Depends on: nothing. Found during verification: `make data` fails at `pipeline/load/postgres.py:54` with `cannot truncate a table referenced in a foreign key constraint (accounts → customers)`, because migration `0002` adds `identity.accounts` with an FK to `bank.customers`.
  - Acceptance: the loader's truncate succeeds on a DB where migration `0002` is applied. `make seed-identity`, which `make data` runs right after the load, re-provisions `identity.accounts`, so emptying it on reload is expected. Before choosing between an explicit table list and `CASCADE`, list every FK into `bank.*` in `latam_golden`. Record the choice and the FK list in the state file. Update the `copy_all` docstring.
  - Verify: `cd pipeline && uv run ruff check load && uv run python -m load && cd .. && make seed-identity`, all exit 0.
  - Files: `pipeline/load/postgres.py` only.

- [ ] T7 (added at verify, human decision): NLU resolves a picker label to `last4` in every flow, not only `card_info`
  - Depends on: V4 FAIL. In the block flow, clicking "Crédito •••• 7723 · Activa" for a customer with two credit cards re-asks which card. Diagnosis: `select_card` is correct. The only example in `prompts/nlu@v3.md` that resolves a pending `card_hint` answer is anchored to `flujo 'card_info'`, so NLU likely returns a coarse hint (or none) when `pending.flow` is `card_block`, `card_unlock` or `replacement`.
  - Acceptance: first confirm the hypothesis with ONE live NLU call on v3, using the `card_block` pending context and the label text, and record the `card_hint` it returns. Add `prompts/nlu@v4.md` (v3 plus a flow-agnostic rule and example: an answer to a pending `card_hint` that contains `•••• NNNN` gives `last4:NNNN`, whatever flow is pending). Bump `understand.py` `_PROMPT` to `PromptRef("nlu", 4)`. Keep v3 on disk. Update any test or fixture that pins the NLU prompt version. With v4, the same live call returns `last4:7723` for `card_block`, and a `card_info` pending call still returns `last4`.
  - Verify: the unit tests that reference the NLU prompt, `uv run ruff check` on the touched files, `uv run lint-imports`, and the two live NLU calls above (at most 3 live calls in total).
  - Files: `backend/app/domains/conversation/prompts/nlu@v4.md` (new), `backend/app/domains/conversation/nodes/understand.py`, plus any test that pins the NLU prompt version.
