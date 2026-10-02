"""Money, date, card-mask and label formatting. See D11, D17, D18, `02` §7.

Money, dates, card masks, times and days-counts are formatted here, never by
the LLM (R4). Babel supplies number/date rounding and grouping; the exact
separator and code placement per the contract come from an explicit country
table below rather than from CLDR locale defaults, since Babel's locale data
doesn't line up with `02` §7's strings and the plan's Q5 examples one-for-one.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from babel.dates import format_date as _babel_format_date
from babel.numbers import format_decimal as _babel_format_decimal

from app.domains.localization.schemas import FxRate

__all__ = [
    "BANK_TZ",
    "format_date",
    "format_days",
    "format_money",
    "format_time",
    "kind_label",
    "local_today",
    "mask_card",
    "mxn_estimate",
    "queue_label",
    "status_label",
]

Country = Literal["MX", "CO", "AR"]
# "Locked" is not a bank status: it labels an Active card carrying a temporary lock.
CardStatus = Literal["Active", "Blocked", "Suspended", "Closed", "Locked"]
CardKind = Literal["credit", "debit"]
Language = Literal["es", "pt"]
Queue = Literal["atencion", "cobranza", "fraudes", "reclamos"]

# `03` §5: every `bank.*` timestamp is UTC; local display uses the account
# country's zone, never the server's or the customer's device zone.
BANK_TZ: dict[Country, ZoneInfo] = {
    "MX": ZoneInfo("America/Mexico_City"),
    "CO": ZoneInfo("America/Bogota"),
    "AR": ZoneInfo("America/Argentina/Buenos_Aires"),
}

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
        "Locked": "Bloqueada temporalmente",
    },
    # Masculine agreement: "o cartão" (pt).
    "pt": {
        "Active": "Ativo",
        "Blocked": "Bloqueado",
        "Suspended": "Suspenso",
        "Closed": "Fechado",
        "Locked": "Bloqueado temporariamente",
    },
}

_KIND_LABELS: dict[Language, dict[CardKind, str]] = {
    # `02` §4.1's card-picker options: "Crédito •••• 6475", "Débito •••• 1203".
    "es": {"credit": "Crédito", "debit": "Débito"},
    "pt": {"credit": "Crédito", "debit": "Débito"},
}

_QUEUE_LABELS: dict[Language, dict[Queue, str]] = {
    # Handoff queue names shown in an `action_unverified`/escalation reply.
    "es": {
        "atencion": "Atención al cliente",
        "cobranza": "Cobranza",
        "fraudes": "Fraudes",
        "reclamos": "Reclamos",
    },
    "pt": {
        "atencion": "Atendimento",
        "cobranza": "Cobrança",
        "fraudes": "Fraudes",
        "reclamos": "Reclamações",
    },
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


def local_today(country: Country, now: datetime | None = None) -> date:
    """Today's date in the account country's zone (`03` §5).

    `now` is UTC (or any aware datetime); defaults to the real clock. Used
    for relative-date resolution, never for the pipeline's date-shifted data.
    """
    at = now if now is not None else datetime.now(UTC)
    return at.astimezone(BANK_TZ[country]).date()


def format_time(at: datetime, country: Country) -> str:
    """`HH:MM` in the account country's zone (D17's `{time}`). `at` is aware."""
    return at.astimezone(BANK_TZ[country]).strftime("%H:%M")


def mxn_estimate(amount_usd: Decimal, fx: FxRate, language: Language) -> str:
    """The labeled MXN-estimate footnote for a USD card in MX (D18).

    Renders in the MX money pattern, rounded to 2 decimals, with the rate's
    own `as_of` date (day-first) so the customer sees which day it is from.
    """
    converted = (amount_usd * fx.rate).quantize(Decimal("0.01"))
    money = format_money(converted, fx.target, "MX")
    rate_date = format_date(fx.as_of)
    if language == "es":
        return f"(≈ {money}, tipo de cambio del {rate_date})"
    return f"(≈ {money}, câmbio de {rate_date})"


def queue_label(queue: Queue, language: Language) -> str:
    """Localized handoff-queue display name (D18/escalation replies)."""
    return _QUEUE_LABELS[language][queue]


def format_days(n: int, language: Language) -> str:
    """`30 días` / `30 dias`."""
    unit = "días" if language == "es" else "dias"
    return f"{n} {unit}"
