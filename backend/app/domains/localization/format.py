"""Money, date, card-mask and label formatting. See D11, `02` §7.

Money, dates and card masks are formatted here, never by the LLM (R4). Babel
supplies number/date rounding and grouping; the exact separator and code
placement per the contract come from an explicit country table below rather
than from CLDR locale defaults, since Babel's locale data doesn't line up
with `02` §7's strings and the plan's Q5 examples one-for-one.
"""

from datetime import date
from decimal import Decimal
from typing import Literal

from babel.dates import format_date as _babel_format_date
from babel.numbers import format_decimal as _babel_format_decimal

__all__ = [
    "format_date",
    "format_money",
    "kind_label",
    "mask_card",
    "status_label",
]

Country = Literal["MX", "CO", "AR"]
CardStatus = Literal["Active", "Blocked", "Suspended", "Closed"]
CardKind = Literal["credit", "debit"]
Language = Literal["es", "pt"]

# Babel gives us grouped/rounded digits in the `en_US` shape (",", ".") once
# and for all; the country table below swaps those two characters where the
# country's convention differs, instead of trusting a locale's own symbols.
_COUNTRY_SEPARATORS: dict[Country, tuple[str, str]] = {
    # (decimal separator, thousands separator)
    "MX": (".", ","),
    "CO": (",", "."),
    "AR": (",", "."),
}

# Whether the record's `$` sign is followed by a space before the digits
# (D11, plan Q5): CO and MX render it tight, AR leaves a space.
_SPACE_AFTER_DOLLAR: dict[Country, bool] = {"MX": False, "CO": False, "AR": True}

_STATUS_LABELS: dict[Language, dict[CardStatus, str]] = {
    # Feminine agreement: "la tarjeta" (es).
    "es": {
        "Active": "Activa",
        "Blocked": "Bloqueada",
        "Suspended": "Suspendida",
        "Closed": "Cerrada",
    },
    # Masculine agreement: "o cartão" (pt).
    "pt": {
        "Active": "Ativo",
        "Blocked": "Bloqueado",
        "Suspended": "Suspenso",
        "Closed": "Fechado",
    },
}

_KIND_LABELS: dict[Language, dict[CardKind, str]] = {
    # `02` §4.1's card-picker options: "Crédito •••• 6475", "Débito •••• 1203".
    "es": {"credit": "Crédito", "debit": "Débito"},
    "pt": {"credit": "Crédito", "debit": "Débito"},
}


def format_money(amount: Decimal, currency: str, country: Country) -> str:
    """Render a money value in the account country's format (D11, `02` §7).

    The country sets the digit grouping, the decimal separator and the
    spacing around `$`; the record's `currency` sets the code, except that
    USD in MX renders as the bare `US$` prefix by local convention. COP has
    no decimal places. No MXN estimate is added here (that's D2-B2).
    """
    decimals = 0 if currency == "COP" else 2
    pattern = "#,##0" if decimals == 0 else "#,##0.00"
    digits = _babel_format_decimal(amount, format=pattern, locale="en_US")

    decimal_sep, thousands_sep = _COUNTRY_SEPARATORS[country]
    if (decimal_sep, thousands_sep) != (".", ","):
        digits = digits.translate(str.maketrans(",.", "\x00\x01")).translate(
            str.maketrans("\x00\x01", thousands_sep + decimal_sep)
        )

    if currency == "USD" and country == "MX":
        prefix = "US$"
    else:
        prefix = f"{currency} $" + (" " if _SPACE_AFTER_DOLLAR[country] else "")

    return prefix + digits


def format_date(d: date) -> str:
    """Day-first `dd/mm/yyyy`, the only order used in replies (`02` §7)."""
    return _babel_format_date(d, format="dd/MM/yyyy", locale="en_US")


def mask_card(last4: str) -> str:
    """`•••• 1234`. `last4` is already the masked tail (R1); never a full PAN."""
    return f"•••• {last4}"


def status_label(status: CardStatus, language: Language) -> str:
    """Localized card status, with the right gender for "tarjeta"/"cartão"."""
    return _STATUS_LABELS[language][status]


def kind_label(kind: CardKind, language: Language) -> str:
    """Localized card kind, as shown in `card_select` options (`02` §4.1)."""
    return _KIND_LABELS[language][kind]
