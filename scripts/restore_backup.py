"""Decrypt a backup the bot sent to the admin chat back into a SQLite database.

    BACKUP_PASSWORD=... python scripts/restore_backup.py poweron-2026-10-19.sqlite3.enc poweron.sqlite3

Without BACKUP_PASSWORD in the environment the password is asked for. The output is checked
with SQLite's integrity check before it is written.
"""

import os
import sqlite3
import sys
from getpass import getpass
from pathlib import Path

from cryptography.fernet import InvalidToken

from poweron.adapters.backup_crypto import decrypt


def main(source: Path, target: Path) -> None:
    password = os.environ.get("BACKUP_PASSWORD") or getpass("Backup password: ")
    try:
        content = decrypt(source.read_bytes(), password)
    except (InvalidToken, ValueError):
        sys.exit("cannot decrypt: wrong password, or not an intact poweron backup")
    check = sqlite3.connect(":memory:")
    check.deserialize(content)
    result = check.execute("pragma integrity_check").fetchone()[0]
    if result != "ok":
        sys.exit(f"the decrypted database is damaged: {result}")
    # 0600 and O_EXCL: the plaintext holds everyone's addresses, and nothing is overwritten.
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        sys.exit(f"{target} already exists; pick another name or move it away first")
    with os.fdopen(descriptor, "wb") as output:
        output.write(content)
    print(f"restored {target} ({len(content)} bytes)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python scripts/restore_backup.py BACKUP.enc OUTPUT.sqlite3")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
