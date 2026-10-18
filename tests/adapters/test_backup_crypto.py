import pytest
from cryptography.fernet import InvalidToken

from poweron.adapters.backup_crypto import decrypt, encrypt


def test_encryption_round_trips_and_salts_every_file() -> None:
    first, second = encrypt(b"database", "secret"), encrypt(b"database", "secret")

    assert first != second
    assert decrypt(first, "secret") == decrypt(second, "secret") == b"database"


def test_a_wrong_password_or_a_tampered_file_is_rejected() -> None:
    encrypted = encrypt(b"database", "secret")

    with pytest.raises(InvalidToken):
        decrypt(encrypted, "wrong")
    with pytest.raises(InvalidToken):
        decrypt(encrypted[:-1] + bytes([encrypted[-1] ^ 1]), "secret")


def test_a_file_that_is_not_a_backup_is_rejected() -> None:
    with pytest.raises(ValueError):
        decrypt(b"not a backup at all", "secret")
