from datetime import UTC, datetime

from security import expiry_iso, hash_password, new_session_token, token_hash, verify_password


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
