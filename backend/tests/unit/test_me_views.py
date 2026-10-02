"""`/me` view builders: every display string is the `localization.format`
output (R4), and a debit card shows its balance but no credit-only field
(A1, ADR-032).
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from app.api.v1.me import card_details_view, tx_row
from app.domains.cards.schemas import CardDetails
from app.domains.localization.format import (
    BANK_TZ,
    Country,
    format_date,
    format_money,
    mask_card,
)
from app.domains.transactions.schemas import TxView


def _details(kind: str, currency: str) -> CardDetails:
    return CardDetails.model_validate(
        {
            "card_id": "PRD-X1",
            "kind": kind,
            "last4": "6475",
            "status": "Active",
            "locked": False,
            "currency": currency,
            "expiration_date": date(2028, 7, 31),
            "credit_limit": Decimal("50000.00") if kind == "credit" else None,
            "current_balance": Decimal("12345.67"),
            "interest_rate": None,
            "days_past_due": 0 if kind == "credit" else None,
            "source": "bank.products:PRD-X1",
        }
    )


def _tx(currency: str, amount: str) -> TxView:
    return TxView(
        tx_id="TRX-1",
        card_id="PRD-X1",
        # 02:30 UTC is still the previous local day in MX and CO.
        occurred_at=datetime(2026, 3, 31, 2, 30, tzinfo=UTC),
        amount=Decimal(amount),
        currency=currency,
        amount_usd=None,
        type="Purchase",
        category=None,
        merchant_name="Tienda",
        merchant_category=None,
        channel="POS",
        city=None,
        country=None,
        status="Approved",
        response_code=None,
        fraud_score=None,
    )


def test_display_strings_from_localization() -> None:
    for country, currency in (("MX", "MXN"), ("CO", "COP")):
        c: Country = country  # type: ignore[assignment]
        credit = _details("credit", currency)
        view = card_details_view(credit, c)
        assert view.mask == mask_card("6475")
        assert view.expiration_date_display == format_date(date(2028, 7, 31))
        assert view.credit_limit_display == format_money(Decimal("50000.00"), currency, c)
        assert view.current_balance_display == format_money(Decimal("12345.67"), currency, c)
        assert view.available_credit_display == format_money(Decimal("37654.33"), currency, c)

        row = tx_row(_tx(currency, "1234.50"), c, {"PRD-X1": mask_card("6475")})
        assert row.amount_display == format_money(Decimal("1234.50"), currency, c)
        local = datetime(2026, 3, 31, 2, 30, tzinfo=UTC).astimezone(BANK_TZ[c]).date()
        assert row.date_display == format_date(local)
        assert row.card_mask == mask_card("6475")

    debit = card_details_view(_details("debit", "MXN"), "MX")
    assert debit.current_balance == Decimal("12345.67")
    assert debit.current_balance_display == format_money(Decimal("12345.67"), "MXN", "MX")
    assert debit.credit_limit is None
    assert debit.available_credit is None
    assert debit.days_past_due is None

    assert tx_row(_tx("MXN", "1.00"), "MX", {}).card_mask is None
