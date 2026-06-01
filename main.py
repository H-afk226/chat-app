"""
db.py  ──  SecureChat database + key management
Security upgrades:
  • Argon2id password hashing (works on Python 3.14, replaces bcrypt/SHA-256)
  • Backwards-compatible: old SHA-256 rows still log in, then auto-upgraded
  • username validation (alphanumeric + underscore only)
"""

import sqlite3
import hashlib
import os
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from cryptography.fernet import Fernet

DB_FILE  = "users.db"
KEY_FILE = "key.key"

# Argon2id hasher — time_cost=3, memory_cost=65536 (64 MB), parallelism=2
_ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)

# ── Encryption key ────────────────────────────────────────────────

def load_or_create_key() -> bytes:
    """Load existing Fernet key or generate and save a new one."""
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            return f.read()
    key = Fernet.generate_key()
    with open(KEY_FILE, "wb") as f:
        f.write(key)
    print(f"[db] New encryption key created → {KEY_FILE}")
    return key

# ── Password hashing (Argon2id) ───────────────────────────────────

def _hash_password(password: str) -> str:
    """Hash password with Argon2id. Returns the hash string."""
    return _ph.hash(password)

def _verify_password(password: str, stored: str) -> bool:
    """Verify against an Argon2 hash."""
    try:
        return _ph.verify(stored, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False

# ── Database init ─────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c    = conn.cursor()
    # salt column kept for legacy SHA-256 migration only
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username  TEXT PRIMARY KEY,
            password  TEXT NOT NULL,
            salt      TEXT NOT NULL DEFAULT '',
            hash_type TEXT NOT NULL DEFAULT 'argon2'
        )
    """)
    try:
        c.execute("ALTER TABLE users ADD COLUMN salt TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN hash_type TEXT NOT NULL DEFAULT 'sha256'")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

# ── Register ──────────────────────────────────────────────────────

def register_user(username: str, password: str) -> tuple[bool, str]:
    username = username.strip()
    if len(username) < 3:
        return False, "Username must be at least 3 characters."
    if len(username) > 20:
        return False, "Username must be 20 characters or fewer."
    if not all(c.isalnum() or c == "_" for c in username):
        return False, "Username may only contain letters, digits, or _."
    if len(password) < 6:
        return False, "Password must be at least 6 characters."

    hashed = _hash_password(password)

    try:
        conn = sqlite3.connect(DB_FILE)
        c    = conn.cursor()
        c.execute(
            "INSERT INTO users (username, password, salt, hash_type) VALUES (?, ?, ?, ?)",
            (username, hashed, "", "argon2")
        )
        conn.commit()
        conn.close()
        return True, "Account created successfully."
    except sqlite3.IntegrityError:
        return False, "Username already taken."
    except Exception as e:
        return False, f"Database error: {e}"

# ── Login ─────────────────────────────────────────────────────────

def login_user(username: str, password: str) -> tuple[bool, str]:
    username = username.strip()
    try:
        conn = sqlite3.connect(DB_FILE)
        c    = conn.cursor()
        c.execute(
            "SELECT password, salt, hash_type FROM users WHERE username = ?",
            (username,)
        )
        row = c.fetchone()
        conn.close()
    except Exception as e:
        return False, f"Database error: {e}"

    if not row:
        return False, "User not found."

    stored_hash, salt, hash_type = row

    # ── Legacy SHA-256 rows: verify then auto-upgrade to Argon2 ──
    if hash_type == "sha256":
        if not salt:
            legacy_ok = (hashlib.sha256(password.encode()).hexdigest() == stored_hash)
        else:
            digest    = hashlib.sha256((salt + password).encode()).hexdigest()
            legacy_ok = (digest == stored_hash)

        if not legacy_ok:
            return False, "Wrong password."

        # Silently upgrade to Argon2
        new_hash = _hash_password(password)
        try:
            conn = sqlite3.connect(DB_FILE)
            conn.execute(
                "UPDATE users SET password=?, salt='', hash_type='argon2' WHERE username=?",
                (new_hash, username)
            )
            conn.commit()
            conn.close()
        except Exception as _upgrade_err:  # noqa: BLE001
            # Non-fatal: login succeeded; Argon2 upgrade failed (e.g. DB locked)
            print(f"[main] password upgrade skipped: {_upgrade_err}")
        return True, "Login successful."

    # ── Argon2 path ───────────────────────────────────────────────
    if _verify_password(password, stored_hash):
        return True, "Login successful."
    return False, "Wrong password."