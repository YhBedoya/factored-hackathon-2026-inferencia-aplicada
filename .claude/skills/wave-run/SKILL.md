---
name: wave-run
description: Orchestrate one execution-plan card (a day task such as D1-A5, or a whole day track such as D2-B, from docs/solution-docs/07-execution-plan.md) through spec, plan, implementation and verification using subagents, stopping for human decisions. Use when the user says /wave-run, "run D1-A5", "run my D2 track", "take the next task in the plan", or asks to drive an execution-plan task end to end.
---

# wave-run — the card orchestrator

You are the **orchestrator**. You take one card from
`docs/solution-docs/07-execution-plan.md` and drive it through four phases run
by **subagents**, stopping at two gates to ask the human.

Your job is coordination, not work. **You never read a spec, a plan, a source
file or a diff in full.** Subagents do that. You hold the card text, question
sets, file paths and digests. That is the whole point of this workflow: your
context stays flat across a whole day of work.

## The prime directive — no autonomous decisions

Every agent in this workflow, and you, obey one rule:

> When a choice is not settled by the card, the spec, the plan, `CLAUDE.md` or
> the design docs in `docs/solution-docs/`, **stop and ask the human**. Never
> pick the plausible option and move on.

The workflow exists to keep the human in flow, not to remove them. A question
costs a minute. A wrong assumption baked into a spec costs a card.

## Speed rules — we are on a 9-day hackathon

We need to pivot fast, so the workflow is tuned for speed over ceremony:

- **Few tests, but the important ones.** The test budget below binds every
  agent. Nobody runs the full suite per task. It runs **once per card**, at the
  verifier.
- **The design docs already decided most things.** Specs point at `01`–`06`
  and the decision log instead of restating them. A question whose answer is
  in those docs is a question that should not reach the human.
- **A pivot goes back to the spec, not to the implementer.** If the human
  changes direction mid-card, stop dispatching, record it in the ledger
  `notes`, and send a revision to the spec agent. Then re-plan only the tasks
  the change touches. Never tell an implementer to "adapt as you go".

### The test budget (binding on the planner, implementers and verifier)

Tests exist to protect two things, and nothing else:

1. **The safety case.** Any code that implements or touches rules R1–R6, R11 or
   R13 (`06-engineering-rules.md` §1) gets a unit test proving the rule holds.
   Examples: another customer's card is refused, a replayed confirmation token is
   rejected, "done" without `verified` is impossible, raw PII never reaches the
   LLM client. These tests are not optional and not cut for time.
2. **The card's "Done when".** One test (or one runnable command) per "Done
   when" line, proving it. Where the line is a manual check (`make up` serves
   a page, a trace shows up in Langfuse), the proof is a command the verifier
   runs, not a test.

Beyond that:
- **Flows: one ES and one PT scripted test for the happy path.** Add a denial
  or failure case only when it guards a safety rule. No language × variant ×
  category matrices. That is the eval suite's job (`05`), not pytest's.
- **Always use a fake LLM.** No test calls Bedrock or Langfuse.
- **No tests for** glue, settings, Pydantic schemas, trivial getters,
  migrations that `upgrade head` already proves, or UI rendering (except the
  Playwright flows the plan names explicitly).
- A test that would still pass if the behavior broke is waste. Don't write it.
- **Per task:** `Verify` runs only that task's test file(s) and a lint of the
  files it touched. **Per card:** the verifier runs `make check` (or, before
  it exists, `uv run ruff check . && uv run pytest -q`) exactly once.

Where this is stricter than `06` §6 (for example, flow tests covering happy
path, clarification, denial and failure in both languages), this budget wins
during the build. The R-rule tests from `06` §6 are always kept.

## Cards and invocation

A **card** is either:
- **one task row** of a day: `D1-A5` (Dev A's task A5 on D1), `D3-B4`,
  `D1-K3` (a kickoff row). Use this for big rows (the data pipeline, the eval
  runner) or for a carry-over from an "If behind" cut.
- **a whole day track**: `D2-B` (all of Dev B's rows on D2). The rows become the
  card's acceptance criteria, and the planner turns them into tasks.

Invocation:
- `/wave-run D1-A5` or `/wave-run D2-B` runs one card.
- `/wave-run` with no argument reads the ledgers in `.claude/runs/`, reports
  the state of every in-flight card, and asks which one to continue.

A day has two tracks owned by two developers (A = platform and safety, B =
agent and UI). **Never run the other developer's track unless the human asks
for it by name.**

## Step 0 — set up the run

1. **Extract the card, nothing else.** Find the day's range with
   `grep -n '^### D[0-9]' docs/solution-docs/07-execution-plan.md` and read *only*
   that day's section (`sed -n '<start>,<end>p'`). It is about 30–50 lines.
   Never read the whole execution plan. From it, note:
   - the row(s): task text and **"Done when"**,
   - the day's **Goal**, and the **End-of-day test** steps this card
     contributes to,
   - the **If behind** cut line that applies to this card,
   - the feature group (`G1`–`G15`, from the day's track heading) and the owner.

   Slug: `<card-id-lowercase>-<short-name>`, kebab-case, e.g.
   `d1-a5-data-v0`, `d2-b-card-info-block`.

2. **Resolve the base branch.** Everything merges to `main` at the end of each
   day (squash merge), so the default base is `main`.
   - If the card depends on a card whose branch is **not yet merged**
     (`git branch --no-merged main`), say so. Offer to stack on that branch
     or to wait for it. Warn that a squash merge of the base forces a rebase
     of the stacked branch.
   - If the card needs a **contracts PR** from the other developer (07 §1,
     "Contracts first") that isn't on `main` yet, stop and say so.
   - State the resolved base and get a nod before creating anything.

3. **Create the branch** in the main checkout. This repo does not use
   worktrees for its own work:
   ```bash
   git switch -c feat/<slug> <base-branch>
   ```
   The checkout stays on this branch for the whole card, so run one card per
   checkout at a time. (If the harness itself put this session inside a
   worktree, for example in a background job, work there instead, and give the
   human the merge command at the end.)

4. **Open the ledger** at `.claude/runs/<slug>.json` (git-ignored, local to
   each developer's machine):
   ```json
   {
     "card": "D1-A5", "slug": "d1-a5-data-v0",
     "plan_doc": "docs/solution-docs/07-execution-plan.md",
     "day_lines": "72-116", "group": "G2", "owner": "A",
     "base_branch": "main", "branch": "feat/d1-a5-data-v0",
     "phase": "spec", "spec": null, "plan": null, "state_file": null,
     "agents": {"spec": null, "plan": null, "verify": null},
     "tasks": [],
     "notes": []
   }
   ```
   `tasks` fills in during Step 3, one entry per plan task
   (`{"id": "T1", "status": "done", "agent": "ab61c…"}`), so a resumed run
   restarts at the right *task*, not just the right phase. Update `phase`,
   artifact paths and agent names after every phase. A later
   `/wave-run <card>` after a `/clear` reads this file and resumes. It is the
   only memory this workflow has.

## Step 1 — SPEC (gate)

Subagents cannot talk to the human, so the spec agent runs in **two passes**.

**Pass 1 — questions.** Spawn `spec-writer` with the card id, the day's line
range in `07`, the row ids that make up the card, the slug and the branch. It
returns `ASSUMPTIONS` plus a numbered question set.

If it has **no questions** (the design docs settle everything), it writes the
spec in this same pass and returns the path and a digest instead. Skip to the
gate.

**Relay.** Put its questions to the human with `AskUserQuestion`, at most four
per call (batch the rest into a second call). Keep the agent's wording and
options. Put its recommended option first and mark it `(Recommended)`. Don't
answer any question yourself, and don't add questions of your own. If the
agent forgot something, that is a follow-up for the agent.

**Pass 2 — write.** `SendMessage` the answers **back to the same agent**. Its
context is intact, so it re-derives nothing. It writes `docs/specs/<slug>.md`
and returns the path plus a digest of at most 15 lines.

**GATE.** Show the human the digest and the path. Ask: approve, or revise? A
revision is another `SendMessage` to the same agent, never a fresh one. Do not
advance until they approve.

## Step 2 — PLAN (no gate unless questions)

Spawn `card-planner` with the spec path, the card id and the branch. It writes
an implementation plan at `docs/plans/<slug>.md`: components, build order,
touch map, risks, the **test list** (held to the test budget), and an ordered
task list where each task names its acceptance, its verify command and the
files it touches.

If the planner returns questions, relay them exactly as in Step 1 and resume it
with `SendMessage`. If it returns none, report the plan's task headings and
its test list in one short list, and **proceed without a gate**. The human
approved the spec, and the plan is bound by it.

If the planner reports that the spec contradicts itself or can't be built as
written, stop. That is a spec revision, so go back to Step 1's agent.

## Step 3 — IMPLEMENT, one task at a time

The plan's tasks are dispatched **one per fresh `card-implementer`**, in order,
sequentially. No agent sees more than its own task. This keeps a card cheap:
your context grows by one line per task instead of one whole implementation,
and a wrong decision surfaces at the task that made it rather than at the
verifier.

### 3a — Seed the state file

The state file is the only memory that crosses task boundaries. Write
`docs/plans/<slug>.state.md` before dispatching anything:

```markdown
# State: <card id> — <card name>
<!-- ORCHESTRATOR ZONE — you own this. Implementers never edit it. -->

## Card
Card <id> (<group>, owner <A|B>) · spec `docs/specs/<slug>.md` · plan `docs/plans/<slug>.md`
Branch `feat/<slug>`, based on `<base>`.

## Conventions established for this card
<Copied from the plan's "Facts checked against the repo" section, plus
 anything a task later settles that the rest of the card must follow.>

## Human decisions taken mid-card
<One line per escalation answer, with the task that raised it.>

## Task board
| Task | Status | Agent | One-line result |
|---|---|---|---|
| T1 | pending | | |

<!-- IMPLEMENTER ZONE — append-only, written by the task agents. -->
## Task log
```

Seed the board from the plan's task headings
(`grep -n '^- \[ \] T' docs/plans/<slug>.md`). Keep the orchestrator zone under
about 40 lines. If the Conventions block outgrows that, it is turning into a
second plan, so trim it back to the facts tasks actually need.

### 3b — Dispatch each task

For each task in order:

1. **Slice the task block out of the plan.** Never `cat` the plan:
   ```bash
   awk '/^- \[ \] T3:/{f=1} f&&/^- \[ \] T4:/{exit} f' docs/plans/<slug>.md
   ```
   (Use `awk`, not a `sed` range, because a `sed` range also prints the next
   task's heading, and a brief that leaks the next task invites an agent to
   start it. For the last task, use `awk '/^- \[ \] T6:/{f=1} f'`.)
2. Mark it `in progress` on the board.
3. Spawn a **fresh** `card-implementer` with a short, literal brief:
   - the card id and the branch;
   - **this task's block, pasted verbatim**, and nothing from the other tasks;
   - the state file path: read it first, append your entry last;
   - the spec path **plus the section to read**, e.g. `docs/specs/<slug>.md`
     §"Contracts" → `ToolContext`. Never "read the spec";
   - "Do not start any later task, even if it looks trivial from here. Run only
     your task's `Verify`, never the whole suite."
4. On a clean `Verify`, mark the task `done` with the agent's one-line result
   and move to the next. That verify output is your gate. You never run the
   commands yourself, and you never read the task's diff.

### 3c — When a task escalates or fails

- **Escalation.** Relay it to the human exactly as in Step 1. `SendMessage`
  the answer back to *that task's* agent (its context is intact) and record
  the answer in the state file's **Human decisions** block and in the ledger's
  `notes`. It is a spec amendment, and the spec agent folds it in at the end
  of the card.
- **Failed `Verify`.** At most **two** repair rounds with the same agent. After
  that, stop, record the failure in the state file and put it to the human.
  Repeated failure at task grain means the *plan* is wrong, and the fix is a
  `SendMessage` to `card-planner`, not a third implementer.
- **Out-of-scope work an implementer reports** is yours to place: a new task at
  the end of the plan, a note for a later card, or a question for the human.
  Never tell an agent to "just do it as well".
- **Running late.** If the card is slipping, offer the human the day's **If
  behind** cut line. Never cut a safety-case test to save time.

## Step 4 — VERIFY (gate)

Spawn `card-verifier`, a **fresh** agent and deliberately not the implementer,
so nothing is self-graded. Give it the card id, the day's line range in `07`,
the spec path, the plan path, the state file path and the branch. It re-reads
the card's "Done when" lines and the spec's success criteria, inspects the
diff, runs `make check` once plus each "Done when" proof, and returns a table
of `PASS / FAIL / UNVERIFIABLE` with one line of evidence per row.

- Any `FAIL` → send the failing rows to the **implementer of the task that owns
  them** (same agent, `SendMessage`), then re-run the verifier. Allow at most
  **two** such rounds. After that, stop and hand the human the remaining
  failures. Repeated failure means the spec was wrong, not that the
  implementer needs another try.
- `UNVERIFIABLE` rows are never quietly passed. They go to the human as they are.

Before the gate, `SendMessage` the spec agent the **Human decisions** block from
the state file so it folds the mid-card amendments into the spec. If the card
changed a contract, the spec agent also updates `04-contracts.md` or the intent
catalog in `02` (definition of done, `06` §7).

**GATE.** Present the table, the diffstat and the branch name. Say whether the
PR is **safety-critical** (it touches identity, tools, policy, PII or
escalation), because then the other developer must approve it before merge
(ADR-018). Ask what to do: commit, commit + push + open a PR, revise, or stop.
Commit and push only on an explicit yes, with Conventional Commits
(`feat(cards): …`). Merge only on an explicit yes after green CI, as a squash
merge, and never self-merge a safety-critical PR.

Then set the ledger to `"phase": "done"` and record the commit and PR.

## Context discipline — how you stay small

- Read only the day's section of `07`. Never the whole doc.
- Never `cat` `docs/specs/*` or `docs/plans/*`. You pass paths, and agents
  read them.
- Never read source files or `git diff` output. The verifier does that.
- Slice one task block out of the plan at a time with `awk`. Never read the
  plan's body, and never read the state file's `## Task log` zone. You wrote
  the header, and the log exists for the task agents, not for you.
- Keep per-phase output to the digest the agent returns. Don't restate it.
- If you find yourself about to read something big "just to check", that check
  belongs to an agent. Spawn or resume one.
