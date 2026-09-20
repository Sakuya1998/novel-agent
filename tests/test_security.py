from datetime import UTC, datetime

from novel_agent.security import (
    expiry_iso,
    hash_password,
    new_csrf_token,
    new_session_token,
    token_hash,
    verify_csrf_token,
    verify_password,
)


def test_password_hash_is_salted_and_verifiable():
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")

    assert first.startswith("scrypt$")
    assert first != second
    assert verify_password("correct horse battery staple", first) is True
    assert verify_password("wrong password", first) is False


def test_session_tokens_are_random_and_hashable():
    first = new_session_token()
    second = new_session_token()

    assert first != second
    assert len(token_hash(first)) == 64
    assert token_hash(first) != first
    assert datetime.fromisoformat(expiry_iso(1)) > datetime.now(UTC)


def test_csrf_tokens_are_random_and_verified_in_constant_time(monkeypatch):
    first = new_csrf_token()
    second = new_csrf_token()
    compared: list[tuple[str, str]] = []

    def record_compare(expected: str, actual: str) -> bool:
        compared.append((expected, actual))
        return expected == actual

    monkeypatch.setattr("novel_agent.security.hmac.compare_digest", record_compare)

    assert first != second
    assert verify_csrf_token(first, first) is True
    assert verify_csrf_token(first, second) is False
    assert verify_csrf_token(first, "") is False
    assert compared == [(first, first), (first, second)]
