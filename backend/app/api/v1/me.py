"""Read-only banking views for the customer home: `GET /me/cards`,
`GET /me/cards/{card_id}`, `GET /me/transactions`.

`router` declares `require_role("customer")` and `require_csrf` at the
*router* level (R13, ADR-025), same convention `conversations.py` set. No
route takes `customer_id` (R1): it always comes from the `Session`. A foreign
or unknown `card_id` is `404 not_found` either way (spec D8): `AccessDenied`
and `NotFound` are folded together so the route never confirms that another
customer's card exists.

Display strings (masks, money, dates) are built here, in code, from
`app.domains.localization` (R4); the frontend only renders them. The view
builders are pure module-level functions so a unit test can call them. A
debit card's `current_balance` is its available balance (A1, ADR-032); its
credit-only fields stay `null`.

See `docs/specs/landing-home-bienvenida.md` "Contracts (delta only)", D7-D9, A1.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError

from app.core.errors import AccessDenied, NotFound
from app.domains.cards import service as cards_service
from app.domains.cards.schemas import CardDetails, CardSummary
from app.domains.customers import service as customers_service
from app.domains.identity.deps import get_session, require_csrf, require_role
from app.domains.identity.models import Session
from app.domains.localization.format import (
    BANK_TZ,
    Country,
    format_date,
    format_money,
    mask_card,
)
from app.domains.transactions import service as transactions_service
from app.domains.transactions.schemas import TxFilter, TxStatus, TxView
from app.domains.transactions.service import InvalidCursor

__all__ = [
    "CardDetailsView",
    "CardView",
    "TxPage",
    "TxRow",
    "card_details_view",
    "card_view",
    "router",
    "tx_row",
]


class CardView(BaseModel):
    model_config = ConfigDict(frozen=True)

    card_id: str
    kind: Literal["credit", "debit"]
    last4: str
    mask: str
    status: Literal["Active", "Blocked", "Suspended", "Closed"]
    locked: bool


class CardDetailsView(CardView):
    currency: str
    expiration_date: date | None
    expiration_date_display: str | None
    credit_limit: Decimal | None
    credit_limit_display: str | None
    current_balance: Decimal | None
    current_balance_display: str | None
    available_credit: Decimal | None
    available_credit_display: str | None
    days_past_due: int | None


class TxRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    tx_id: str
    card_id: str
    card_mask: str | None
    occurred_at: AwareDatetime
    date_display: str
    amount: Decimal
    currency: str
    amount_display: str
    merchant_name: str | None
    type: str
    status: TxStatus


class TxPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[TxRow]
    next_cursor: str | None


def card_view(card: CardSummary) -> CardView:
    return CardView(
        card_id=card.card_id,
        kind=card.kind,
        last4=card.last4,
        mask=mask_card(card.last4),
        status=card.status,
        locked=card.locked,
    )


def _money(amount: Decimal | None, currency: str, country: Country) -> str | None:
    return None if amount is None else format_money(amount, currency, country)


def card_details_view(details: CardDetails, country: Country) -> CardDetailsView:
    # A1, ADR-032: a debit card shows its balance (the money available in
    # it), never the credit-only fields.
    is_debit = details.kind == "debit"
    limit = None if is_debit else details.credit_limit
    balance = details.current_balance
    available = None if is_debit else details.available_credit
    expiration = details.expiration_date
    return CardDetailsView(
        **card_view(details).model_dump(),
        currency=details.currency,
        expiration_date=expiration,
        expiration_date_display=None if expiration is None else format_date(expiration),
        credit_limit=limit,
        credit_limit_display=_money(limit, details.currency, country),
        current_balance=balance,
        current_balance_display=_money(balance, details.currency, country),
        available_credit=available,
        available_credit_display=_money(available, details.currency, country),
        days_past_due=None if is_debit else details.days_past_due,
    )


def tx_row(tx: TxView, country: Country, masks: dict[str, str]) -> TxRow:
    local_date = tx.occurred_at.astimezone(BANK_TZ[country]).date()
    return TxRow(
        tx_id=tx.tx_id,
        card_id=tx.card_id,
        card_mask=masks.get(tx.card_id),
        occurred_at=tx.occurred_at,
        date_display=format_date(local_date),
        amount=tx.amount,
        currency=tx.currency,
        amount_display=format_money(tx.amount, tx.currency, country),
        merchant_name=tx.merchant_name,
        type=tx.type,
        status=tx.status,
    )


router = APIRouter(
    prefix="/me",
    dependencies=[Depends(require_role("customer")), Depends(require_csrf)],
)


def _customer_id(session: Session) -> str:
    """Narrow `session.customer_id`; `None` is a staff session, which
    `require_role("customer")` already refused (D15).
    """
    if session.customer_id is None:
        raise HTTPException(status_code=403, detail="forbidden_role")
    return session.customer_id


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="not_found")


@router.get("/cards", response_model=list[CardView])
async def list_cards(session: Annotated[Session, Depends(get_session)]) -> list[CardView]:
    cards = await cards_service.list_cards(_customer_id(session))
    return [card_view(card) for card in cards]


@router.get("/cards/{card_id}", response_model=CardDetailsView)
async def get_card(
    card_id: str, session: Annotated[Session, Depends(get_session)]
) -> CardDetailsView:
    customer_id = _customer_id(session)
    try:
        details = await cards_service.get_card_details(customer_id, card_id)
    except (AccessDenied, NotFound) as exc:
        raise _not_found() from exc
    profile = await customers_service.get_profile(customer_id)
    return card_details_view(details, profile.country)


@router.get("/transactions", response_model=TxPage)
async def list_transactions(
    session: Annotated[Session, Depends(get_session)],
    card_id: Annotated[str | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
) -> TxPage:
    customer_id = _customer_id(session)
    try:
        tx_filter = TxFilter(card_id=card_id, date_from=date_from, date_to=date_to)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="invalid_filter") from exc
    if card_id is not None:
        # Ownership first, before any paging (R1): `list_page` doesn't check it.
        try:
            await cards_service.get_card_details(customer_id, card_id)
        except (AccessDenied, NotFound) as exc:
            raise _not_found() from exc
    try:
        views, next_cursor = await transactions_service.list_page(customer_id, tx_filter, cursor)
    except InvalidCursor as exc:
        raise HTTPException(status_code=422, detail="invalid_cursor") from exc
    profile = await customers_service.get_profile(customer_id)
    cards = await cards_service.list_cards(customer_id)
    masks = {card.card_id: mask_card(card.last4) for card in cards}
    return TxPage(items=[tx_row(v, profile.country, masks) for v in views], next_cursor=next_cursor)
