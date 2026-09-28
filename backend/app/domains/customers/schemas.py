"""Customer read model.

See `docs/solution-docs/04-contracts.md` §1 (`customers.get_profile`).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = ["CustomerProfile"]


class CustomerProfile(BaseModel):
    """The masked profile behind `customers.get_profile`.

    `load_session` uses `country` to seed NLU context and `customer_status`
    for ADR-021 status precedence. `first_name` lets Cardy address the
    customer by name (`docs/brand.md`); it is PII, so it only ever reaches
    the LLM as the `{customer_name}` placeholder key, never as a value
    (R5). `city` is PII too, and only ever reaches a reply as the masked
    `•••, <city>` delivery-address label (D2-B D4), never the raw address.
    See `04` §1.
    """

    model_config = ConfigDict(frozen=True)

    country: Literal["MX", "CO", "AR"]
    customer_status: Literal["Active", "Inactive", "Suspended", "Closed"]
    first_name: str | None = None
    city: str | None = None
