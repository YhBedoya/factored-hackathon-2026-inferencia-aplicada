# intent_gen@v3

Eval-only prompt (ADR-032). It is never used in the served graph.

You generate training utterances for a customer-support intent classifier of a
card fintech chat. Write the way real customers type in a chat window. This
top-up teaches the classifier that naming the card type ("credit" or "debit")
does not change the class of a card request.

## Cell

- Locale: {locale} (es-MX, es-CO, es-AR or pt-BR)
- Class: {class_name}
- Class description: {class_description}
- Families to write ({count}, in this exact order, one card type each): {card_types}

## Task

Produce {count} families, one per card type, in the given order. Each family has
one seed utterance plus 2 paraphrases ({items} items in total). The paraphrases
keep the same meaning and the same card type as the seed, with different wording.

Every item MUST name the card type in the locale's natural wording:

- es-*: "tarjeta de crédito" or "tarjeta de débito". A natural short form such
  as "la de crédito" or "mi débito" is allowed only when a native speaker of the
  locale would say it in a card context. Never use a bare "crédito" that could
  read as a loan.
- pt-BR: "cartão de crédito" or "cartão de débito". A short form such as "o de
  crédito" only when a Brazilian would say it in a card context.

Every item must clearly ask for this class and no other class. Keep the card
type mention incidental: the request itself is what defines the class.

## Rules

- Write every item in the register of the locale. Spanish for es-*, Brazilian
  Portuguese for pt-BR. Never mix in English.
- PII only as placeholder tokens of the form ⟨KIND_n⟩ with KIND in the kinds
  the product masks (for example ⟨CARD_1⟩, ⟨NAME_1⟩, ⟨EMAIL_1⟩, ⟨PHONE_1⟩),
  numbered from 1. Never write real names, card numbers, emails or phones.
- No bank names, brand names or real data.
- Items inside one family must differ in wording, not only in punctuation.
- No duplicates across the cell.
- Every item must be labeled as the class by a reasonable reader. For a class
  that is a short reply or a social turn (greeting, thanks, yes, no), keep the
  item short and natural while still naming the card type.

## Output

Return only JSON, with no prose and no code fences:

{"families": [{"slot": "card_type", "seed": "<text>", "paraphrases": ["<text>", "<text>"]}]}

The array has exactly {count} entries, in the given card type order.
