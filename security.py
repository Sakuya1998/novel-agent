"""轻量本地认证上下文与密码/会话工具。"""

import base64
import hashlib
import hmac
import secrets
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime

LOCAL_TENANT_ID = "tenant_local"
LOCAL_USER_ID = "user_local"


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: str
    username: str
    role: str
    display_name: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "username": self.username,
            "role": self.role,
            "display_name": self.display_name,
        }


_CURRENT_PRINCIPAL: ContextVar[Principal | None] = ContextVar(
    "novel_agent_current_principal", default=None
)


def set_current_principal(principal: Principal | None):
    return _CURRENT_PRINCIPAL.set(principal)


def reset_current_principal(token) -> None:
    _CURRENT_PRINCIPAL.reset(token)


def current_principal() -> Principal | None:
    return _CURRENT_PRINCIPAL.get()


def current_tenant_id() -> str | None:
    principal = current_principal()
    return principal.tenant_id if principal else None


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=64)

    def encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    return f"scrypt$16384$8$1${encode(salt)}${encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_value, digest_value = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        def decode(value: str) -> bytes:
            return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

        expected = decode(digest_value)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=decode(salt_value),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (TypeError, ValueError, UnicodeError):
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def expiry_iso(hours: int) -> str:
    from datetime import timedelta

    return (datetime.now(UTC) + timedelta(hours=max(hours, 1))).replace(microsecond=0).isoformat()
