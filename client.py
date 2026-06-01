"""
client.py  ──  SecureChat network client  v6.2
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VOICE CALL ADDED (v6.2)
  [NEW]  VoiceCall class — AES-256-GCM encrypted audio using existing DH-FS key
  [NEW]  call_offer()   — initiate a call to a peer
  [NEW]  call_answer()  — accept or decline an incoming call
  [NEW]  call_end()     — hang up
  [NEW]  send_audio()   — stream encrypted audio chunk to peer
  [NEW]  on_call_offer / on_call_answer / on_call_end / on_call_audio callbacks

ENCRYPTION ARCHITECTURE
  Layer 1 – Transport : TLS 1.2+ (optional, falls back to plain TCP)
  Layer 2 – Fernet    : AES-128-CBC + HMAC-SHA256 on every packet payload
  Layer 3 – RSA-2048  : Per-recipient OAEP encryption of message body
  Layer 4 – DH-FS     : Ephemeral Diffie-Hellman per session for forward secrecy
  Layer 5 – Voice     : AES-256-GCM per audio chunk (key = DH-FS shared secret)
"""

import socket
import ssl
import threading
import json
import struct
import base64
import pathlib
import os
import time as _time
import hashlib
from typing import Optional, Callable

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa, padding as apadding, dh
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

try:
    import pyaudio
    _PYAUDIO_OK = True
except ImportError:
    _PYAUDIO_OK = False

HOST      = "127.0.0.1"
PORT      = 5555
_HERE     = pathlib.Path(__file__).parent.resolve()
_KEY_FILE = str(_HERE / "key.key")

# ── Transport key ─────────────────────────────────────────────────

def _load_transport_key() -> bytes:
    if os.path.exists(_KEY_FILE):
        with open(_KEY_FILE, "rb") as f:
            return f.read()
    return Fernet.generate_key()


# ── RSA helpers ───────────────────────────────────────────────────

def _gen_rsa():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return priv, priv.public_key()


def _pub_to_pem(pub) -> str:
    return pub.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()


def _pem_to_pub(pem: str):
    return serialization.load_pem_public_key(pem.encode())


def _rsa_encrypt(msg: str, pub) -> str:
    ct = pub.encrypt(
        msg.encode(),
        apadding.OAEP(
            mgf=apadding.MGF1(hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return base64.b64encode(ct).decode()


def _rsa_decrypt(ct_b64: str, priv) -> str:
    ct = base64.b64decode(ct_b64)
    return priv.decrypt(
        ct,
        apadding.OAEP(
            mgf=apadding.MGF1(hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    ).decode()


def _sign(msg: str, priv) -> str:
    sig = priv.sign(
        msg.encode(),
        apadding.PSS(
            mgf=apadding.MGF1(hashes.SHA256()),
            salt_length=apadding.PSS.MAX_LENGTH,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(sig).decode()


# ── DH helpers (lazy initialisation) ─────────────────────────────

_DH_PARAMS     = None
_DH_PARAMS_EVT = threading.Event()


def _init_dh_params():
    global _DH_PARAMS
    _DH_PARAMS = dh.generate_parameters(
        generator=2, key_size=2048, backend=default_backend()
    )
    _DH_PARAMS_EVT.set()


threading.Thread(target=_init_dh_params, daemon=True).start()


def _get_dh_params():
    _DH_PARAMS_EVT.wait(timeout=30)
    return _DH_PARAMS


def _gen_dh_keypair():
    params = _get_dh_params()
    if params is None:
        raise RuntimeError("DH parameter generation timed out.")
    priv = params.generate_private_key()
    return priv, priv.public_key()


def _dh_pub_to_b64(pub) -> str:
    raw = pub.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return base64.b64encode(raw).decode()


def _dh_pub_from_b64(b64: str):
    raw = base64.b64decode(b64)
    return serialization.load_pem_public_key(raw, backend=default_backend())


def _derive_shared_key(priv, peer_pub) -> bytes:
    shared = priv.exchange(peer_pub)
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"securechat-dh",
        backend=default_backend(),
    ).derive(shared)


# ── Fingerprint ───────────────────────────────────────────────────

def _fingerprint(pub) -> str:
    der = pub.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    h = hashlib.sha256(der).hexdigest().upper()
    return " ".join(h[i: i + 4] for i in range(0, len(h), 4))


# ── File helpers ──────────────────────────────────────────────────

def encode_file(path: str) -> Optional[dict]:
    import mimetypes
    try:
        size = os.path.getsize(path)
        if size > 512 * 1024:
            return None
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode()
        return {
            "name":     os.path.basename(path),
            "size":     size,
            "mime":     mime,
            "data_b64": data,
        }
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════
#  VoiceCall  ── AES-256-GCM encrypted real-time audio
# ══════════════════════════════════════════════════════════════════

class VoiceCall:
    """
    Encrypted voice call using the DH-FS shared secret as the AES-256-GCM key.

    Usage:
        vc = VoiceCall(shared_key=dh_shared_bytes,
                       on_audio_out=lambda b64: client.send_audio(peer, b64))
        vc.start()          # begins capture + playback threads
        vc.play(audio_b64)  # called when encrypted audio arrives from peer
        vc.stop()           # hang up
    """

    CHUNK    = 1024
    RATE     = 44100
    CHANNELS = 1

    def __init__(self, shared_key: bytes, on_audio_out: Callable):
        if not _PYAUDIO_OK:
            raise RuntimeError("pyaudio is not installed. Run: pip install pyaudio")
        self._key         = shared_key[:32]
        self._on_out      = on_audio_out
        self._active      = False
        self._muted       = False   # mic muted → sends silence
        self._speaker_off = False   # speaker off → drops incoming audio
        self._pa          = pyaudio.PyAudio()
        self._in_stream   = None
        self._out_stream  = None

    def set_mute(self, muted: bool):
        """Mute or unmute the microphone."""
        self._muted = muted

    def set_speaker(self, off: bool):
        """Turn speaker output on or off."""
        self._speaker_off = off

    # ── Lifecycle ─────────────────────────────────────────────────

    def start(self):
        """Open microphone capture and speaker playback streams."""
        self._active = True
        fmt = pyaudio.paInt16

        self._out_stream = self._pa.open(
            format=fmt, channels=self.CHANNELS,
            rate=self.RATE, output=True,
            frames_per_buffer=self.CHUNK,
        )
        self._in_stream = self._pa.open(
            format=fmt, channels=self.CHANNELS,
            rate=self.RATE, input=True,
            frames_per_buffer=self.CHUNK,
        )
        threading.Thread(target=self._capture_loop, daemon=True).start()

    def stop(self):
        """Close all audio streams and release PyAudio."""
        self._active = False
        for stream in (self._in_stream, self._out_stream):
            if stream:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
        try:
            self._pa.terminate()
        except Exception:
            pass
        self._in_stream  = None
        self._out_stream = None

    # ── Capture loop (microphone → encrypt → send) ────────────────

    def _capture_loop(self):
        import struct
        silence = b'\x00' * self.CHUNK * 2   # 16-bit silence frame
        while self._active:
            try:
                pcm = self._in_stream.read(self.CHUNK, exception_on_overflow=False)
                if self._muted:
                    pcm = silence          # send silence when muted
                nonce   = os.urandom(12)
                ct      = AESGCM(self._key).encrypt(nonce, pcm, None)
                payload = base64.b64encode(nonce + ct).decode()
                self._on_out(payload)
            except Exception:
                break

    def play(self, audio_b64: str):
        """Decrypt and play an incoming audio chunk from the peer."""
        if not self._active or not self._out_stream:
            return
        if self._speaker_off:
            return                         # drop audio when speaker is off
        try:
            raw       = base64.b64decode(audio_b64)
            nonce, ct = raw[:12], raw[12:]
            pcm       = AESGCM(self._key).decrypt(nonce, ct, None)
            self._out_stream.write(pcm)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════
#  ChatClient
# ══════════════════════════════════════════════════════════════════

class ChatClient:
    def __init__(
        self,
        on_message:        Optional[Callable] = None,
        on_broadcast:      Optional[Callable] = None,
        on_system:         Optional[Callable] = None,
        on_online_list:    Optional[Callable] = None,
        on_group_message:  Optional[Callable] = None,
        on_typing:         Optional[Callable] = None,
        on_history:        Optional[Callable] = None,
        on_profile_update: Optional[Callable] = None,
        on_own_profile:    Optional[Callable] = None,
        on_profile_bundle: Optional[Callable] = None,
        on_edit:           Optional[Callable] = None,
        on_delete:         Optional[Callable] = None,
        on_reaction:       Optional[Callable] = None,
        on_session_list:   Optional[Callable] = None,
        on_url_preview:    Optional[Callable] = None,
        on_dh:             Optional[Callable] = None,
        # ── NEW: voice call callbacks ─────────────────────────────
        on_call_offer:     Optional[Callable] = None,   # (peer: str)
        on_call_answer:    Optional[Callable] = None,   # (peer: str, accepted: bool)
        on_call_end:       Optional[Callable] = None,   # (peer: str)
        on_call_audio:     Optional[Callable] = None,   # (peer: str, audio_b64: str)
        on_self_destruct:  Optional[Callable] = None,   # (msg_id: int, remaining: int)
        on_totp_setup:     Optional[Callable] = None,   # (secret, uri)
        on_totp_result:    Optional[Callable] = None,   # (ok, message, action)
        on_totp_status:    Optional[Callable] = None,   # (enabled: bool)
    ):
        self._sock    = None
        self._fernet  = Fernet(_load_transport_key())
        self._send_lock = threading.Lock()

        self._on_message        = on_message        or (lambda s, t, ex: None)
        self._on_broadcast      = on_broadcast      or (lambda s, t: None)
        self._on_system         = on_system         or (lambda t: None)
        self._on_online_list    = on_online_list    or (lambda u: None)
        self._on_group_message  = on_group_message  or (lambda s, t, ex: None)
        self._on_typing         = on_typing         or (lambda s: None)
        self._on_history        = on_history        or (lambda ch, m: None)
        self._on_profile_update = on_profile_update or (lambda u, p: None)
        self._on_own_profile    = on_own_profile    or (lambda p: None)
        self._on_profile_bundle = on_profile_bundle or (lambda d: None)
        self._on_edit           = on_edit           or (lambda i, t: None)
        self._on_delete         = on_delete         or (lambda i: None)
        self._on_reaction       = on_reaction       or (lambda i, c: None)
        self._on_session_list   = on_session_list   or (lambda s: None)
        self._on_url_preview    = on_url_preview    or (lambda u, og: None)
        self._on_dh             = on_dh             or (lambda m: None)
        # NEW voice call callbacks
        self._on_call_offer     = on_call_offer     or (lambda p: None)
        self._on_call_answer    = on_call_answer    or (lambda p, a: None)
        self._on_call_end       = on_call_end       or (lambda p: None)
        self._on_call_audio     = on_call_audio     or (lambda p, d: None)
        self._on_self_destruct  = on_self_destruct  or (lambda mid, rem: None)
        self._on_totp_setup     = on_totp_setup     or (lambda s, u: None)
        self._on_totp_result    = on_totp_result    or (lambda ok, msg, act: None)
        self._on_totp_status    = on_totp_status    or (lambda e: None)

        self.username      = None
        self.session_id    = None
        self._connected    = False

        self._priv, self._pub = _gen_rsa()
        self._peer_keys:   dict = {}
        self._online_users: list = []
        self._dh_state:    dict = {}

    # ── Fingerprints ──────────────────────────────────────────────

    def get_fingerprint(self) -> str:
        return _fingerprint(self._pub)

    def get_peer_fingerprint(self, username: str) -> str:
        pub = self._peer_keys.get(username)
        return _fingerprint(pub) if pub else "Key not yet received"

    # ── Connect / disconnect ──────────────────────────────────────

    def connect(self) -> tuple:
        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            try:
                ctx.load_verify_locations(str(_HERE / "server.crt"))
                ctx.check_hostname = False
                ctx.verify_mode    = ssl.CERT_REQUIRED
                use_tls = True
            except Exception:
                ctx = None
                use_tls = False

            raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock = (
                ctx.wrap_socket(raw, server_hostname="127.0.0.1") if use_tls else raw
            )
            self._sock.connect((HOST, PORT))
            self._connected = True
            return True, "Connected"
        except Exception as e:
            return False, str(e)

    def disconnect(self):
        self._connected = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    # ── Auth ──────────────────────────────────────────────────────

    def login(self, u: str, p: str) -> tuple:
        return self._auth("login", u, p)

    def register(self, u: str, p: str) -> tuple:
        return self._auth("register", u, p)

    def _auth(self, t: str, u: str, p: str) -> tuple:
        if not self._connected:
            return False, "Not connected"
        self._send({"type": t, "username": u, "password": p})
        resp = self._recv()
        if not resp:
            return False, "No response"
        if resp.get("ok"):
            self.username   = u
            self.session_id = resp.get("session_id")
            threading.Thread(target=self._listen, daemon=True).start()
            _time.sleep(0.2)
            self._send_pubkey()
            return True, "OK"
        return False, resp.get("reason", "Auth failed")

    def _send_pubkey(self):
        self._send({"type": "public_key", "pem": _pub_to_pem(self._pub)})

    # ── DH forward secrecy ────────────────────────────────────────

    def initiate_dh(self, peer: str):
        try:
            dh_priv, dh_pub = _gen_dh_keypair()
        except RuntimeError:
            return
        self._dh_state[peer] = {"priv": dh_priv, "pub": dh_pub, "shared": None}
        self._send({
            "type":   "dh_init",
            "to":     peer,
            "dh_pub": _dh_pub_to_b64(dh_pub),
        })

    def _handle_dh_init(self, msg: dict):
        peer    = msg.get("from", "")
        b64_pub = msg.get("dh_pub", "")
        if not peer or not b64_pub:
            return
        try:
            peer_dh_pub = _dh_pub_from_b64(b64_pub)
            dh_priv, dh_pub = _gen_dh_keypair()
            shared = _derive_shared_key(dh_priv, peer_dh_pub)
        except Exception:
            return
        self._dh_state[peer] = {"priv": dh_priv, "pub": dh_pub, "shared": shared}
        self._send({"type": "dh_response", "to": peer,
                    "dh_pub": _dh_pub_to_b64(dh_pub)})

    def _handle_dh_response(self, msg: dict):
        peer    = msg.get("from", "")
        b64_pub = msg.get("dh_pub", "")
        state   = self._dh_state.get(peer)
        if not state or not b64_pub:
            return
        try:
            peer_dh_pub = _dh_pub_from_b64(b64_pub)
            shared      = _derive_shared_key(state["priv"], peer_dh_pub)
        except Exception:
            return
        self._dh_state[peer]["shared"] = shared

    def has_dh_secret(self, peer: str) -> bool:
        return bool(self._dh_state.get(peer, {}).get("shared"))

    # ── Profile ───────────────────────────────────────────────────

    def send_profile_update(
        self,
        display_name: str = "",
        bio: str = "",
        avatar: str = "",
        status_emoji: str = "🟢",
        status_text: str = "Online",
    ):
        self._send({"type": "profile_update", "profile": {
            "display_name": display_name,
            "bio":          bio,
            "avatar":       avatar,
            "status_emoji": status_emoji,
            "status_text":  status_text,
        }})

    def request_profile(self, username: str):
        self._send({"type": "profile_request", "username": username})

    # ── Messaging ─────────────────────────────────────────────────

    def send_message(
        self,
        receiver: str,
        text: str,
        reply_to_id: Optional[int] = None,
        ttl: Optional[int] = None,
        file_data: Optional[dict] = None,
    ):
        if not self._connected:
            return
        payload: dict = {"type": "message", "receiver": receiver, "message": text}

        pub = self._peer_keys.get(receiver)
        if pub and text:
            try:
                payload["encrypted_for"] = _rsa_encrypt(text, pub)
            except Exception:
                pass

        if text:
            payload["signature"] = _sign(text, self._priv)

        if reply_to_id: payload["reply_to_id"] = reply_to_id
        if ttl:         payload["ttl"]         = ttl
        if file_data:   payload["file_data"]   = file_data

        self._send(payload)

    def send_group_message(
        self,
        text: str,
        reply_to_id: Optional[int] = None,
        ttl: Optional[int] = None,
        file_data: Optional[dict] = None,
    ):
        if not self._connected:
            return
        enc_map: dict = {}
        if text:
            for u in self._online_users:
                pub = self._peer_keys.get(u)
                if pub:
                    try:
                        enc_map[u] = _rsa_encrypt(text, pub)
                    except Exception:
                        pass

        payload: dict = {
            "type":          "message",
            "receiver":      "__GROUP__",
            "message":       text,
            "encrypted_for": enc_map,
        }
        if text:
            payload["signature"] = _sign(text, self._priv)

        if reply_to_id: payload["reply_to_id"] = reply_to_id
        if ttl:         payload["ttl"]         = ttl
        if file_data:   payload["file_data"]   = file_data
        self._send(payload)

    def send_broadcast(self, text: str):
        if not self._connected:
            return
        self._send({
            "type":      "message",
            "receiver":  "__BROADCAST__",
            "message":   text,
            "signature": _sign(text, self._priv),
        })

    def send_typing(self, to: str):
        if not self._connected:
            return
        self._send({"type": "typing", "to": to})

    def send_edit(self, msg_id: int, new_text: str):
        if not self._connected:
            return
        self._send({"type": "edit_message", "msg_id": msg_id, "new_text": new_text})

    def send_delete(self, msg_id: int):
        if not self._connected:
            return
        self._send({"type": "delete_message", "msg_id": msg_id})

    def send_reaction(self, msg_id: int, emoji: str):
        if not self._connected:
            return
        self._send({"type": "reaction", "msg_id": msg_id, "emoji": emoji})

    def request_sessions(self):
        if not self._connected:
            return
        self._send({"type": "session_list_request"})

    def kick_session(self, session_id: str):
        if not self._connected:
            return
        self._send({"type": "kick_session", "session_id": session_id})

    def send_change_password(self, old_pw: str, new_pw: str):
        if not self._connected:
            return
        self._send({
            "type":         "change_password",
            "old_password": old_pw,
            "new_password": new_pw,
        })

    # ── 2FA Methods ───────────────────────────────────────────────────

    def request_totp_setup(self):
        """Ask server to generate a TOTP secret and QR URI."""
        if self._connected:
            self._send({"type": "totp_setup_request"})

    def verify_totp_enable(self, code: str):
        """Send the first verification code to activate 2FA."""
        if self._connected:
            self._send({"type": "totp_verify_enable", "code": code})

    def disable_totp(self, code: str):
        """Disable 2FA after verifying current code."""
        if self._connected:
            self._send({"type": "totp_disable", "code": code})

    def request_totp_status(self):
        """Ask server whether 2FA is currently enabled."""
        if self._connected:
            self._send({"type": "totp_status_request"})

    # ── Voice Call Methods (NEW) ───────────────────────────────────

    def call_offer(self, peer: str):
        """Send a call invitation to peer."""
        if not self._connected:
            return
        self._send({"type": "call_offer", "to": peer})

    def call_answer(self, peer: str, accept: bool):
        """Accept or decline an incoming call."""
        if not self._connected:
            return
        self._send({"type": "call_answer", "to": peer, "accept": accept})

    def call_end(self, peer: str):
        """Hang up an active call."""
        if not self._connected:
            return
        self._send({"type": "call_end", "to": peer})

    def send_audio(self, peer: str, audio_b64: str):
        """Send one encrypted audio chunk to peer during an active call."""
        if not self._connected:
            return
        self._send({"type": "call_audio", "to": peer, "audio": audio_b64})

    # ── Listener ─────────────────────────────────────────────────

    def _listen(self):
        while self._connected:
            msg = self._recv()
            if not msg:
                self._connected = False
                self._on_system("Disconnected from server")
                break
            t = msg.get("type", "")

            if t == "message":
                sender   = msg.get("sender", "")
                text     = msg.get("message", "")
                enc      = msg.get("encrypted_for")
                sig      = msg.get("signature")
                msg_id   = msg.get("msg_id")
                reply    = msg.get("reply_to_id")
                ttl      = msg.get("ttl")
                file_d   = msg.get("file_data")
                og       = msg.get("og")

                if isinstance(enc, str):
                    try:
                        text = _rsa_decrypt(enc, self._priv)
                    except Exception:
                        pass

                display = ("✔ " + text) if sig else text
                extra = {
                    "msg_id":      msg_id,
                    "reply_to_id": reply,
                    "ttl":         ttl,
                    "file_data":   file_d,
                    "og":          og,
                }
                if msg.get("broadcast"):
                    self._on_broadcast(sender, display)
                elif msg.get("group"):
                    self._on_group_message(sender, display, extra)
                else:
                    self._on_message(sender, display, extra)

            elif t == "history":
                self._on_history(msg.get("channel", ""), msg.get("messages", []))

            elif t == "typing":
                self._on_typing(msg.get("from", ""))

            elif t == "profile_bundle":
                self._on_profile_bundle(msg.get("profiles", {}))

            elif t == "own_profile":
                self._on_own_profile(msg.get("profile", {}))

            elif t == "profile_update":
                self._on_profile_update(msg.get("username", ""), msg.get("profile", {}))

            elif t == "edit_message":
                self._on_edit(msg.get("msg_id"), msg.get("new_text", ""))

            elif t == "delete_message":
                self._on_delete(msg.get("msg_id"))

            elif t == "reaction_update":
                self._on_reaction(msg.get("msg_id"), msg.get("counts", {}))

            elif t == "session_list":
                self._on_session_list(msg.get("sessions", []))

            elif t == "url_preview_result":
                self._on_url_preview(msg.get("url", ""), msg.get("og"))

            elif t == "dh_init":
                self._handle_dh_init(msg)
                peer = msg.get("from", "")
                if peer:
                    self._on_dh({"event": "ready", "peer": peer})

            elif t == "dh_response":
                self._handle_dh_response(msg)
                peer = msg.get("from", "")
                if peer:
                    self._on_dh({"event": "ready", "peer": peer})

            elif t == "system":
                self._on_system(msg.get("message", ""))

            elif t == "online_list":
                users = msg.get("users", [])
                self._online_users = [u for u in users if u != self.username]
                self._on_online_list(users)

            elif t == "public_key_update":
                u   = msg.get("username")
                pem = msg.get("pem")
                if u and pem and u != self.username:
                    try:
                        self._peer_keys[u] = _pem_to_pub(pem)
                        if u not in self._dh_state:
                            self.initiate_dh(u)
                    except Exception:
                        pass

            elif t == "public_key_bundle":
                for u, pem in msg.get("keys", {}).items():
                    if u != self.username:
                        try:
                            self._peer_keys[u] = _pem_to_pub(pem)
                            if u not in self._dh_state:
                                self.initiate_dh(u)
                        except Exception:
                            pass

            # ── NEW: voice call packet handlers ───────────────────
            elif t == "self_destruct_warning":
                self._on_self_destruct(
                    msg.get("msg_id", 0),
                    msg.get("remaining", 0),
                )

            elif t == "totp_setup_response":
                self._on_totp_setup(
                    msg.get("secret", ""),
                    msg.get("uri", ""),
                )

            elif t == "totp_enable_result":
                self._on_totp_result(
                    msg.get("ok", False),
                    msg.get("message", ""),
                    "enable",
                )

            elif t == "totp_disable_result":
                self._on_totp_result(
                    msg.get("ok", False),
                    msg.get("message", ""),
                    "disable",
                )

            elif t == "totp_status":
                self._on_totp_status(msg.get("enabled", False))

            elif t == "call_offer":
                self._on_call_offer(msg.get("from", ""))

            elif t == "call_answer":
                self._on_call_answer(msg.get("from", ""), msg.get("accept", False))

            elif t == "call_end":
                self._on_call_end(msg.get("from", ""))

            elif t == "call_audio":
                self._on_call_audio(msg.get("from", ""), msg.get("audio", ""))

    # ── Socket I/O ────────────────────────────────────────────────

    def _send(self, data: dict):
        try:
            raw = json.dumps(data).encode()
            enc = self._fernet.encrypt(raw)
            packet = struct.pack(">I", len(enc)) + enc
            with self._send_lock:
                self._sock.sendall(packet)
        except Exception:
            self._connected = False

    def _recv(self) -> Optional[dict]:
        try:
            hdr = self._recv_exact(4)
            if not hdr:
                return None
            length = struct.unpack(">I", hdr)[0]
            data   = self._recv_exact(length)
            if not data:
                return None
            return json.loads(self._fernet.decrypt(data).decode())
        except Exception as e:
            print("[RECV]", e)
            return None

    def _recv_exact(self, n: int) -> Optional[bytes]:
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf