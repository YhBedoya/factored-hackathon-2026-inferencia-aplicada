"""Password and login-key primitives for customer accounts. Stdlib only
(D4): PBKDF2-SHA256 hashing plus the seeded, deterministic password used by
the credentials export.

`login_key` doubles as D2's PII boundary: it is the only form of
`document_number` that is ever allowed to reach `identity.accounts`, a
Redis rate-limit key or a log line. No function here logs anything.

See `docs/specs/d2-a-login-read-tools-api.md` D1, D2, D4.
"""

import base64
import hashlib
import hmac
import os

from app.domains.identity.models import DocumentType

__all__ = [
    "generate_password",
    "hash_password",
    "login_key",
    "login_key_prefix",
    "normalize_document_number",
    "staff_login_key",
    "verify_password",
]

# Characters D1 says to drop before comparing: spaces, dots and dashes.
_DROP_CHARS = str.maketrans("", "", " .-")

_PBKDF2_SCHEME = "pbkdf2_sha256"


def normalize_document_number(raw: str) -> str:
    """Trim, drop spaces/dots/dashes and uppercase (D1). Leading zeros
    survive because this never parses the value as a number.
    """

    return raw.strip().translate(_DROP_CHARS).upper()


def login_key(document_type: DocumentType, document_number: str, *, hmac_key: str) -> str:
    """Hex HMAC-SHA256 of `doc:<TYPE>:<NUMBER>` (D2). `document_type` is
    used exactly as its `Literal` value, so `DNI` and `CC` never collide
    even if their normalized numbers happened to match.
    """

    message = f"doc:{document_type}:{normalize_document_number(document_number)}"
    return hmac.new(hmac_key.encode(), message.encode(), hashlib.sha256).hexdigest()


def staff_login_key(username: str, *, hmac_key: str) -> str:
    """Hex HMAC-SHA256 of `staff:<username>` (D3), the staff-account analogue
    of `login_key`. Reuses the same `identity.accounts.login_key` lookup and
    the same `rl:login:<key>` rate limiter, so no separate limiter namespace
    exists for staff.
    """

    message = f"staff:{username}"
    return hmac.new(hmac_key.encode(), message.encode(), hashlib.sha256).hexdigest()


def login_key_prefix(key: str) -> str:
    """First 12 hex characters of a `login_key`, the only slice of it a log
    line or trace may carry (D2).
    """

    return key[:12]


def generate_password(customer_id: str, *, seed: str) -> str:
    """Deterministic 12-character password: the first 12 characters of the
    base32 of HMAC-SHA256(`seed`, `customer_id`) (D4). The account key is
    `customer_id` — the only stable key now that D3 leaves customers as the
    only accounts.
    """

    digest = hmac.new(seed.encode(), customer_id.encode(), hashlib.sha256).digest()
    return base64.b32encode(digest).decode("ascii").rstrip("=")[:12]


def hash_password(password: str, *, iterations: int = 1000) -> str:
    """`pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>`, a random 16-byte
    salt per call (D4).
    """

    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    salt_b64 = base64.b64encode(salt).decode("ascii")
    hash_b64 = base64.b64encode(derived).decode("ascii")
    return f"{_PBKDF2_SCHEME}${iterations}${salt_b64}${hash_b64}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verification. A malformed `stored` value (wrong
    scheme, wrong shape, bad base64) is a `False`, never an exception, so a
    corrupt row can't turn a login attempt into a 500.
    """

    try:
        scheme, iterations_raw, salt_b64, hash_b64 = stored.split("$")
        if scheme != _PBKDF2_SCHEME:
            return False
        iterations = int(iterations_raw)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except (ValueError, TypeError):
        return False

    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return hmac.compare_digest(candidate, expected)
