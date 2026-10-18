"""The backup file format: MAGIC + salt + Fernet token, keyed by scrypt from a password."""

import base64
import os

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"PWB1"
SALT_SIZE = 16
# 2**16 needs ~64 MB for a moment once a day and keeps offline guessing slow if the password is weak.
SCRYPT_COST = 2**16


def _key(password: str, salt: bytes) -> bytes:
    raw = Scrypt(salt=salt, length=32, n=SCRYPT_COST, r=8, p=1).derive(password.encode())
    return base64.urlsafe_b64encode(raw)


def encrypt(content: bytes, password: str) -> bytes:
    """Fernet authenticates, so a wrong password or a changed byte fails to decrypt."""
    salt = os.urandom(SALT_SIZE)
    return MAGIC + salt + Fernet(_key(password, salt)).encrypt(content)


def decrypt(blob: bytes, password: str) -> bytes:
    if not blob.startswith(MAGIC):
        raise ValueError("not a poweron backup")
    salt = blob[len(MAGIC) : len(MAGIC) + SALT_SIZE]
    return Fernet(_key(password, salt)).decrypt(blob[len(MAGIC) + SALT_SIZE :])
