# intent_gen@v2

Eval-only prompt (ADR-032). It is never used in the served graph.

You generate training utterances for a customer-support intent classifier of a
card fintech chat. Write the way real customers type in a chat window.

## Cell

- Locale: {locale} (es-MX, es-CO, es-AR or pt-BR)
- Class: {class_name}
- Class description: {class_description}
- Slots (10, in this exact order): {slots}

## Task

Produce 10 families, one per slot, in the given order. Each family has one
seed utterance plus 2 paraphrases (30 items in total). The paraphrases keep the
slot's property and the same meaning as the seed, with different wording.

Slot meanings:

- plain: a clear, typical request for this class.
- regional: strong regional vocabulary and register of the locale (voseo and
  "che" for es-AR, "parce" or "vos" for es-CO, "wey" or "ahorita" for es-MX,
  informal Brazilian Portuguese for pt-BR).
- typo_informal: informal chat style with typos, missing accents, slang and
  abbreviations.
- hard_negative: the text uses words typical of ANOTHER class, but the
  customer wants this class. The item MUST express this class.
- negation: the customer rules out a DIFFERENT intent or topic and asks for this
  class ("no quiero bloquearla, solo ver cuánto debo" for balance_due). The item
  MUST express this class.
- short_answer: 1 to 3 words only, as a reply in a conversation.

## Rules

- Write every item in the register of the locale. Spanish for es-*, Brazilian
  Portuguese for pt-BR. Never mix in English.
- PII only as placeholder tokens of the form ⟨KIND_n⟩ with KIND in the kinds
  the product masks (for example ⟨CARD_1⟩, ⟨NAME_1⟩, ⟨EMAIL_1⟩, ⟨PHONE_1⟩),
  numbered from 1. Never write real names, card numbers, emails or phones.
- No bank names, brand names or real data. Refer to "mi tarjeta" / "meu cartão".
- Items inside one family must differ in wording, not only in punctuation.
- No duplicates across the cell.
- Every item, in every slot, must be labeled as the class by a reasonable
  reader. For a class that is an out-of-scope topic (loans, accounts,
  investments and the like), the same applies to the topic: every item must be
  about this topic.

## Output

Return only JSON, with no prose and no code fences:

{"families": [{"slot": "<slot name>", "seed": "<text>", "paraphrases": ["<text>", "<text>"]}]}

The array has exactly 10 entries, in slot order.
