"""
db.py  ──  SecureChat database  v6.3
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SELF-DESTRUCT ADDED (v6.3)
  [NEW]  get_expiring_messages() — fetch messages expiring within N seconds
  [NEW]  TTL options now: 10s / 30s / 1min / 5min / 1hr / 24hr / 7days / Never
  [NEW]  purge_expired() now returns list of deleted msg_ids so server can
         broadcast delete events to online clients in real time
"""

import sqlite3
import hashlib
import os
import pathlib
import time
import uuid as _uuid
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from cryptography.fernet import Fernet

_HERE    = pathlib.Path(__file__).parent.resolve()
DB_FILE  = str(_HERE / "users.db")
KEY_FILE = str(_HERE / "key.key")

_ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)

MESSAGE_TTL = 7 * 24 * 3600   # 7 days default


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    return conn


def load_or_create_key() -> bytes:
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            return f.read()
    key = Fernet.generate_key()
    with open(KEY_FILE, "wb") as f:
        f.write(key)
    print(f"[db] New server encryption key → {KEY_FILE}")
    return key


def _hash_password(pw: str) -> str:
    return _ph.hash(pw)


def _verify_password(pw: str, stored: str) -> bool:
    try:
        return _ph.verify(stored, pw)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def init_db():
    conn = _connect()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS users (
        username  TEXT PRIMARY KEY,
        password  TEXT NOT NULL,
        salt      TEXT NOT NULL DEFAULT '',
        hash_type TEXT NOT NULL DEFAULT 'argon2'
    )""")
    for col_def in [
        "salt TEXT NOT NULL DEFAULT ''",
        "hash_type TEXT NOT NULL DEFAULT 'sha256'",
        "totp_secret TEXT NOT NULL DEFAULT ''",
        "totp_enabled INTEGER NOT NULL DEFAULT 0",
    ]:
        try:
            c.execute("ALTER TABLE users ADD COLUMN " + col_def)
        except sqlite3.OperationalError:
            pass

    c.execute("""CREATE TABLE IF NOT EXISTS profiles (
        username     TEXT PRIMARY KEY,
        display_name TEXT NOT NULL DEFAULT '',
        bio          TEXT NOT NULL DEFAULT '',
        avatar       TEXT NOT NULL DEFAULT '',
        status_emoji TEXT NOT NULL DEFAULT '🟢',
        status_text  TEXT NOT NULL DEFAULT 'Online'
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS messages (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        sender      TEXT NOT NULL,
        receiver    TEXT NOT NULL,
        message     TEXT NOT NULL DEFAULT '',
        msg_type    TEXT NOT NULL DEFAULT 'dm',
        timestamp   REAL NOT NULL,
        expires_at  REAL,
        reply_to_id INTEGER,
        edited      INTEGER NOT NULL DEFAULT 0,
        deleted     INTEGER NOT NULL DEFAULT 0
    )""")
    for col_def in [
        "reply_to_id INTEGER",
        "edited INTEGER NOT NULL DEFAULT 0",
        "deleted INTEGER NOT NULL DEFAULT 0",
        "expires_at REAL",
    ]:
        try:
            c.execute("ALTER TABLE messages ADD COLUMN " + col_def)
        except sqlite3.OperationalError:
            pass

    c.execute("""CREATE TABLE IF NOT EXISTS reactions (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
        username   TEXT NOT NULL,
        emoji      TEXT NOT NULL,
        UNIQUE(message_id, username, emoji)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY,
        username   TEXT NOT NULL,
        ip         TEXT NOT NULL,
        login_time REAL NOT NULL
    )""")

    for ddl in [
        "CREATE INDEX IF NOT EXISTS idx_messages_sender   ON messages(sender)",
        "CREATE INDEX IF NOT EXISTS idx_messages_receiver ON messages(receiver)",
        "CREATE INDEX IF NOT EXISTS idx_messages_ts       ON messages(timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_messages_expires  ON messages(expires_at)",
        "CREATE INDEX IF NOT EXISTS idx_reactions_msgid   ON reactions(message_id)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_user     ON sessions(username)",
    ]:
        c.execute(ddl)

    c.execute("DELETE FROM sessions")
    conn.commit()
    conn.close()


# ── Auth ──────────────────────────────────────────────────────────

def register_user(username: str, password: str) -> tuple:
    username = username.strip()
    if len(username) < 3:
        return False, "Username must be at least 3 characters."
    if len(username) > 20:
        return False, "Username must be 20 characters or fewer."
    if not all(c.isalnum() or c == "_" for c in username):
        return False, "Username: letters, digits or _ only."
    if len(password) < 6:
        return False, "Password must be at least 6 characters."

    hashed = _hash_password(password)
    try:
        conn = _connect()
        conn.execute(
            "INSERT INTO users (username, password, salt, hash_type) VALUES (?,?,?,?)",
            (username, hashed, "", "argon2"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO profiles (username) VALUES (?)", (username,)
        )
        conn.commit()
        conn.close()
        return True, "Account created successfully."
    except sqlite3.IntegrityError:
        return False, "Username already taken."
    except Exception as e:
        return False, f"Database error: {e}"


def login_user(username: str, password: str) -> tuple:
    username = username.strip()
    try:
        conn = _connect()
        c = conn.cursor()
        c.execute(
            "SELECT password, salt, hash_type FROM users WHERE username=?", (username,)
        )
        row = c.fetchone()
        conn.close()
    except Exception as e:
        return False, f"Database error: {e}"

    if not row:
        return False, "User not found."

    stored_hash = row["password"]
    salt        = row["salt"]
    hash_type   = row["hash_type"]

    if hash_type == "sha256":
        if salt:
            legacy_ok = (
                hashlib.sha256((salt + password).encode()).hexdigest() == stored_hash
            )
        else:
            legacy_ok = (
                hashlib.sha256(password.encode()).hexdigest() == stored_hash
            )
        if not legacy_ok:
            return False, "Wrong password."
        new_hash = _hash_password(password)
        try:
            conn = _connect()
            conn.execute(
                "UPDATE users SET password=?, salt='', hash_type='argon2' WHERE username=?",
                (new_hash, username),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
        return True, "Login successful."

    if _verify_password(password, stored_hash):
        return True, "Login successful."
    return False, "Wrong password."


def change_password(username: str, old_pw: str, new_pw: str) -> tuple:
    ok, _ = login_user(username, old_pw)
    if not ok:
        return False, "Current password is incorrect."
    if len(new_pw) < 6:
        return False, "New password must be at least 6 characters."
    try:
        conn = _connect()
        conn.execute(
            "UPDATE users SET password=?, salt='', hash_type='argon2' WHERE username=?",
            (_hash_password(new_pw), username),
        )
        conn.commit()
        conn.close()
        return True, "Password changed successfully."
    except Exception as e:
        return False, str(e)


# ── Profiles ──────────────────────────────────────────────────────

def get_profile(username: str) -> dict:
    try:
        conn = _connect()
        c = conn.cursor()
        c.execute("SELECT * FROM profiles WHERE username=?", (username,))
        row = c.fetchone()
        conn.close()
        if row:
            return dict(row)
    except Exception:
        pass
    return {
        "username": username, "display_name": "", "bio": "",
        "avatar": "", "status_emoji": "🟢", "status_text": "Online",
    }


def set_profile(
    username: str,
    display_name: str = "",
    bio: str = "",
    avatar: str = "",
    status_emoji: str = "🟢",
    status_text: str = "Online",
) -> bool:
    try:
        conn = _connect()
        conn.execute(
            """INSERT INTO profiles
               (username, display_name, bio, avatar, status_emoji, status_text)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(username) DO UPDATE SET
                 display_name = excluded.display_name,
                 bio          = excluded.bio,
                 avatar       = excluded.avatar,
                 status_emoji = excluded.status_emoji,
                 status_text  = excluded.status_text""",
            (username, display_name, bio, avatar, status_emoji, status_text),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[db] set_profile: {e}")
        return False


def get_all_profiles(include_avatars: bool = False) -> dict:
    try:
        conn = _connect()
        c = conn.cursor()
        if include_avatars:
            c.execute("SELECT * FROM profiles")
        else:
            c.execute(
                "SELECT username, display_name, bio, '' as avatar, "
                "status_emoji, status_text FROM profiles"
            )
        rows = c.fetchall()
        conn.close()
        return {r["username"]: dict(r) for r in rows}
    except Exception:
        return {}


# ── Messages ──────────────────────────────────────────────────────

def save_message(
    sender: str,
    receiver: str,
    message: str,
    msg_type: str = "dm",
    ttl: Optional[int] = MESSAGE_TTL,
    reply_to_id: Optional[int] = None,
) -> int:
    now     = time.time()
    expires = (now + ttl) if (ttl and ttl > 0) else None
    try:
        conn = _connect()
        cur  = conn.execute(
            "INSERT INTO messages "
            "(sender, receiver, message, msg_type, timestamp, expires_at, reply_to_id)"
            " VALUES (?,?,?,?,?,?,?)",
            (sender, receiver, message, msg_type, now, expires, reply_to_id),
        )
        mid = cur.lastrowid
        conn.commit()
        conn.close()
        return mid
    except Exception as e:
        print(f"[db] save_message: {e}")
        return -1


def edit_message(msg_id: int, new_text: str) -> bool:
    try:
        conn = _connect()
        conn.execute(
            "UPDATE messages SET message=?, edited=1 WHERE id=?", (new_text, msg_id)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[db] edit_message: {e}")
        return False


def delete_message(msg_id: int) -> bool:
    try:
        conn = _connect()
        conn.execute(
            "UPDATE messages SET deleted=1, message='[deleted]' WHERE id=?", (msg_id,)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[db] delete_message: {e}")
        return False


def get_message(msg_id: int) -> Optional[dict]:
    try:
        conn = _connect()
        c    = conn.cursor()
        c.execute("SELECT * FROM messages WHERE id=?", (msg_id,))
        row  = c.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


# ── NEW: get messages expiring within `within_secs` ───────────────

def get_expiring_messages(within_secs: int = 60) -> list:
    """
    Return all non-deleted messages that will expire within `within_secs`.
    Used by the server purge loop to broadcast delete events before they vanish.
    Returns list of dicts with id, sender, receiver, msg_type, expires_at.
    """
    now    = time.time()
    cutoff = now + within_secs
    try:
        conn = _connect()
        c    = conn.cursor()
        c.execute(
            """SELECT id, sender, receiver, msg_type, expires_at
               FROM messages
               WHERE expires_at IS NOT NULL
                 AND expires_at > ?
                 AND expires_at <= ?
                 AND deleted = 0""",
            (now, cutoff),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        print(f"[db] get_expiring_messages: {e}")
        return []


# ── Bulk helpers ──────────────────────────────────────────────────

def get_reactions_bulk(message_ids: list) -> dict:
    if not message_ids:
        return {}
    placeholders = ",".join("?" * len(message_ids))
    try:
        conn = _connect()
        c    = conn.cursor()
        c.execute(
            "SELECT message_id, emoji, COUNT(*) as cnt FROM reactions "
            "WHERE message_id IN (" + placeholders + ") GROUP BY message_id, emoji",
            message_ids,
        )
        rows   = c.fetchall()
        conn.close()
        result: dict = {}
        for r in rows:
            result.setdefault(r["message_id"], {})[r["emoji"]] = r["cnt"]
        return result
    except Exception:
        return {}


def _enrich_bulk(rows: list) -> list:
    if not rows:
        return []

    msg_ids   = [dict(r)["id"] for r in rows]
    reply_ids = [dict(r)["reply_to_id"] for r in rows if dict(r).get("reply_to_id")]
    reactions = get_reactions_bulk(msg_ids)

    reply_map: dict = {}
    if reply_ids:
        try:
            conn         = _connect()
            c            = conn.cursor()
            placeholders = ",".join("?" * len(reply_ids))
            c.execute(
                "SELECT id, sender, message FROM messages WHERE id IN ("
                + placeholders + ")",
                reply_ids,
            )
            for pr in c.fetchall():
                reply_map[pr["id"]] = {
                    "id":     pr["id"],
                    "sender": pr["sender"],
                    "text":   pr["message"][:80],
                }
            conn.close()
        except Exception:
            pass

    result = []
    for row in rows:
        d = dict(row)
        d["reactions"] = reactions.get(d["id"], {})
        if d.get("reply_to_id") and d["reply_to_id"] in reply_map:
            d["reply_preview"] = reply_map[d["reply_to_id"]]
        result.append(d)
    return result


def get_history(user_a: str, user_b: str, limit: int = 100) -> list:
    try:
        now  = time.time()
        conn = _connect()
        c    = conn.cursor()
        c.execute(
            """SELECT * FROM messages WHERE msg_type='dm'
               AND (expires_at IS NULL OR expires_at > ?)
               AND ((sender=? AND receiver=?) OR (sender=? AND receiver=?))
               ORDER BY timestamp DESC LIMIT ?""",
            (now, user_a, user_b, user_b, user_a, limit),
        )
        rows = list(reversed(c.fetchall()))
        conn.close()
        return _enrich_bulk(rows)
    except Exception as e:
        print(f"[db] get_history: {e}")
        return []


def get_group_history(limit: int = 100) -> list:
    try:
        now  = time.time()
        conn = _connect()
        c    = conn.cursor()
        c.execute(
            """SELECT * FROM messages WHERE msg_type='group'
               AND (expires_at IS NULL OR expires_at > ?)
               ORDER BY timestamp DESC LIMIT ?""",
            (now, limit),
        )
        rows = list(reversed(c.fetchall()))
        conn.close()
        return _enrich_bulk(rows)
    except Exception as e:
        print(f"[db] get_group_history: {e}")
        return []


# ── NEW: purge_expired returns deleted IDs ────────────────────────

def purge_expired() -> list:
    """
    Delete all expired messages and return their IDs so the server
    can broadcast delete_message events to online clients.
    """
    try:
        conn = _connect()
        c    = conn.cursor()
        c.execute(
            "SELECT id FROM messages WHERE expires_at IS NOT NULL AND expires_at < ?",
            (time.time(),),
        )
        ids = [r[0] for r in c.fetchall()]
        if ids:
            conn.execute(
                "DELETE FROM messages WHERE expires_at IS NOT NULL AND expires_at < ?",
                (time.time(),),
            )
            conn.commit()
        conn.close()
        return ids
    except Exception as e:
        print(f"[db] purge_expired: {e}")
        return []


# ── Reactions ─────────────────────────────────────────────────────

def toggle_reaction(message_id: int, username: str, emoji: str) -> dict:
    try:
        conn = _connect()
        cur  = conn.execute(
            "SELECT id FROM reactions WHERE message_id=? AND username=? AND emoji=?",
            (message_id, username, emoji),
        )
        if cur.fetchone():
            conn.execute(
                "DELETE FROM reactions WHERE message_id=? AND username=? AND emoji=?",
                (message_id, username, emoji),
            )
        else:
            conn.execute(
                "INSERT OR IGNORE INTO reactions (message_id, username, emoji) VALUES (?,?,?)",
                (message_id, username, emoji),
            )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[db] toggle_reaction: {e}")
    return get_reactions(message_id)


def get_reactions(message_id: int) -> dict:
    try:
        conn = _connect()
        c    = conn.cursor()
        c.execute(
            "SELECT emoji, COUNT(*) as cnt FROM reactions "
            "WHERE message_id=? GROUP BY emoji",
            (message_id,),
        )
        rows = c.fetchall()
        conn.close()
        return {r["emoji"]: r["cnt"] for r in rows}
    except Exception:
        return {}


# ── 2FA / TOTP ───────────────────────────────────────────────────

def generate_totp_secret(username: str) -> str:
    """Generate and store a new TOTP secret for the user. Returns the secret."""
    import pyotp
    secret = pyotp.random_base32()
    try:
        conn = _connect()
        conn.execute(
            "UPDATE users SET totp_secret=?, totp_enabled=0 WHERE username=?",
            (secret, username),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[db] generate_totp_secret: {e}")
    return secret


def enable_totp(username: str) -> bool:
    """Mark 2FA as enabled after user has verified their first code."""
    try:
        conn = _connect()
        conn.execute(
            "UPDATE users SET totp_enabled=1 WHERE username=?", (username,)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[db] enable_totp: {e}")
        return False


def disable_totp(username: str) -> bool:
    """Turn off 2FA and clear the secret."""
    try:
        conn = _connect()
        conn.execute(
            "UPDATE users SET totp_secret='', totp_enabled=0 WHERE username=?",
            (username,),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[db] disable_totp: {e}")
        return False


def get_totp_info(username: str) -> dict:
    """Return {secret, enabled} for the user."""
    try:
        conn = _connect()
        c    = conn.cursor()
        c.execute(
            "SELECT totp_secret, totp_enabled FROM users WHERE username=?",
            (username,),
        )
        row = c.fetchone()
        conn.close()
        if row:
            return {"secret": row[0], "enabled": bool(row[1])}
    except Exception as e:
        print(f"[db] get_totp_info: {e}")
    return {"secret": "", "enabled": False}


def verify_totp(username: str, code: str) -> bool:
    """Verify a 6-digit TOTP code. Returns True if valid."""
    import pyotp
    info = get_totp_info(username)
    if not info["secret"] or not info["enabled"]:
        return True   # 2FA not set up — let through
    totp = pyotp.TOTP(info["secret"])
    return totp.verify(code, valid_window=1)   # ±30 second window


# ── Sessions ──────────────────────────────────────────────────────

def add_session(username: str, ip: str) -> str:
    sid = str(_uuid.uuid4())
    try:
        conn = _connect()
        conn.execute(
            "INSERT INTO sessions (session_id, username, ip, login_time) VALUES (?,?,?,?)",
            (sid, username, ip, time.time()),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[db] add_session: {e}")
    return sid


def remove_session(session_id: str):
    try:
        conn = _connect()
        conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[db] remove_session: {e}")


def get_sessions(username: str) -> list:
    try:
        conn = _connect()
        c    = conn.cursor()
        c.execute(
            "SELECT * FROM sessions WHERE username=? ORDER BY login_time DESC",
            (username,),
        )
        rows = c.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def kick_session(session_id: str):
    remove_session(session_id)


def kick_all_other_sessions(username: str, keep_sid: str):
    try:
        conn = _connect()
        conn.execute(
            "DELETE FROM sessions WHERE username=? AND session_id!=?",
            (username, keep_sid),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[db] kick_all: {e}")