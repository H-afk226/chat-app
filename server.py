"""
server.py  ──  SecureChat server  v6.3
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SELF-DESTRUCT ADDED (v6.3)
  [NEW]  _purge_loop() now runs every 5 seconds (was 1 hour)
  [NEW]  purge_expired() returns deleted IDs → broadcast delete_message
         so all online clients remove the bubble in real time
  [NEW]  _warn_loop() runs every 5 seconds, finds messages expiring within
         30 seconds and broadcasts a self_destruct_warning so the client
         can start the visual countdown timer on the bubble
"""

import socket
import ssl
import threading
import json
import struct
import time
import pathlib
import re
import urllib.request
from typing import Optional

_HERE = pathlib.Path(__file__).parent.resolve()
from cryptography.fernet import Fernet
import db

HOST = "127.0.0.1"
PORT = 5555

clients: dict      = {}
public_keys: dict  = {}
clients_lock       = threading.Lock()
fernet: Optional[Fernet] = None

# ── Rate limiting ─────────────────────────────────────────────────
failed_attempts: dict = {}
blocked_until: dict   = {}
rate_lock             = threading.Lock()
FAIL_WINDOW = 60
MAX_FAILS   = 5
BLOCK_SECS  = 300


def _check_rate(ip: str) -> tuple:
    now = time.time()
    with rate_lock:
        if ip in blocked_until and now < blocked_until[ip]:
            return False, f"Blocked for {int(blocked_until[ip] - now)}s."
        recent = [t for t in failed_attempts.get(ip, []) if now - t < FAIL_WINDOW]
        failed_attempts[ip] = recent
        if len(recent) >= MAX_FAILS:
            blocked_until[ip] = now + BLOCK_SECS
            failed_attempts[ip] = []
            return False, f"Too many attempts. Blocked {BLOCK_SECS}s."
    return True, ""


def _fail(ip: str):
    with rate_lock:
        failed_attempts.setdefault(ip, []).append(time.time())


def _clear_rate(ip: str):
    with rate_lock:
        failed_attempts.pop(ip, None)
        blocked_until.pop(ip, None)


def _log(m: str):
    print(f"[{time.strftime('%H:%M:%S')}] {m}")


# ── Wire protocol ─────────────────────────────────────────────────

def send_msg(sock, payload: dict):
    try:
        raw = json.dumps(payload).encode()
        tok = fernet.encrypt(raw)
        sock.sendall(struct.pack(">I", len(tok)) + tok)
    except Exception as e:
        _log(f"[send_msg] ignored: {e}")


def recv_msg(sock) -> Optional[dict]:
    try:
        hdr = _recv_exact(sock, 4)
        if not hdr:
            return None
        n   = struct.unpack(">I", hdr)[0]
        tok = _recv_exact(sock, n)
        if not tok:
            return None
        return json.loads(fernet.decrypt(tok).decode())
    except Exception:
        return None


def _recv_exact(sock, n: int) -> Optional[bytes]:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def _sock(username: str):
    with clients_lock:
        info = clients.get(username)
    return info["sock"] if info else None


# ── URL preview ───────────────────────────────────────────────────

_URL_RE = re.compile(r'https?://[^\s<>"]+', re.I)


def _fetch_og(url: str) -> Optional[dict]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SecureChat/6.3"})
        with urllib.request.urlopen(req, timeout=4) as r:  # noqa: S310
            html = r.read(32768).decode("utf-8", errors="ignore")

        def _og(prop):
            m = re.search(
                r'<meta[^>]+property=["\']og:' + prop +
                r'["\'][^>]+content=["\']([^"\']+)', html, re.I,
            )
            if not m:
                m = re.search(
                    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:' +
                    prop + r'["\']', html, re.I,
                )
            return m.group(1).strip() if m else ""

        title = _og("title") or re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
        if hasattr(title, "group"):
            title = title.group(1).strip()
        return {
            "url":         url,
            "title":       str(title)[:120],
            "description": _og("description")[:200],
            "image":       _og("image"),
        }
    except Exception:
        return None


def _fetch_og_async(sock, url: str):
    def _run():
        og = _fetch_og(url)
        send_msg(sock, {"type": "url_preview_result", "url": url, "og": og})
    threading.Thread(target=_run, daemon=True).start()


# ── History delivery ──────────────────────────────────────────────

def _send_history(sock, username: str):
    grp = db.get_group_history(80)
    if grp:
        send_msg(sock, {"type": "history", "channel": "__GROUP__", "messages": grp})
    try:
        conn = db._connect()
        c    = conn.cursor()
        c.execute(
            """SELECT DISTINCT CASE WHEN sender=? THEN receiver ELSE sender END
               FROM messages WHERE msg_type='dm' AND (sender=? OR receiver=?)""",
            (username, username, username),
        )
        peers = [r[0] for r in c.fetchall()]
        conn.close()
    except Exception:
        peers = []
    for peer in peers:
        hist = db.get_history(username, peer, 80)
        if hist:
            send_msg(sock, {"type": "history", "channel": peer, "messages": hist})


# ── Client handler ────────────────────────────────────────────────

def handle_client(conn_sock, addr):
    username   = None
    session_id = None
    ip         = addr[0]
    _log(f"+ {addr}")

    try:
        ok, reason = _check_rate(ip)
        if not ok:
            send_msg(conn_sock, {"type": "auth_result", "ok": False, "reason": reason})
            return

        msg = recv_msg(conn_sock)
        if not msg or msg.get("type") not in ("login", "register"):
            send_msg(conn_sock, {"type": "auth_result", "ok": False, "reason": "Bad handshake"})
            return

        if msg["type"] == "login":
            ok, reason = db.login_user(msg["username"], msg["password"])
        else:
            ok, reason = db.register_user(msg["username"], msg["password"])

        if not ok:
            _fail(ip)
            send_msg(conn_sock, {"type": "auth_result", "ok": False, "reason": reason})
            return

        _clear_rate(ip)
        username   = msg["username"]
        session_id = db.add_session(username, ip)
        send_msg(conn_sock, {
            "type": "auth_result", "ok": True,
            "reason": reason, "session_id": session_id,
        })

        with clients_lock:
            if username in clients:
                send_msg(conn_sock, {
                    "type":    "system",
                    "message": "Already logged in from another location.",
                })
                return
            clients[username] = {"sock": conn_sock, "session_id": session_id}

        _log(f"✓ {username} ({len(clients)} online)")
        broadcast_system(f"{username} joined the chat")

        with clients_lock:
            snap = {k: v for k, v in public_keys.items() if k != username}
        if snap:
            send_msg(conn_sock, {"type": "public_key_bundle", "keys": snap})

        all_profiles = db.get_all_profiles(include_avatars=False)
        send_msg(conn_sock, {"type": "profile_bundle", "profiles": all_profiles})
        send_msg(conn_sock, {"type": "own_profile", "profile": db.get_profile(username)})
        send_msg(conn_sock, {"type": "session_list", "sessions": db.get_sessions(username)})

        send_online()
        _send_history(conn_sock, username)

        while True:
            msg = recv_msg(conn_sock)
            if not msg:
                break
            t = msg.get("type", "")

            if t == "public_key":
                pem = msg.get("pem", "")
                if pem:
                    with clients_lock:
                        public_keys[username] = pem
                    distribute_public_key(username, pem)
                    send_online()

            elif t in ("dh_init", "dh_response"):
                target = msg.get("to", "")
                sock_t = _sock(target)
                if sock_t:
                    msg["from"] = username
                    send_msg(sock_t, msg)

            elif t in ("call_offer", "call_answer", "call_end", "call_audio"):
                target = msg.get("to", "")
                sock_t = _sock(target)
                if sock_t:
                    msg["from"] = username
                    send_msg(sock_t, msg)
                    if t != "call_audio":
                        _log(f"[CALL:{t}] {username}→{target}")
                elif t == "call_offer":
                    send_msg(conn_sock, {
                        "type":    "system",
                        "message": f"📵 {target} is not online.",
                    })

            elif t == "typing":
                target = msg.get("to", "")
                sock_t = _sock(target)
                if sock_t:
                    send_msg(sock_t, {"type": "typing", "from": username})

            elif t == "profile_update":
                p = msg.get("profile", {})
                db.set_profile(
                    username,
                    p.get("display_name", ""), p.get("bio", ""),
                    p.get("avatar", ""), p.get("status_emoji", "🟢"),
                    p.get("status_text", "Online"),
                )
                updated = db.get_profile(username)
                broadcast_all({"type": "profile_update", "username": username, "profile": updated})

            elif t == "change_password":
                old_pw = msg.get("old_password", "")
                new_pw = msg.get("new_password", "")
                ok2, reason2 = db.change_password(username, old_pw, new_pw)
                send_msg(conn_sock, {
                    "type":    "system",
                    "message": f"{'✓' if ok2 else '✗'} {reason2}",
                })

            elif t == "edit_message":
                msg_id   = msg.get("msg_id")
                new_text = msg.get("new_text", "").strip()
                if msg_id and new_text:
                    row = db.get_message(msg_id)
                    if row and row["sender"] == username:
                        db.edit_message(msg_id, new_text)
                        broadcast_all({"type": "edit_message",
                                       "msg_id": msg_id, "new_text": new_text})

            elif t == "delete_message":
                msg_id = msg.get("msg_id")
                if msg_id:
                    row = db.get_message(msg_id)
                    if row and row["sender"] == username:
                        db.delete_message(msg_id)
                        broadcast_all({"type": "delete_message", "msg_id": msg_id})

            elif t == "reaction":
                msg_id = msg.get("msg_id")
                emoji  = msg.get("emoji", "")
                if msg_id and emoji:
                    counts = db.toggle_reaction(msg_id, username, emoji)
                    broadcast_all({"type": "reaction_update",
                                   "msg_id": msg_id, "counts": counts})

            elif t == "kick_session":
                sid_to_kick   = msg.get("session_id", "")
                sock_to_close = None
                with clients_lock:
                    for u, info in list(clients.items()):
                        if info["session_id"] == sid_to_kick and u != username:
                            sock_to_close = info["sock"]
                            break
                db.kick_session(sid_to_kick)
                if sock_to_close:
                    try:
                        sock_to_close.close()
                    except Exception:
                        pass
                send_msg(conn_sock, {
                    "type":     "session_list",
                    "sessions": db.get_sessions(username),
                })

            elif t == "url_preview":
                url = msg.get("url", "")
                if url:
                    _fetch_og_async(conn_sock, url)

            elif t == "profile_request":
                target_user = msg.get("username", "")
                if target_user:
                    profile = db.get_profile(target_user)
                    send_msg(conn_sock, {
                        "type":     "profile_update",
                        "username": target_user,
                        "profile":  profile,
                    })

            # ── 2FA management packets ─────────────────────────────
            elif t == "totp_setup_request":
                # Client wants to set up 2FA — generate secret + send QR URI
                secret = db.generate_totp_secret(username)
                import pyotp
                uri = pyotp.totp.TOTP(secret).provisioning_uri(
                    name=username,
                    issuer_name="SecureChat"
                )
                send_msg(conn_sock, {
                    "type":   "totp_setup_response",
                    "secret": secret,
                    "uri":    uri,
                })
                _log(f"[2FA] {username} setup started")

            elif t == "totp_verify_enable":
                # Client verified the first code — enable 2FA
                code = msg.get("code", "")
                info = db.get_totp_info(username)
                import pyotp
                totp = pyotp.TOTP(info["secret"])
                if totp.verify(code, valid_window=1):
                    db.enable_totp(username)
                    send_msg(conn_sock, {
                        "type":    "totp_enable_result",
                        "ok":      True,
                        "message": "2FA enabled successfully!",
                    })
                    _log(f"[2FA] {username} enabled 2FA")
                else:
                    send_msg(conn_sock, {
                        "type":    "totp_enable_result",
                        "ok":      False,
                        "message": "Invalid code. Please try again.",
                    })

            elif t == "totp_disable":
                # Client wants to turn off 2FA
                code = msg.get("code", "")
                if db.verify_totp(username, code):
                    db.disable_totp(username)
                    send_msg(conn_sock, {
                        "type":    "totp_disable_result",
                        "ok":      True,
                        "message": "2FA disabled.",
                    })
                    _log(f"[2FA] {username} disabled 2FA")
                else:
                    send_msg(conn_sock, {
                        "type":    "totp_disable_result",
                        "ok":      False,
                        "message": "Wrong code.",
                    })

            elif t == "totp_status_request":
                info = db.get_totp_info(username)
                send_msg(conn_sock, {
                    "type":    "totp_status",
                    "enabled": info["enabled"],
                })

            elif t == "message":
                receiver  = msg.get("receiver", "")
                text      = msg.get("message", "").strip()
                enc_data  = msg.get("encrypted_for")
                signature = msg.get("signature")
                reply_to  = msg.get("reply_to_id")
                ttl       = msg.get("ttl", db.MESSAGE_TTL)
                file_data = msg.get("file_data")

                if not text and not enc_data and not file_data:
                    continue

                if receiver == "__BROADCAST__":
                    broadcast_message(username, text, signature)

                elif receiver == "__GROUP__":
                    mid = db.save_message(
                        username, "__GROUP__", text,
                        msg_type="group", ttl=ttl, reply_to_id=reply_to,
                    )
                    group_message(username, text, enc_data, signature,
                                  mid, reply_to, ttl, file_data)

                else:
                    mid = db.save_message(
                        username, receiver, text,
                        msg_type="dm", ttl=ttl, reply_to_id=reply_to,
                    )
                    og = None
                    urls = _URL_RE.findall(text or "")
                    if urls:
                        def _og_callback(url=urls[0], sock=conn_sock, msg_id=mid):
                            result  = _fetch_og(url)
                            recv_sock = _sock(receiver)
                            if recv_sock and result:
                                send_msg(recv_sock, {
                                    "type":   "url_preview_result",
                                    "url":    url,
                                    "og":     result,
                                    "msg_id": msg_id,
                                })
                        threading.Thread(target=_og_callback, daemon=True).start()

                    private_message(username, receiver, text, enc_data, signature,
                                    mid, reply_to, ttl, file_data, og)

    except Exception as e:
        _log(f"[ERROR] {e}")
    finally:
        if username:
            with clients_lock:
                clients.pop(username, None)
                public_keys.pop(username, None)
            if session_id:
                db.remove_session(session_id)
            _log(f"- {username} left ({len(clients)} online)")
            broadcast_system(f"{username} left the chat")
            send_online()
        try:
            conn_sock.close()
        except Exception:
            pass


# ── Key distribution ──────────────────────────────────────────────

def distribute_public_key(username: str, pem: str):
    with clients_lock:
        snap = dict(clients)
    for u, info in snap.items():
        try:
            send_msg(info["sock"], {
                "type": "public_key_update", "username": username, "pem": pem,
            })
        except Exception:
            pass


# ── Message routing ───────────────────────────────────────────────

def private_message(sender, receiver, text, enc_data, signature,
                    msg_id, reply_to, ttl, file_data, og):
    receiver = receiver.strip()
    with clients_lock:
        target_info = clients.get(receiver)
        sender_info = clients.get(sender)

    payload = {
        "type": "message", "sender": sender, "message": text,
        "broadcast": False, "msg_id": msg_id,
    }
    if enc_data:  payload["encrypted_for"] = enc_data
    if signature: payload["signature"]     = signature
    if reply_to:  payload["reply_to_id"]   = reply_to
    if ttl and ttl != db.MESSAGE_TTL: payload["ttl"] = ttl
    if file_data: payload["file_data"]     = file_data
    if og:        payload["og"]            = og

    if target_info:
        try:
            send_msg(target_info["sock"], payload)
        except Exception as e:
            _log(f"[DM ERROR] {e}")
    elif sender_info:
        send_msg(sender_info["sock"], {
            "type":    "system",
            "message": f"⚠ {receiver} is not online.",
        })


def group_message(sender, text, enc_data_map, signature,
                  msg_id, reply_to, ttl, file_data):
    with clients_lock:
        snap = dict(clients)
    for user, info in snap.items():
        if user == sender:
            continue
        payload = {
            "type": "message", "sender": sender, "message": text,
            "broadcast": False, "group": True, "msg_id": msg_id,
        }
        if enc_data_map and isinstance(enc_data_map, dict):
            ct = enc_data_map.get(user)
            if ct:
                payload["encrypted_for"] = ct
        if signature: payload["signature"]   = signature
        if reply_to:  payload["reply_to_id"] = reply_to
        if file_data: payload["file_data"]   = file_data
        try:
            send_msg(info["sock"], payload)
        except Exception:
            pass


def broadcast_message(sender, text, signature):
    with clients_lock:
        snap = dict(clients)
    payload = {"type": "message", "sender": sender, "message": text, "broadcast": True}
    if signature:
        payload["signature"] = signature
    for user, info in snap.items():
        if user != sender:
            try:
                send_msg(info["sock"], payload)
            except Exception:
                pass


def broadcast_system(text: str):
    with clients_lock:
        snap = dict(clients)
    for info in snap.values():
        try:
            send_msg(info["sock"], {"type": "system", "message": text})
        except Exception:
            pass


def broadcast_all(payload: dict):
    with clients_lock:
        snap = dict(clients)
    for info in snap.values():
        try:
            send_msg(info["sock"], payload)
        except Exception:
            pass


def send_online():
    with clients_lock:
        users = list(clients.keys())
        snap  = dict(clients)
    for info in snap.values():
        try:
            send_msg(info["sock"], {"type": "online_list", "users": users})
        except Exception:
            pass


# ── NEW: Self-destruct background loops ───────────────────────────

def _warn_loop():
    """
    Every 5 seconds, find messages expiring within the next 30 seconds
    and broadcast a self_destruct_warning so clients can start their
    visual countdown timers.
    """
    warned: set = set()   # track msg_ids we've already warned about
    while True:
        time.sleep(5)
        try:
            expiring = db.get_expiring_messages(within_secs=30)
            for row in expiring:
                mid = row["id"]
                if mid in warned:
                    continue
                warned.add(mid)
                remaining = max(0, int(row["expires_at"] - time.time()))
                broadcast_all({
                    "type":       "self_destruct_warning",
                    "msg_id":     mid,
                    "expires_at": row["expires_at"],
                    "remaining":  remaining,
                })
        except Exception as e:
            _log(f"[WARN_LOOP] {e}")


def _purge_loop():
    """
    Every 5 seconds, delete expired messages and broadcast delete_message
    to all online clients so bubbles vanish in real time.
    """
    while True:
        time.sleep(5)
        try:
            deleted_ids = db.purge_expired()
            for mid in deleted_ids:
                broadcast_all({"type": "delete_message", "msg_id": mid})
                _log(f"[PURGE] msg#{mid} self-destructed")
        except Exception as e:
            _log(f"[PURGE_LOOP] {e}")


# ── Entry point ───────────────────────────────────────────────────

def start_server():
    global fernet
    _log("SecureChat server v6.4 starting…")
    db.init_db()
    fernet = Fernet(db.load_or_create_key())
    threading.Thread(target=_warn_loop,  daemon=True).start()
    threading.Thread(target=_purge_loop, daemon=True).start()

    tls_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        tls_ctx.load_cert_chain(str(_HERE / "server.crt"), str(_HERE / "server.key"))
        use_tls = True
        _log("TLS enabled")
    except FileNotFoundError:
        use_tls = False
        _log("TLS cert not found — plain socket.")

    raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    raw.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    raw.bind((HOST, PORT))
    raw.listen(20)
    srv = tls_ctx.wrap_socket(raw, server_side=True) if use_tls else raw
    _log(f"Listening on {HOST}:{PORT}  TLS={'yes' if use_tls else 'no'}")

    while True:
        try:
            s, addr = srv.accept()
            threading.Thread(target=handle_client, args=(s, addr), daemon=True).start()
        except Exception as e:
            _log(f"[ACCEPT] {e}")


if __name__ == "__main__":
    start_server()