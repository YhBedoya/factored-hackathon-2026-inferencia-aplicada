Card support shortlist

Identity & session
- [MVP · Rules] Mock identity provider and session token: Customers sign in through a test identity service. Every tool reads the customer from the server session, never from the chat.
Note> There is a landing page and a login page where the user must sign in for all the actions that required the identity verified.
- [MVP · Rules] Session expiry and resume: If the token expires mid-flow, the system asks the customer to sign in again and resumes the pending step without repeating questions.
- [MVP · Hybrid] Card picker: When a customer has several cards, ask which one and show masked options such as "Crédito •••• 6475 · Activa" and "Débito •••• 1203 · Bloqueada".
Transactions
- [MVP · Hybrid] Decline explainer: Map response codes 51, 14, 05 and 54 to a plain-language cause and a next step. Rules pick the explanation and the LLM only phrases it.
- [MVP · LLM] Natural-language transaction search: Turn "el cargo de Oxxo del martes pasado por unos 350" into a structured filter: date range, fuzzy merchant, amount ±10%, currency. Relative dates use the customer's time zone.
- [MVP · Rules] Pending and reversed explainer: Explain why a hold is showing, when it should drop, and why a reversal appears as two lines.
- [Stretch · Rules] Duplicate-charge detector: Same merchant and amount within a few minutes: offer to open a pre-filled dispute.
Blocks & card controls
- [MVP · Rules] Instant lost/stolen block: Confirm the card, confirm the action, call the block tool, then read back product_status = Blocked before telling the customer it's done.
- [MVP · Hybrid] Temporary lock vs permanent block: "Bloquear" is ambiguous. Ask whether to pause the card or cancel and replace it. This is a natural ambiguous case for the demo.
- [MVP · Rules] Unblock with reason check: If the customer locked the card, unlock it if the user requires and he is loged in. If the bank blocked it (fraud, days past due, Suspended), no self-service: hand off to Fraudes or Cobranza.
- [MVP · Hybrid] Suspected-fraud triage: "No reconozco estas compras": list recent transactions with fraud_score, block the card, draft the claim and route to Fraudes with a handoff packet.
- [Stretch · Rules] Travel notice: Register destination countries and dates to prevent declines abroad, which do occur in the data.
- [Stretch · Rules] Spending limits: Set daily ATM and purchase caps within bounds set by policy, never by the model.
Card information
- [Stretch · Rules] Card Doctor: One diagnostic that checks status, expiry, available credit, channel toggles, travel notice and the last decline code, then gives one answer to "why isn't my card working?"
- [MVP · Rules] Card status and details: Masked number, status, expiry date, credit limit, available credit (limit − balance) and interest rate, each cited to the product record.
- [MVP · Rules] Balance, due date and minimum payment: The balance and days_past_due come from the data. The minimum payment comes from a labeled synthetic policy formula, because the data has no such field.
- [Stretch · Rules] Expiry and renewal: For cards expiring within 60 days, say when the new card ships (simulated) and what to update for automatic payments.
- [Stretch · LLM] Benefits by segment: Explain Premium, Plus, Basic and Student card benefits from the synthetic catalog.
Card lifecycle
- [MVP · Rules] Replacement and reissue: After a block, order a replacement. Confirm the delivery address, and require step-up for an address change. Returns a simulated tracking ID.
- [Stretch · Rules] New card activation: Last four digits plus OTP, then read back status = Active.
- [Stretch · Rules] PIN reset: Never show a PIN in chat. Send a reset link through a verified channel (simulated).
- [Stretch · Hybrid] Cancel with a retention offer: Retention contacts resolve only 60% on first contact. Make one offer, and only if accepts_marketing allows it, then cancel or route to a Retención agent.
- [Stretch · Hybrid] Credit limit increase request: The model only collects details and explains the outcome. A synthetic policy service decides, and borderline cases go to a Créditos agent.
Ask for a credit card
- [Stretch · Hybrid] Card finder: Three questions (use, income range, travel), then a side-by-side comparison of cards from the synthetic catalog.
- [Stretch · Hybrid] Pre-qualification through a policy service: Three separate parts: an ML risk estimate, labeled-synthetic eligibility rules, and an LLM that only explains reason codes. It never approves credit.
- [Stretch · Rules] Missing-income path: About 20% of customers have no income value. Ask for it and mark it self-declared, or send the case to human review. Never guess.
Disputes & claims
- [MVP · Hybrid] Unrecognized-charge intake: The top complaint subcategory. The customer picks the transaction, amount, currency and date are filled from the record, and the system asks the required questions, then creates a simulated claim with a case ID.
- [MVP · Rules] Priority flags: Repeat complainer, a case received through the regulator, a claim above a set amount, or Critical priority always goes to a human.
- [Stretch · Hybrid] Recognize before you dispute: Before filing, show the decoded merchant, location and channel: "this was an App purchase from your phone in Bogotá".
Human handoff & agent assist
- [MVP · Rules] Structured handoff packet: JSON with the request, verified facts, actions taken (with tool results), evidence, open questions, language and sentiment.
- [MVP · Rules] Explicit escalation rules: A bank-side block, confirmed fraud, a legal or regulator mention, two failed clarifications, low intent confidence, or a request for a human.
- [Stretch · LLM] Agent copilot panel: The handoff packet, a suggested reply and policy citations. One-click actions still pass through the policy engine.
Language & channels
- [MVP · LLM] ES and PT-BR with a regional lexicon: tarjeta/cartão, bloquear/travar, "compra no reconocida"/"compra não reconhecida", Argentine voseo ("¿me podés bloquear…?"), Mexican and Colombian terms.
- [MVP · Hybrid] Per-turn language detection and code-switching: Handle portuñol and switches mid-conversation, and always reply in the customer's current language. Covered by tests.
- [MVP · Rules] Out-of-market requests: Pix, boleto or a Brazilian account: say the bank doesn't serve that market and offer what it can do.
- [MVP · Rules] Localized money and dates: MXN $1,234.50, COP $1.234.567 and ARS $ 1.234,50, with day-first dates. Formatted in code, not by the model.
- [Stretch · LLM] Channel-aware replies: Short replies for WhatsApp, rich cards for web chat, short sentences for voice.
- [Stretch · LLM] Plain-language mode: Shorter sentences, no banking jargon, and a readability check before sending.
Safety, evaluation & operations
- [MVP · Rules] Policy engine outside the model: A server table maps each intent to its allowed tools. Actions need a confirmation token that the server issues.
- [MVP · Rules] Customer-scoped tools: Every query is filtered by the session's customer. A request for another customer's card returns a refusal and is logged.
- [MVP · Rules] Verified read-back: The system only says "done" after re-reading the record and confirming the change.
- [MVP · Rules] PII minimization: Mask card numbers, document numbers, emails and phone numbers before any LLM call. Tokens are resolved on the server.
- [MVP · Hybrid] Injection hardening, including data fields: A merchant_name or complaint description may contain instructions. Tool output is always treated as data, and the adversarial suite tests this.
- [MVP · Rules] Tracing and audit timeline: Langfuse traces of LLM calls, tool calls and rule hits. An audit view answers "why did the bot say this?" with sources, not chain-of-thought.
- [MVP · Rules] Bounded retries and safe fallback: Two retries with backoff, then a handoff with the packet. Never an invented answer.
- [MVP · Rules] Evaluation harness: Frozen held-out ES/PT scenarios and a baseline, measuring safe resolution, containment, escalation quality and unsafe outcomes with denominators and confidence intervals.
- [MVP · ML] Intent classifier vs keyword baseline: The required learned component, trained and tested on the team-labeled utterance set with splits grouped by customer and language.
- [Stretch · LLM] Customer simulator: LLM personas built from dataset profiles (country, segment, accent, sentiment) generate multi-turn tests. A sample is checked by hand.
- [Stretch · Rules] Ops scorecard: Safe resolution, missed and unnecessary transfers, p50/p95 latency and cost per resolution, broken down by language and segment.

Others
- [Control and traceability of LLM] – Suit to consult, check and validate all the interactions that users have with the agent. This will be used by the staff to quickly check how the agent is performing.
