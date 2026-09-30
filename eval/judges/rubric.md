# Judge rubric (D15, `05` §5)

Human-facing rubric for scoring one bot reply, given the customer turns that
came before it. Each of the four dimensions is pass/fail, plus one overall
pass/fail for the reply as a whole. `judge@v1` scores the same five booleans
by prompt; a human labeler uses this same rubric on the same item.

A reply can fail more than one dimension. **Overall** is not an average: mark
it fail whenever a customer would come away misinformed, unable to act, or
talked down to, even if only one dimension below is at fault.

## Grounding

**Pass:** every number, date, status or policy claim in the reply traces to a
fact actually shown earlier in the conversation (a tool result, a confirmed
action, a value the customer stated). The reply never invents an amount, a
date or a rule.

**Fail:** the reply states a balance, date or outcome that does not appear
anywhere in the preceding turns, or contradicts one that does.

- ES example (pass): the context shows a Pending transaction with
  `occurred_at` 2026-03-31; the reply says "se espera que se refleje el
  31 de marzo" — the date is exactly the one shown.
- PT example (fail): the context has no balance figure anywhere, but the
  reply says "seu saldo disponível é R$ 1.200" — that number was never shown.

## Tone

**Pass:** the reply is calm, respectful and reassuring, matching Cardy's
voice (`docs/brand.md`) — even when declining a request or explaining a
problem.

**Fail:** the reply is curt, blaming, sarcastic, or so effusive it reads as
insincere.

- ES example (pass): "Entiendo la preocupación por ese cargo; vamos a
  revisarlo juntos."
- PT example (fail): "Você deveria ter conferido isso antes de reclamar."

## Clarity

**Pass:** a customer with no banking background can act on the reply without
re-reading it: short sentences, one idea at a time, a clear next step when
one exists.

**Fail:** the reply buries the answer in jargon, runs several unrelated
ideas together, or leaves the customer unsure what to do next.

- ES example (pass): "Ese cargo sigue pendiente. Se espera que se confirme
  antes del 3 de abril. Si necesitas algo más, dime."
- PT example (fail): "O status transacional encontra-se em processamento
  susceptível a liquidação conforme o ciclo de conciliação do emissor."

## Register

**Pass:** the reply is in the expected language for the turn (`es` or `pt`,
never mixed), with vocabulary and phrasing a customer in that market would
recognize (no false cognates, no literal translation from the other
language).

**Fail:** the reply switches language mid-message, or uses a word/phrase a
native speaker of that variant would flag as foreign or wrong.

- ES example (pass): a Mexican customer gets "tu tarjeta" (not "vosotros"
  forms, not Portuguese words).
- PT example (fail): a Brazilian customer's reply says "Você pode verificar
  no seu **cartão de crédito**... la fatura" — mixing in a Spanish word
  mid-sentence.

## Overall

**Pass:** the reply is grounded, has an acceptable tone, is clear and is in
the right register — a customer who received exactly this message would be
correctly informed and know what happens next.

**Fail:** any single dimension above fails badly enough that the customer
is misinformed, stuck or made to feel worse than before the reply.
