"""Customer read model.

See `docs/solution-docs/04-contracts.md` §1 (`customers.get_profile`).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = ["CustomerProfile"]


class CustomerProfile(BaseModel):
    """The masked profile behind `customers.get_profile`.

    `load_session` uses `country` to seed NLU context and `customer_status`
    for ADR-021 status precedence. See `04` §1.
    """

    model_config = ConfigDict(frozen=True)

    country: Literal["MX", "CO", "AR"]
    customer_status: Literal["Active", "Inactive", "Suspended", "Closed"]
