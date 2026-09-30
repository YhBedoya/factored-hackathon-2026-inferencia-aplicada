"""Fault-injection switches (D6-A).

`FAULTS` (comma-separated, command line only) turns named failure points on so
the reliability paths can be exercised on demand. Read on every call, so a
test that flips the setting and clears `get_settings`'s cache sees it at once.
`main.py` refuses to start with any fault set under `APP_ENV=prod`.
"""

from app.core.config import Fault, get_settings

__all__ = ["Fault", "fault_active"]


def fault_active(name: Fault) -> bool:
    """True when `name` is listed in `FAULTS`."""
    return name in get_settings().faults
