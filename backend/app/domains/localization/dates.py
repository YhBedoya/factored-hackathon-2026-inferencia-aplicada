"""Plain-code date resolver for `tx_search`/`tx_explain` (spec
`d7-b-transactions-traceability-judge.md` A3).

`resolve_date_expression` is the only place an NLU-extracted date phrase
becomes a `TxFilter.date_from`/`date_to` window: the LLM never supplies a
date directly (R6, spec "Never"). It folds case and accents the same way
`policy/escalation.py::_fold` does, then matches a small, fixed set of ES/PT
expressions with plain string comparisons and regexes -- no date-parsing
library, so an unsupported phrase fails closed to `None` instead of guessing.
Pure and side-effect free: no I/O, no LLM. `today` is the caller's already
zone-adjusted day (`localization.format.local_today`); `tz` is accepted for
signature symmetry with that function and to make the caller's zone
assumption explicit, even though weekday/calendar arithmetic on a `date`
needs no zone of its own.
"""

import re
import unicodedata
from datetime import date, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

__all__ = ["resolve_date_expression"]

_ES_WEEKDAYS: dict[str, int] = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sabado": 5,
    "domingo": 6,
}

_PT_WEEKDAYS: dict[str, int] = {
    "segunda": 0,
    "terca": 1,
    "quarta": 2,
    "quinta": 3,
    "sexta": 4,
    "sabado": 5,
    "domingo": 6,
}

_ES_MONTHS: dict[str, int] = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

_PT_MONTHS: dict[str, int] = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}

_HACE_N_DIAS = re.compile(r"^hace (\d+) dias?$")
_HA_N_DIAS = re.compile(r"^ha (\d+) dias?$")
_ES_WEEKDAY_PASADO = re.compile(r"^(?:el )?(\w+) pasado$")
_PT_WEEKDAY_PASSADA = re.compile(r"^(\w+) passada$")
_ES_DAY_OF_MONTH = re.compile(r"^(\d{1,2}) de (\w+)$")
_PT_DAY_OF_MONTH = re.compile(r"^(\d{1,2}) de (\w+)$")


def _fold(text: str) -> str:
    """Lowercase and strip accents so `día`/`dia` and `março`/`marco` match."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _single_day(d: date) -> tuple[date, date]:
    return d, d


def _most_recent_weekday_before(today: date, weekday: int) -> tuple[date, date]:
    """The most recent `weekday` strictly before `today` (A3)."""
    delta = (today.weekday() - weekday) % 7
    if delta == 0:
        delta = 7
    return _single_day(today - timedelta(days=delta))


def _previous_week(today: date) -> tuple[date, date]:
    """Monday-Sunday of the calendar week before `today`'s week (A3)."""
    this_monday = today - timedelta(days=today.weekday())
    previous_monday = this_monday - timedelta(days=7)
    return previous_monday, previous_monday + timedelta(days=6)


def _previous_month(today: date) -> tuple[date, date]:
    """The full previous calendar month (A3)."""
    first_of_this_month = today.replace(day=1)
    last_of_previous_month = first_of_this_month - timedelta(days=1)
    return last_of_previous_month.replace(day=1), last_of_previous_month


def _most_recent_on_or_before(today: date, day: int, month: int) -> tuple[date, date] | None:
    """The most recent `day`/`month` on or before `today` (A3), trying this
    year and then last year. `None` if neither year has that calendar date
    (e.g. 29 February outside a leap year)."""
    for year in (today.year, today.year - 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate <= today:
            return _single_day(candidate)
    return None


def resolve_date_expression(
    expr: str,
    today: date,
    tz: ZoneInfo,
    language: Literal["es", "pt"],
) -> tuple[date, date] | None:
    """Resolve a plain ES/PT date phrase to an inclusive `(date_from, date_to)`
    window, or `None` when it isn't one of A3's fixed patterns.

    `today` and `tz` are the customer's local day and zone
    (`localization.format.local_today`/`BANK_TZ`); this function does no
    zone conversion of its own.
    """
    del tz  # accepted for signature symmetry with `local_today`; unused here
    text = _fold(expr.strip())

    if language == "es":
        if text == "hoy":
            return _single_day(today)
        if text == "ayer":
            return _single_day(today - timedelta(days=1))
        if text == "anteayer":
            return _single_day(today - timedelta(days=2))
        if text == "semana pasada":
            return _previous_week(today)
        if text == "mes pasado":
            return _previous_month(today)

        match_n_dias = _HACE_N_DIAS.match(text)
        if match_n_dias:
            return _single_day(today - timedelta(days=int(match_n_dias.group(1))))

        match_weekday = _ES_WEEKDAY_PASADO.match(text)
        if match_weekday and match_weekday.group(1) in _ES_WEEKDAYS:
            return _most_recent_weekday_before(today, _ES_WEEKDAYS[match_weekday.group(1)])

        match_day_of_month = _ES_DAY_OF_MONTH.match(text)
        if match_day_of_month and match_day_of_month.group(2) in _ES_MONTHS:
            day, month_name = match_day_of_month.groups()
            return _most_recent_on_or_before(today, int(day), _ES_MONTHS[month_name])

        return None

    # language == "pt"
    if text == "hoje":
        return _single_day(today)
    if text == "ontem":
        return _single_day(today - timedelta(days=1))
    if text == "anteontem":
        return _single_day(today - timedelta(days=2))
    if text == "semana passada":
        return _previous_week(today)
    if text == "mes passado":
        return _previous_month(today)

    match_n_dias = _HA_N_DIAS.match(text)
    if match_n_dias:
        return _single_day(today - timedelta(days=int(match_n_dias.group(1))))

    match_weekday = _PT_WEEKDAY_PASSADA.match(text)
    if match_weekday and match_weekday.group(1) in _PT_WEEKDAYS:
        return _most_recent_weekday_before(today, _PT_WEEKDAYS[match_weekday.group(1)])

    match_day_of_month = _PT_DAY_OF_MONTH.match(text)
    if match_day_of_month and match_day_of_month.group(2) in _PT_MONTHS:
        day, month_name = match_day_of_month.groups()
        return _most_recent_on_or_before(today, int(day), _PT_MONTHS[month_name])

    return None
