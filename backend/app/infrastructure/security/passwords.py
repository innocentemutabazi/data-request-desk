"""Password hashing with Argon2id (the OWASP-recommended default; salted, memory-hard)."""

from __future__ import annotations

import asyncio
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()  # argon2-cffi defaults = RFC 9106 low-memory profile, argon2id


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except (VerificationError, InvalidHashError):
        return False


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return _hasher.hash("not-a-real-password")


async def verify_password_async(plain: str, hashed: str | None) -> bool:
    """Verify off the event loop (Argon2 is deliberately CPU/memory heavy).

    When the account does not exist we still burn one full verification against a dummy hash, so
    response time does not reveal whether an email is registered (user-enumeration timing oracle).
    """
    target = hashed or _dummy_hash()
    ok = await asyncio.to_thread(verify_password, plain, target)
    return ok and hashed is not None


def needs_rehash(hashed: str) -> bool:
    return _hasher.check_needs_rehash(hashed)
