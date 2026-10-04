# Plan: "Swip Staff Caso" design on the case screen

Route: `/staff/handoffs/:handoffId`. Applies the attached design (`Swip Staff Caso.html`) to the existing screen. The backend, the API contracts and the return action stay as they are. Implemented directly in this session (not via `/wave-run`).

## Human decisions (2026-10-03)

| # | Topic | Decision |
|---|---|---|
| 1 | Return button | Keep the text "Devolver al bot" and the same action. Only the style changes (outlined pill). |
| 2 | Risk | Today's data: "Mención legal" without the word, and attempts only when > 0. Only the visual style changes (red block). |
| 3 | Routing | Motivo and cola stay translated. Rama and flujo are shown raw. All values in mono. |
| 4 | Responsive | Two columns from `lg`. Below that, one column with the card first (as today). |
| 5 | Labels | Use the design's text in ES and PT. The i18n keys keep their names. |
| 6 | Queue color | Reuse the inbox mapping (Atención cyan, Cobranza neutral, Fraudes red, Reclamos gold) by extracting it into a shared module. |
| 7 | "En vivo" | Reflects the real SSE state: "En vivo" (green dot) on `onOpen`, "Reconectando…" (gold dot) on `onReconnecting`. |

## Rules that still apply

- R4: every value (facts, evidence, score, mask, reference) is rendered **as the server sends it**. Nothing is reformatted. Values that come from a closed catalog (queue, reason, priority, status, role) are translated through the dictionary.
- A section with nothing to show isn't rendered, heading included.
- Keep the `data-testid` values that `e2e/staff.es.spec.ts` uses (`packet-view`, `packet-verified-fact`, `packet-action-case-id`, `packet-evidence`, `packet-open-question`, `agent-chat-input`, `agent-chat-send`, `return-handoff`) and the existing ones (`packet-meta`, `packet-routing`, `packet-risk`, `packet-history`, `packet-friction`, `packet-case-summary`, `packet-request`, `packet-focus-card`, `packet-conversation-link`, `agent-chat-message-<role>`).
- `frontend/src/lib/i18n/index.tsx` has uncommitted changes from the user. Don't overwrite it. If it needs touching, edit on top of them.

## Changes by file

### 1. `frontend/src/components/staff/queueStyles.ts` (new)
- Move `QUEUE_BAR` out of `InboxList.tsx` (bar = `bg-*`). Add a `QUEUE_CHIP` with the solid chip classes (`bg-alert text-bg`, `bg-cyan text-bg`, `bg-gold text-bg`, `bg-muted-foreground text-bg`).
- `InboxList.tsx` imports `QUEUE_BAR` from here. Its behavior doesn't change.

### 2. `frontend/src/routes/staff/handoffs.$handoffId.tsx`
- **Loading** (`!detail && !errorCode`): skeleton like the design: two columns. Left: a 160×16 strip, a `h-[60vh]` block and a 44px pill. Right: a `h-[70vh]` block. All `rounded-2xl bg-card animate-pulse`. Add `aria-busy="true"`.
- **Error**: as today (`role="alert"`, `text-alert`).
- Container: `max-w-[1150px] px-6 py-10`, grid `lg:grid-cols-2 gap-6 items-start`.
- Pass `reference={detail.summary.reference}` to `AgentChat`.
- Return button: pill `h-10 rounded-full border-muted-foreground px-[18px] font-semibold hover:border-foreground`. While returning (`returning`): label `staff.detail.returning` ("Devolviendo…") and `opacity-45`.
- Right column: `lg:sticky lg:top-22 lg:max-h-[calc(100vh-112px)] lg:overflow-y-auto`.

### 3. `frontend/src/components/staff/AgentChat.tsx`
- New prop `reference: string`. Header: `staff.chat.title` + ` · ` + reference on the left. On the right, the connection indicator: a state `"live" | "reconnecting" | "connecting"` set in `onOpen`/`onReconnecting`. Green dot (`bg-ok`) with `staff.chat.live`, or gold dot with `staff.chat.reconnecting`. Before the first `onOpen`, show nothing.
- Log: `h-[60vh] max-h-96 lg:max-h-none overflow-y-auto rounded-2xl border bg-[#0B1328] p-4 flex flex-col gap-3`. Auto-scroll to the end when messages change (a `ref`). The design's `#0B1328` color is added as a `--color-surface` token in `index.css` (see 6).
- Bubbles by role (label above, 12px semibold):
  - `customer`: left, `bg-card border-border`, radius `16px 16px 16px 4px`, label `text-muted-foreground`.
  - `bot`: left, `bg-[#0F3440]`, label `text-cyan`.
  - `agent`: right, `bg-cyan text-bg`, radius `16px 16px 4px 16px`, label `text-cyan`.
  - `system`: centered pill `rounded-full border px-3 py-1 text-muted-foreground`, no label.
  - Max width 80% (system 100%). `data-testid="agent-chat-message-<role>"` is kept.
- Composer: a `<form onSubmit>` (Enter sends). Pill input `h-11 rounded-full bg-surface px-4` with placeholder `staff.chat.placeholder`. Pill `Enviar` button `h-11 rounded-full px-[22px] font-semibold`. While sending: `staff.chat.sending`. Keep the rule that the server is the source of truth: no optimistic append.

### 4. `frontend/src/components/staff/PacketView.tsx`
- Card: `rounded-2xl border-border bg-card` (no shadcn ring). Header with `border-b px-[22px] pt-5 pb-[18px]`.
  - `h1` heading 20px: `staff.packet.title` · reference in mono 17px `text-cyan`.
  - Chips (`data-testid="packet-meta"` on the container): queue (solid `QUEUE_CHIP`), reason (`border-border`), priority (`border-gold text-gold`). The priority keeps the `staff.priority.<p>` key.
  - "Tomado por {name}" at 13px `text-muted-foreground`.
- Body `px-[22px] pt-5 pb-6 gap-4 text-sm`. Sections separated by `border-t pt-4` (except the first). Order as in the design:
  1. **Risk** (`packet-risk`), first, if there are items: a box `border-alert bg-alert/8 rounded-xl px-3.5 py-3`, title with a round "!" icon in red, items as chips `rounded-full border bg-surface text-xs`. Content as today (decision 2).
  2. **Case summary** (`packet-case-summary`): a `dl` with grid `130px 1fr`. The "Qué quedó pendiente" row is highlighted: `bg-[#0F3440] border-gold rounded-[10px] -mx-3 px-3 py-2.5`, label `text-gold font-semibold`, value semibold. The `request` fallback stays as is.
  3. **Focus card** (`packet-focus-card`): an 18×12 gold rectangle + the mask, as the server sends it.
  4. **Routing** (`packet-routing`): `key` (min 72px, muted) + value in mono 13px. Motivo/cola translated, rama/flujo raw.
  5. **Verified facts**: `fact:` in foreground, value muted, `(source)` in mono 12px.
  6. **Actions taken**: `✓` in `text-ok` + the tool in mono + the case IDs (the `packet-action-case-id` spans stay separate).
  7. **Evidence**: ref in mono + `(score)` in `text-gold` when there is one.
  8. **Open questions**: a cyan `?` + the text.
  9. **History**: reference/claim_id in mono + translated reason/status, or the claim's category/status.
  10. **Friction**: inline `key: value`, value semibold.
  11. Link `packet-conversation-link`: `text-cyan font-semibold underline underline-offset-3 hover:text-foreground`, with `border-t pt-4`.
- `PacketSection` is generalized to receive the separator and the list style.

### 5. i18n `es.json` / `pt.json` (same keys, design text)
- Update: `staff.packet.title` ("Paquete del caso" / "Pacote do caso"), `summary_asked` ("Qué pidió" / "O que pediu"), `summary_did` ("Qué se hizo" / "O que foi feito"), `summary_unfinished` ("Qué quedó pendiente" / "O que ficou pendente"), `routing` ("Ruteo" / "Roteamento"), `verified_facts` ("Hechos verificados" / "Fatos verificados"), `claimed_by` ("Tomado por {name}" / "Assumido por {name}"), `history` ("Historial" / "Histórico"), `chat.title` ("Chat con el cliente" / "Chat com o cliente"), and the PT for `evidence`, `open_questions`, `focus_card`, `friction`, `open_conversation` according to the design.
- Add: `staff.chat.placeholder`, `staff.chat.sending`, `staff.chat.live`, `staff.chat.reconnecting`, `staff.detail.returning`.
- Before editing, confirm whether `index.tsx` derives the `TKey` type from `es.json` (if so, the new keys only need to go into the JSON files).

### 6. `frontend/src/index.css`
- Add to `@theme`: `--color-surface: #0b1328;` (recessed chat background and inputs) and `--color-cyan-deep: #0f3440;` (Cardy bubble and the pending row). Document their use the same way the existing tokens are documented.

## Tests (minimal, per CLAUDE.md)
- `e2e/staff.es.spec.ts` must keep passing without changes (testids kept).
- One ES and one PT unit test of `PacketView` (render with a full packet: the queue chip has the queue's class, the pending row is present, risk shows up first, the score isn't reformatted).
- No new tests for the skeleton or the live indicator beyond a check that "En vivo" appears after `onOpen` in the AgentChat test, if one already exists.
- Checks: `cd frontend && npx biome ci . && npx tsc --noEmit`, and the touched tests. Visual check with Playwright at 1440 and 390 px (playwright runs inside Docker: use `http://nginx/...`; staff login is done by the user or with test credentials. Don't read `data/secrets/`).

## Out of scope
- Backend and contracts (legal word, return action).
- StaffNav (it already matches the design).
