"""
gui_client.py  ──  SecureChat GUI  v6.2
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VOICE CALL ADDED (v6.2)
  [NEW]  📞 Call button in the top header bar (next to search / save)
  [NEW]  CallWindow — floating encrypted call dialog with timer & hang-up
  [NEW]  Incoming call dialog — accept / decline with one click
  [NEW]  Call encryption badge shows AES-256-GCM + DH-FS key confirmation
  [NEW]  App._on_call_offer / _on_call_answer / _on_call_end / _on_call_audio
  [NEW]  App._start_call / App._end_call helpers
  [NEW]  on_call_* callbacks wired into ChatClient in App._new_client()
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import time
import math
import random
import secrets as _secrets
import base64

try:
    from PIL import Image, ImageTk
    _PIL = True
except ImportError:
    _PIL = False

    class Image:
        @staticmethod
        def open(*args, **kwargs):
            return None

    class ImageTk:
        @staticmethod
        def PhotoImage(*args, **kwargs):
            return None

from client import ChatClient, encode_file

# ══════════════════════════════════════════════════════════════════
#  DESIGN SYSTEM
# ══════════════════════════════════════════════════════════════════

LIGHT = {
    "bg": "#FAF6F0", "surface": "#F3EDE3", "card": "#FFFDF8",
    "elevated": "#EDE5D8", "input_bg": "#FBF8F3",
    "cyan": "#B07D4A", "cyan_dk": "#8A5E30", "purple": "#8B5E9B",
    "indigo": "#6B7DC4", "teal": "#4A9B8E", "success": "#3A7D44",
    "warning": "#C87C1A", "danger": "#C0392B", "info": "#2E7BB5",
    "text": "#2C2016", "dim": "#7A6A58", "ghost": "#B0A090",
    "me_bg": "#FFF4E0", "me_bdr": "#B07D4A",
    "them_bg": "#EDE8FF", "them_bdr": "#8B5E9B",
    "group_bg": "#E8F5EC", "group_bdr": "#3A7D44",
    "sidebar": "#EDE5D8", "sid_hover": "#E4D9C8",
    "sid_active": "#D9CAAF", "sid_head": "#D4C4AA",
    "border": "#D4C4AA", "topbar": "#F0E8DC",
    "badge": "#C0392B", "divider": "#E8DDD0",
}
DARK = {
    "bg": "#1A1A2E", "surface": "#16213E", "card": "#0F3460",
    "elevated": "#1A1A3E", "input_bg": "#0D1B2A",
    "cyan": "#E94560", "cyan_dk": "#C73652", "purple": "#9B59B6",
    "indigo": "#7F8FD4", "teal": "#1ABC9C", "success": "#2ECC71",
    "warning": "#F39C12", "danger": "#E74C3C", "info": "#3498DB",
    "text": "#E8E8F0", "dim": "#A0A8C0", "ghost": "#606880",
    "me_bg": "#2D1B33", "me_bdr": "#E94560",
    "them_bg": "#1B2D33", "them_bdr": "#9B59B6",
    "group_bg": "#1B332D", "group_bdr": "#2ECC71",
    "sidebar": "#16213E", "sid_hover": "#1E2D50",
    "sid_active": "#253660", "sid_head": "#0F2040",
    "border": "#2A3A60", "topbar": "#0F2040",
    "badge": "#E74C3C", "divider": "#1E2D50",
}
C = dict(LIGHT)

FM    = ("Georgia",  9)
FM_B  = ("Georgia",  9, "bold")
FU    = ("Georgia", 11)
FU_S  = ("Georgia",  9)
FU_B  = ("Georgia", 11, "bold")
FU_SB = ("Georgia",  9, "bold")
FH2   = ("Georgia", 14, "bold")
FH3   = ("Georgia", 12, "bold")


# ══════════════════════════════════════════════════════════════════
#  COLOUR / DRAWING HELPERS
# ══════════════════════════════════════════════════════════════════

def _rgb(h):
    h = h.lstrip("#")
    return int(h[:2], 16), int(h[2:4], 16), int(h[4:], 16)


def _lerp(c1, c2, t):
    r1, g1, b1 = _rgb(c1)
    r2, g2, b2 = _rgb(c2)
    return "#{:02x}{:02x}{:02x}".format(
        int(r1 + (r2 - r1) * t),
        int(g1 + (g2 - g1) * t),
        int(b1 + (b2 - b1) * t),
    )


def _grad_h(cv, x, y, w, h, c1, c2):
    for i in range(w):
        cv.create_line(x + i, y, x + i, y + h, fill=_lerp(c1, c2, i / max(w, 1)))


def _rr(cv, x1, y1, x2, y2, r=10, **kw):
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return cv.create_polygon(pts, smooth=True, **kw)


def _avatar_color(name: str) -> str:
    palette = [
        "#E91E63", "#9C27B0", "#673AB7", "#3F51B5",
        "#2196F3", "#00BCD4", "#009688", "#4CAF50",
        "#FF5722", "#FF9800", "#F06292", "#BA68C8",
    ]
    return palette[sum(ord(c) for c in (name or "?")) % len(palette)]


def _make_avatar_canvas(parent, name, size=38, avatar_b64="", bg=None):
    bg = bg or C["bg"]
    cv = tk.Canvas(parent, width=size, height=size, bg=bg, highlightthickness=0)

    # Handle preset avatar marker: "PRESET:{base64_json}"
    if avatar_b64 and avatar_b64.startswith("PRESET:"):
        try:
            import json as _jj
            data  = _jj.loads(base64.b64decode(avatar_b64[7:]).decode())
            color = data.get("color", _avatar_color(name))
            emoji = data.get("emoji", name[0].upper() if name else "?")
            cv.create_oval(2, 2, size-2, size-2, fill=color, outline="")
            font_size = max(8, size // 2)
            cv.create_text(size//2, size//2+1, text=emoji,
                           font=("Segoe UI Emoji", font_size))
        except Exception:
            cv.create_oval(2, 2, size-2, size-2,
                           fill=_avatar_color(name), outline="")
            cv.create_text(size//2, size//2,
                           text=(name[0].upper() if name else "?"),
                           fill="#FFF", font=FM_B)
        return cv

    # Handle real image
    if avatar_b64 and _PIL:
        try:
            from io import BytesIO
            img_data = base64.b64decode(avatar_b64)
            img      = Image.open(BytesIO(img_data)).resize((size, size))
            photo    = ImageTk.PhotoImage(img)
            cv._photo = photo
            cv.create_image(0, 0, anchor="nw", image=photo)
            return cv
        except Exception:
            pass

    # Fallback — letter avatar
    cv.create_oval(2, 2, size - 2, size - 2, fill=_avatar_color(name), outline="")
    cv.create_text(size // 2, size // 2,
                   text=(name[0].upper() if name else "?"),
                   fill="#FFF", font=FM_B)
    return cv


# ══════════════════════════════════════════════════════════════════
#  PRIMITIVE WIDGETS
# ══════════════════════════════════════════════════════════════════

class GradientButton(tk.Canvas):
    def __init__(self, parent, text, cmd=None,
                 w=200, h=44, c1=None, c2=None, fg=None, fnt=None, **kw):
        c1  = c1  or C["cyan"]
        c2  = c2  or C["purple"]
        fg  = fg  or "#FFFFFF"
        fnt = fnt or FU_B
        super().__init__(parent, width=w, height=h,
                         bg=parent["bg"], highlightthickness=0, **kw)
        self._cfg = (text, cmd, w, h, c1, c2, fg, fnt)
        self._draw(False)
        self.bind("<Enter>",    lambda e: self._draw(True))
        self.bind("<Leave>",    lambda e: self._draw(False))
        self.bind("<Button-1>", lambda e: cmd() if cmd else None)
        self.config(cursor="hand2")

    def _draw(self, hover):
        text, cmd, w, h, c1, c2, fg, fnt = self._cfg
        self.delete("all")
        if hover:
            for i in range(6, 0, -1):
                _rr(self, i, i, w - i, h - i, r=10,
                    fill="", outline=C["cyan"], width=1)
        _grad_h(self, 2, 2, w - 4, h - 4, c1, c2)
        _rr(self, 2, 2, w - 2, h - 2, r=10,
            fill="", outline=C["cyan"] if hover else "", width=1)
        self.create_text(w // 2, h // 2, text=text, fill=fg, font=fnt)

    def update_text(self, t):
        self._cfg = (t,) + self._cfg[1:]
        self._draw(False)


class CyberEntry(tk.Frame):
    def __init__(self, parent, label, ph="", secret=False, width=28, bg=None, **kw):
        bg = bg or C["card"]
        super().__init__(parent, bg=bg, **kw)
        self._secret  = secret
        self._ph      = ph
        self._active  = False
        self._showing = False
        tk.Label(self, text=label, font=FM_B, fg=C["cyan"], bg=bg).pack(anchor="w", pady=(0, 3))
        self._border = tk.Frame(self, bg=C["ghost"])
        self._border.pack(fill="x")
        inner = tk.Frame(self._border, bg=C["input_bg"], padx=10, pady=9)
        inner.pack(fill="x", padx=1, pady=1)
        self._icon = tk.Label(inner, text="🔒" if secret else "▸",
                              font=FU_S, bg=C["input_bg"], fg=C["dim"])
        self._icon.pack(side="left", padx=(0, 8))
        self.var = tk.StringVar()
        self._e  = tk.Entry(inner, textvariable=self.var, font=FU,
                            bg=C["input_bg"], fg=C["ghost"],
                            insertbackground=C["text"],
                            relief="flat", bd=0, width=width)
        self._e.insert(0, ph)
        self._e.pack(side="left", fill="x", expand=True)
        if secret:
            tog = tk.Label(inner, text="👁", font=FU_S,
                           bg=C["input_bg"], fg=C["dim"], cursor="hand2")
            tog.pack(side="right")
            tog.bind("<Button-1>", self._toggle)
        self._e.bind("<FocusIn>",  self._fin)
        self._e.bind("<FocusOut>", self._fout)

    def _fin(self, e):
        if not self._active:
            self._e.delete(0, "end")
            self._e.config(
                fg=C["text"],
                show="●" if self._secret and not self._showing else "",
            )
            self._active = True
        self._border.config(bg=C["cyan"])
        self._icon.config(fg=C["cyan"])

    def _fout(self, e):
        if not self.var.get():
            self._active = False
            self._e.config(show="", fg=C["ghost"])
            self._e.insert(0, self._ph)
        self._border.config(bg=C["ghost"])
        self._icon.config(fg=C["dim"])

    def _toggle(self, e):
        if self._active:
            self._showing = not self._showing
            self._e.config(show="" if self._showing else "●")

    def get(self) -> str:
        return self.var.get() if self._active else ""

    def clear(self):
        self._active = False
        self._e.config(show="", fg=C["ghost"])
        self._e.delete(0, "end")
        self._e.insert(0, self._ph)


class PulseIndicator(tk.Canvas):
    def __init__(self, parent, size=10, color=None, bg=None, **kw):
        bg    = bg    or parent["bg"]
        color = color or C["success"]
        sz    = size + 8
        super().__init__(parent, width=sz, height=sz, bg=bg,
                         highlightthickness=0, **kw)
        self._c = color
        self._sz = sz
        self._r  = size // 2
        self._t  = 0.0
        self._animate()

    def _animate(self):
        if not self.winfo_exists():
            return
        self.delete("all")
        cx, cy = self._sz // 2, self._sz // 2
        s  = 0.5 + 0.5 * math.sin(self._t * 3)
        pr = int(self._r + 4 * s)
        self.create_oval(cx - pr, cy - pr, cx + pr, cy + pr,
                         outline=self._c, width=1, fill="")
        self.create_oval(cx - self._r, cy - self._r,
                         cx + self._r, cy + self._r,
                         fill=self._c, outline="")
        self._t += 0.15
        self.after(60, self._animate)


class UnreadBadge(tk.Canvas):
    def __init__(self, parent, **kw):
        super().__init__(parent, width=20, height=20,
                         bg=parent["bg"], highlightthickness=0, **kw)
        self._count = 0

    def set(self, n: int):
        self._count = n
        self.delete("all")
        if n <= 0:
            return
        self.create_oval(1, 1, 19, 19, fill=C["badge"], outline="")
        self.create_text(10, 10, text=str(min(n, 99)),
                         fill="#FFFFFF", font=FM_B)

    def increment(self):
        self.set(self._count + 1)

    def reset(self):
        self.set(0)

    @property
    def count(self):
        return self._count


class Toast(tk.Toplevel):
    def __init__(self, root, sender: str, preview: str):
        super().__init__(root)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.config(bg=C["card"])
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        w, h = 320, 72
        self.geometry(f"{w}x{h}+{sw - w - 20}+{sh - h - 60}")

        border = tk.Frame(self, bg=C["cyan"], padx=2, pady=2)
        border.pack(fill="both", expand=True)
        inner  = tk.Frame(border, bg=C["card"], padx=12, pady=10)
        inner.pack(fill="both", expand=True)
        row = tk.Frame(inner, bg=C["card"])
        row.pack(fill="x")

        av = tk.Canvas(row, width=32, height=32, bg=C["card"], highlightthickness=0)
        av.pack(side="left", padx=(0, 8))
        av.create_oval(2, 2, 30, 30, fill=_avatar_color(sender), outline="")
        av.create_text(16, 16,
                       text=sender[0].upper() if sender else "?",
                       fill="#FFF", font=FM_B)

        right = tk.Frame(row, bg=C["card"])
        right.pack(side="left", fill="x", expand=True)
        tk.Label(right, text=sender, font=FU_SB,
                 fg=C["cyan"], bg=C["card"]).pack(anchor="w")
        prev = (preview[:34] + "…") if len(preview) > 34 else preview
        tk.Label(right, text=prev, font=FU_S,
                 fg=C["dim"], bg=C["card"]).pack(anchor="w")

        self.after(3000, self._safe_destroy)

    def _safe_destroy(self):
        try:
            if self.winfo_exists():
                self.destroy()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════
#  CALL WINDOW  (NEW)
# ══════════════════════════════════════════════════════════════════

class IncomingCallDialog(tk.Toplevel):
    """Sleek incoming call screen with pulse animation."""

    def __init__(self, root, peer: str, on_accept, on_decline):
        super().__init__(root)
        self.resizable(False, False)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        W, H = 360, 480
        sx = root.winfo_x() + (root.winfo_width()  - W) // 2
        sy = root.winfo_y() + (root.winfo_height() - H) // 2
        self.geometry(f"{W}x{H}+{sx}+{sy}")
        self._peer     = peer
        self._accept   = on_accept
        self._decline  = on_decline
        self._running  = True
        self._t        = 0.0
        self._build()
        self._pulse()

    def _build(self):
        BG = "#0B0E1A"
        self.configure(bg=BG)
        # thin red border
        tk.Frame(self, bg="#E94560", height=3).pack(fill="x")

        # header
        hdr = tk.Frame(self, bg="#0F1225", pady=12)
        hdr.pack(fill="x")
        dot_cv = tk.Canvas(hdr, width=8, height=8, bg="#0F1225",
                           highlightthickness=0)
        dot_cv.pack(side="left", padx=(18, 6))
        dot_cv.create_oval(0, 0, 8, 8, fill="#E94560", outline="")
        tk.Label(hdr, text="INCOMING ENCRYPTED CALL",
                 font=("Consolas", 9, "bold"),
                 fg="#E94560", bg="#0F1225").pack(side="left")

        # avatar canvas with pulse
        self._av_cv = tk.Canvas(self, width=180, height=180,
                                bg=BG, highlightthickness=0)
        self._av_cv.pack(pady=(28, 0))

        # caller name
        tk.Label(self, text=self._peer,
                 font=("Georgia", 22, "bold"),
                 fg="#FFFFFF", bg=BG).pack(pady=(14, 2))
        tk.Label(self, text="is calling you...",
                 font=("Georgia", 10, "italic"),
                 fg="#4A5080", bg=BG).pack()

        # enc strip
        strip = tk.Frame(self, bg="#0F1225", pady=8)
        strip.pack(fill="x", padx=36, pady=16)
        tk.Label(strip,
                 text="\U0001f512  AES-256-GCM  \u00b7  DH-FS  \u00b7  E2E Encrypted",
                 font=("Consolas", 8), fg="#2ECC71", bg="#0F1225").pack()

        # buttons
        btn_row = tk.Frame(self, bg=BG)
        btn_row.pack(pady=4)
        self._make_call_btn(btn_row, "#C0392B", "#E74C3C",
                            "\U0001f4f5", "Decline",
                            self._do_decline).pack(side="left", padx=28)
        self._make_call_btn(btn_row, "#1A7A40", "#2ECC71",
                            "\U0001f4de", "Accept",
                            self._do_accept).pack(side="left", padx=28)

    def _make_call_btn(self, parent, fill, outline, icon, label, cmd):
        col = tk.Frame(parent, bg=parent["bg"])
        cv  = tk.Canvas(col, width=72, height=72,
                        bg=parent["bg"], highlightthickness=0, cursor="hand2")
        cv.pack()
        cv.create_oval(4, 4, 68, 68, fill=fill, outline=outline, width=2,
                       tags="oval")
        cv.create_text(36, 36, text=icon,
                       font=("Segoe UI Emoji", 22), fill="#fff", tags="ico")
        cv.bind("<Button-1>", lambda e: cmd())
        cv.bind("<Enter>",    lambda e: cv.itemconfig("oval", fill=outline))
        cv.bind("<Leave>",    lambda e: cv.itemconfig("oval", fill=fill))
        tk.Label(col, text=label, font=("Georgia", 9),
                 fg=outline, bg=parent["bg"]).pack(pady=(5, 0))
        return col

    def _pulse(self):
        if not self._running or not self.winfo_exists():
            return
        cv  = self._av_cv
        BG  = "#0B0E1A"
        cx, cy, r = 90, 90, 44
        cv.delete("all")
        for i in range(4):
            phase  = (self._t + i * 0.25) % 1.0
            radius = int(r + 38 * phase)
            fade   = int(220 * (1 - phase))
            g      = min(fade + 100, 255)
            col    = f"#{fade//6:02x}{g:02x}{fade//6:02x}"
            cv.create_oval(cx - radius, cy - radius,
                           cx + radius, cy + radius,
                           outline=col, width=2, fill="")
        color = _avatar_color(self._peer)
        cv.create_oval(cx - r, cy - r, cx + r, cy + r,
                       fill=color, outline="#2ECC71", width=3)
        cv.create_text(cx, cy + 2,
                       text=self._peer[0].upper() if self._peer else "?",
                       fill="#fff", font=("Georgia", 28, "bold"))
        self._t = (self._t + 0.018) % 1.0
        self.after(35, self._pulse)

    def _do_accept(self):
        self._running = False
        self.destroy()
        self._accept()

    def _do_decline(self):
        self._running = False
        self.destroy()
        self._decline()


class CallWindow(tk.Toplevel):
    """
    Active call window — animated equaliser waveform, mute & speaker
    toggle buttons wired to the live VoiceCall instance.
    """

    BARS = 32

    def __init__(self, root, peer: str, on_hangup, voice_call=None):
        super().__init__(root)
        self.resizable(False, False)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        W, H = 340, 500
        sx = root.winfo_x() + root.winfo_width() - W - 24
        sy = root.winfo_y() + 70
        self.geometry(f"{W}x{H}+{sx}+{sy}")
        self.protocol("WM_DELETE_WINDOW", on_hangup)

        self._peer        = peer
        self._on_hangup   = on_hangup
        self._voice_call  = voice_call   # live VoiceCall reference for mute/spk
        self._start       = time.time()
        self._running     = True
        self._wave_t      = 0.0
        self._muted       = False
        self._spk_off     = False
        self._dx = self._dy = 0
        self._build()
        self._tick()
        self._wave()

    def _build(self):
        BG   = "#080F1C"
        TEAL = "#00D4AA"
        self.configure(bg=BG)

        # teal top border
        tk.Frame(self, bg=TEAL, height=3).pack(fill="x")

        # draggable header
        hdr = tk.Frame(self, bg="#0A1628", pady=10)
        hdr.pack(fill="x")
        hdr.bind("<ButtonPress-1>", self._ds)
        hdr.bind("<B1-Motion>",     self._dm)
        dot = tk.Canvas(hdr, width=8, height=8, bg="#0A1628",
                        highlightthickness=0)
        dot.pack(side="left", padx=(16, 6))
        dot.create_oval(0, 0, 8, 8, fill=TEAL, outline="")
        tk.Label(hdr, text="ENCRYPTED CALL",
                 font=("Consolas", 9, "bold"),
                 fg=TEAL, bg="#0A1628").pack(side="left")
        BG2 = "#080F1C"

        # avatar
        av_cv = tk.Canvas(self, width=100, height=100,
                          bg=BG, highlightthickness=0)
        av_cv.pack(pady=(18, 0))
        color = _avatar_color(self._peer)
        # dashed ring
        for i in range(0, 360, 20):
            import math as _m
            x1 = 50 + 46 * _m.cos(_m.radians(i))
            y1 = 50 + 46 * _m.sin(_m.radians(i))
            x2 = 50 + 46 * _m.cos(_m.radians(i + 10))
            y2 = 50 + 46 * _m.sin(_m.radians(i + 10))
            av_cv.create_line(x1, y1, x2, y2, fill=TEAL, width=2)
        av_cv.create_oval(12, 12, 88, 88,
                          fill=color, outline=TEAL, width=2)
        av_cv.create_text(50, 51,
                          text=self._peer[0].upper() if self._peer else "?",
                          fill="#fff", font=("Georgia", 28, "bold"))

        # name + status
        tk.Label(self, text=self._peer,
                 font=("Georgia", 17, "bold"),
                 fg="#FFFFFF", bg=BG).pack(pady=(10, 1))
        self._status_lbl = tk.Label(self, text="Call in progress",
                                    font=("Georgia", 9),
                                    fg=TEAL, bg=BG)
        self._status_lbl.pack()

        # waveform
        self._wave_cv = tk.Canvas(self, width=310, height=60,
                                  bg=BG, highlightthickness=0)
        self._wave_cv.pack(pady=(14, 2))

        # timer
        self._timer_lbl = tk.Label(self, text="00:00",
                                   font=("Consolas", 34, "bold"),
                                   fg=TEAL, bg=BG)
        self._timer_lbl.pack(pady=(0, 2))

        # separator
        tk.Frame(self, bg=TEAL, height=1).pack(fill="x", pady=(12, 0))

        # control buttons row
        ctrl = tk.Frame(self, bg=BG, pady=14)
        ctrl.pack()

        # Mute
        self._mute_col = tk.Frame(ctrl, bg=BG)
        self._mute_col.pack(side="left", padx=18)
        self._mute_cv = tk.Canvas(self._mute_col, width=58, height=58,
                                  bg=BG, highlightthickness=0, cursor="hand2")
        self._mute_cv.pack()
        self._mute_lbl = tk.Label(self._mute_col, text="Mute",
                                  font=("Georgia", 8), fg="#3A6A7A", bg=BG)
        self._mute_lbl.pack(pady=(4, 0))
        self._mute_cv.bind("<Button-1>", lambda e: self._toggle_mute())
        self._draw_btn(self._mute_cv, "#0A2A2A", "#00D4AA", "\U0001f3a4")

        # Hang up — bigger
        hang_col = tk.Frame(ctrl, bg=BG)
        hang_col.pack(side="left", padx=18)
        hang_cv = tk.Canvas(hang_col, width=70, height=70,
                            bg=BG, highlightthickness=0, cursor="hand2")
        hang_cv.pack()
        hang_cv.create_oval(4, 4, 66, 66,
                            fill="#8B1010", outline="#E74C3C", width=2,
                            tags="oval")
        hang_cv.create_text(35, 35, text="\U0001f4f5",
                            font=("Segoe UI Emoji", 22), fill="#fff",
                            tags="ico")
        hang_cv.bind("<Button-1>", lambda e: self._on_hangup())
        hang_cv.bind("<Enter>",    lambda e: hang_cv.itemconfig("oval", fill="#C0392B"))
        hang_cv.bind("<Leave>",    lambda e: hang_cv.itemconfig("oval", fill="#8B1010"))
        tk.Label(hang_col, text="End Call",
                 font=("Georgia", 8), fg="#E74C3C", bg=BG).pack(pady=(4, 0))

        # Speaker
        self._spk_col = tk.Frame(ctrl, bg=BG)
        self._spk_col.pack(side="left", padx=18)
        self._spk_cv = tk.Canvas(self._spk_col, width=58, height=58,
                                 bg=BG, highlightthickness=0, cursor="hand2")
        self._spk_cv.pack()
        self._spk_lbl = tk.Label(self._spk_col, text="Speaker",
                                 font=("Georgia", 8), fg="#3A5A7A", bg=BG)
        self._spk_lbl.pack(pady=(4, 0))
        self._spk_cv.bind("<Button-1>", lambda e: self._toggle_spk())
        self._draw_btn(self._spk_cv, "#0A1A2A", "#3498DB", "\U0001f50a")

    # ── Button draw helper ────────────────────────────────────────

    def _draw_btn(self, cv, fill, outline, icon, muted_style=False):
        cv.delete("all")
        if muted_style:
            cv.create_oval(4, 4, 54, 54,
                           fill="#3A0A0A", outline="#E74C3C", width=2,
                           tags="oval")
            cv.create_text(29, 29, text=icon,
                           font=("Segoe UI Emoji", 18), fill="#E74C3C",
                           tags="ico")
        else:
            cv.create_oval(4, 4, 54, 54,
                           fill=fill, outline=outline, width=2,
                           tags="oval")
            cv.create_text(29, 29, text=icon,
                           font=("Segoe UI Emoji", 18), fill=outline,
                           tags="ico")

    # ── Mute toggle ───────────────────────────────────────────────

    def _toggle_mute(self):
        self._muted = not self._muted
        if self._voice_call:
            self._voice_call.set_mute(self._muted)
        if self._muted:
            self._draw_btn(self._mute_cv, "", "#E74C3C",
                           "\U0001f507", muted_style=True)
            self._mute_lbl.config(text="Unmute", fg="#E74C3C")
            self._status_lbl.config(text="\U0001f507  Microphone muted",
                                    fg="#E74C3C")
        else:
            self._draw_btn(self._mute_cv, "#0A2A2A", "#00D4AA", "\U0001f3a4")
            self._mute_lbl.config(text="Mute", fg="#3A6A7A")
            self._status_lbl.config(text="Call in progress", fg="#00D4AA")

    # ── Speaker toggle ────────────────────────────────────────────

    def _toggle_spk(self):
        self._spk_off = not self._spk_off
        if self._voice_call:
            self._voice_call.set_speaker(self._spk_off)
        if self._spk_off:
            self._draw_btn(self._spk_cv, "", "#E74C3C",
                           "\U0001f508", muted_style=True)
            self._spk_lbl.config(text="Off", fg="#E74C3C")
        else:
            self._draw_btn(self._spk_cv, "#0A1A2A", "#3498DB", "\U0001f50a")
            self._spk_lbl.config(text="Speaker", fg="#3A5A7A")

    # ── Drag ─────────────────────────────────────────────────────

    def _ds(self, e):
        self._dx, self._dy = e.x, e.y

    def _dm(self, e):
        self.geometry(f"+{self.winfo_x()+e.x-self._dx}"
                      f"+{self.winfo_y()+e.y-self._dy}")

    # ── Waveform ──────────────────────────────────────────────────

    def _wave(self):
        if not self._running or not self.winfo_exists():
            return
        cv   = self._wave_cv
        cv.delete("all")
        W, H = 310, 60
        gap  = W / self.BARS
        for i in range(self.BARS):
            x = int(i * gap + gap / 2)
            if self._muted:
                bh  = 3
                col = "#0A2020"
            else:
                bh  = int(4 + 24 * abs(math.sin(self._wave_t * 2.8 + i * 0.38)))
                t   = abs(math.sin(self._wave_t * 1.2 + i * 0.15))
                r   = int(0   + 60  * t)
                g   = int(180 + 75  * t)
                b   = int(150 + 100 * t)
                col = f"#{r:02x}{min(g,255):02x}{min(b,255):02x}"
            cv.create_rectangle(x - 4, H // 2 - bh,
                                x + 4, H // 2 + bh,
                                fill=col, outline="")
        self._wave_t += 0.07
        self.after(38, self._wave)

    # ── Timer ─────────────────────────────────────────────────────

    def _tick(self):
        if not self._running or not self.winfo_exists():
            return
        e    = int(time.time() - self._start)
        m, s = divmod(e, 60)
        self._timer_lbl.config(text=f"{m:02d}:{s:02d}")
        self.after(1000, self._tick)

    def close(self):
        self._running = False
        try:
            if self.winfo_exists():
                self.destroy()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════
#  SCROLL CHAT
# ══════════════════════════════════════════════════════════════════

class ScrollChat(tk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=C["bg"], **kw)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Chat.Vertical.TScrollbar",
            background=C["elevated"], troughcolor=C["surface"],
            bordercolor=C["surface"], arrowcolor=C["ghost"],
            relief="flat", gripcount=0,
        )
        self.canvas = tk.Canvas(self, bg=C["bg"], highlightthickness=0, bd=0)
        sb = ttk.Scrollbar(self, orient="vertical",
                           command=self.canvas.yview,
                           style="Chat.Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner  = tk.Frame(self.canvas, bg=C["bg"])
        self._win   = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfig(self._win, width=e.width),
        )
        self.canvas.bind("<Enter>", self._on_enter)
        self.canvas.bind("<Leave>", self._on_leave)

    def _on_enter(self, e):
        self.canvas.bind_all("<MouseWheel>", self._scroll)

    def _on_leave(self, e):
        self.canvas.unbind_all("<MouseWheel>")

    def _scroll(self, e):
        self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

    def bottom(self):
        self.canvas.update_idletasks()
        self.canvas.yview_moveto(1.0)

    def at_bottom(self):
        try:
            return self.canvas.yview()[1] >= 0.98
        except Exception:
            return True


# ══════════════════════════════════════════════════════════════════
#  PROFILE POPUP
# ══════════════════════════════════════════════════════════════════

class ProfilePopup(tk.Toplevel):
    def __init__(self, root, username: str, profile: dict,
                 fingerprint: str, on_dm=None):
        super().__init__(root)
        self.title(f"Profile — {username}")
        self.resizable(False, False)
        self.configure(bg=C["card"])
        self.attributes("-topmost", True)
        self.geometry(f"360x440+{root.winfo_x() + 200}+{root.winfo_y() + 80}")
        self._build(username, profile, fingerprint, on_dm)

    def _build(self, username, profile, fingerprint, on_dm):
        pad = tk.Frame(self, bg=C["card"], padx=24, pady=18)
        pad.pack(fill="both", expand=True)

        av_cv = _make_avatar_canvas(pad, username, size=70,
                                    avatar_b64=profile.get("avatar", ""),
                                    bg=C["card"])
        av_cv.pack(pady=(0, 8))

        dn = profile.get("display_name", "") or username
        tk.Label(pad, text=dn, font=FH2, fg=C["text"], bg=C["card"]).pack()
        tk.Label(pad, text=f"@{username}", font=FU_S,
                 fg=C["ghost"], bg=C["card"]).pack()
        emoji = profile.get("status_emoji", "🟢")
        stxt  = profile.get("status_text",  "Online")
        tk.Label(pad, text=f"{emoji}  {stxt}", font=FM,
                 fg=C["dim"], bg=C["card"]).pack(pady=4)

        bio = profile.get("bio", "")
        if bio:
            tk.Frame(pad, bg=C["border"], height=1).pack(fill="x", pady=6)
            tk.Label(pad, text=bio, font=FU_S, fg=C["dim"], bg=C["card"],
                     wraplength=300, justify="center").pack()

        tk.Frame(pad, bg=C["border"], height=1).pack(fill="x", pady=8)
        tk.Label(pad, text="🔑  Key Fingerprint (SHA-256)", font=FM_B,
                 fg=C["cyan"], bg=C["card"]).pack(anchor="w")
        fp_text = fingerprint if fingerprint else "Key not yet received"
        self._fp_lbl = tk.Label(pad, text=fp_text, font=("Consolas", 8),
                                fg=C["ghost"], bg=C["card"],
                                wraplength=310, justify="left")
        self._fp_lbl.pack(anchor="w", pady=(2, 2))

        def _copy():
            self.clipboard_clear()
            self.clipboard_append(fp_text)
            self._fp_lbl.config(text="✓ Copied!")
            self.after(1500, lambda: self._fp_lbl.config(text=fp_text))

        tk.Button(pad, text="Copy fingerprint", font=FM,
                  bg=C["elevated"], fg=C["text"], relief="flat",
                  cursor="hand2", command=_copy).pack(anchor="w", pady=(2, 0))

        if on_dm:
            tk.Frame(pad, bg=C["border"], height=1).pack(fill="x", pady=8)
            GradientButton(pad, f"💬  Message {username}",
                           cmd=lambda: (on_dm(username), self.destroy()),
                           w=312, h=40).pack()


# ══════════════════════════════════════════════════════════════════
#  PROFILE EDITOR
# ══════════════════════════════════════════════════════════════════

class ProfileEditor(tk.Toplevel):
    """
    Enhanced profile editor with:
    - Large avatar preview (100px)
    - 12 preset cartoon/emoji avatars to choose from
    - File picker to upload any custom image
    - Remove avatar option
    - Display name, bio, status
    """

    # 12 preset avatar emojis users can pick
    PRESET_AVATARS = [
        "🧑", "👨", "👩", "🧔",
        "🧕", "🤠", "🥳", "🥸",
        "🦸", "🦹", "🧙", "🧚",
    ]
    PRESET_COLORS = [
        "#E91E63","#9C27B0","#3F51B5","#2196F3",
        "#009688","#4CAF50","#FF9800","#FF5722",
        "#795548","#607D8B","#E91E63","#673AB7",
    ]

    def __init__(self, root, current: dict, on_save):
        super().__init__(root)
        self.title("Edit Profile")
        self.resizable(False, False)
        self.configure(bg=C["card"])
        self.attributes("-topmost", True)
        self.geometry(f"520x720+{root.winfo_x() + 120}+{root.winfo_y() + 30}")
        self._on_save        = on_save
        self._avatar_b64     = current.get("avatar", "")
        self._username       = current.get("username", "?")
        self._selected_preset = None
        self._build(current)

    def _build(self, p):
        # Scrollable container
        outer = tk.Frame(self, bg=C["card"])
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, bg=C["card"], highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        pad = tk.Frame(canvas, bg=C["card"], padx=28, pady=18)
        win = canvas.create_window((0, 0), window=pad, anchor="nw")
        pad.bind("<Configure>",
                 lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(win, width=e.width))
        canvas.bind("<Enter>",
                    lambda e: canvas.bind_all("<MouseWheel>",
                    lambda ev: canvas.yview_scroll(int(-1*(ev.delta/120)),"units")))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        # ── Header ────────────────────────────────────────────────
        tk.Label(pad, text="✦  EDIT PROFILE", font=FH2,
                 fg=C["cyan"], bg=C["card"]).pack(pady=(0, 16))

        # ── Large avatar preview ──────────────────────────────────
        av_section = tk.Frame(pad, bg=C["card"])
        av_section.pack(pady=(0, 6))

        self._av_cv = tk.Canvas(av_section, width=110, height=110,
                                bg=C["card"], highlightthickness=0)
        self._av_cv.pack()
        self._refresh_preview()

        # Avatar action buttons
        btn_row = tk.Frame(pad, bg=C["card"])
        btn_row.pack(pady=(8, 0))
        tk.Button(btn_row, text="📁  Upload Photo",
                  font=FM_B, bg=C["cyan"], fg="#fff",
                  relief="flat", cursor="hand2",
                  padx=10, pady=6,
                  command=self._upload_avatar).pack(side="left", padx=(0, 8))
        tk.Button(btn_row, text="🗑  Remove",
                  font=FM, bg=C["elevated"], fg=C["danger"],
                  relief="flat", cursor="hand2",
                  padx=10, pady=6,
                  command=self._remove_avatar).pack(side="left")

        # ── Preset avatars grid ───────────────────────────────────
        tk.Frame(pad, bg=C["border"], height=1).pack(fill="x", pady=(14, 8))
        tk.Label(pad, text="— OR CHOOSE A PRESET AVATAR —",
                 font=("Consolas", 8, "bold"),
                 fg=C["ghost"], bg=C["card"]).pack()

        grid_frame = tk.Frame(pad, bg=C["card"])
        grid_frame.pack(pady=(10, 0))
        self._preset_cvs = []

        for idx, (emoji, color) in enumerate(
                zip(self.PRESET_AVATARS, self.PRESET_COLORS)):
            col = idx % 6
            row = idx // 6
            cv  = tk.Canvas(grid_frame, width=62, height=62,
                            bg=C["card"], highlightthickness=0,
                            cursor="hand2")
            cv.grid(row=row, column=col, padx=4, pady=4)
            cv.create_oval(4, 4, 58, 58, fill=color,
                           outline="", tags="bg")
            cv.create_text(31, 32, text=emoji,
                           font=("Segoe UI Emoji", 22), tags="ico")
            cv.create_oval(2, 2, 60, 60, outline="",
                           width=3, fill="", tags="sel")
            cv.bind("<Button-1>",
                    lambda e, em=emoji, co=color, c=cv:
                    self._pick_preset(em, co, c))
            cv.bind("<Enter>",
                    lambda e, c=cv: c.itemconfig("bg",
                    fill=c.itemcget("bg", "fill")))
            self._preset_cvs.append(cv)

        # ── Display name ──────────────────────────────────────────
        tk.Frame(pad, bg=C["border"], height=1).pack(fill="x", pady=(16, 8))
        tk.Label(pad, text="DISPLAY NAME", font=FM_B,
                 fg=C["cyan"], bg=C["card"]).pack(anchor="w")
        self._dn_var = tk.StringVar(value=p.get("display_name", ""))
        tk.Entry(pad, textvariable=self._dn_var, font=FU,
                 bg=C["input_bg"], fg=C["text"],
                 insertbackground=C["cyan"],
                 relief="flat", bd=4).pack(fill="x", pady=(4, 10))

        # ── Bio ───────────────────────────────────────────────────
        tk.Label(pad, text="BIO", font=FM_B,
                 fg=C["cyan"], bg=C["card"]).pack(anchor="w")
        self._bio = tk.Text(pad, height=3, font=FU_S,
                            bg=C["input_bg"], fg=C["text"],
                            insertbackground=C["cyan"],
                            relief="flat", wrap="word")
        self._bio.insert("1.0", p.get("bio", ""))
        self._bio.pack(fill="x", pady=(4, 10))

        # ── Status ────────────────────────────────────────────────
        tk.Label(pad, text="STATUS", font=FM_B,
                 fg=C["cyan"], bg=C["card"]).pack(anchor="w")
        status_row = tk.Frame(pad, bg=C["card"])
        status_row.pack(fill="x", pady=(4, 10))
        self._emoji_var = tk.StringVar(value=p.get("status_emoji", "🟢"))
        EMOJIS = ["🟢","🔴","🟡","🎧","🏖","💤","🔥","📚","🎮","✈️","🎯","💪"]
        ttk.OptionMenu(status_row, self._emoji_var,
                       p.get("status_emoji", "🟢"),
                       *EMOJIS).pack(side="left", padx=(0, 8))
        self._status_var = tk.StringVar(value=p.get("status_text", "Online"))
        tk.Entry(status_row, textvariable=self._status_var, font=FU_S,
                 bg=C["input_bg"], fg=C["text"],
                 insertbackground=C["cyan"],
                 relief="flat", bd=4, width=20).pack(
                     side="left", fill="x", expand=True)

        # ── Save button ───────────────────────────────────────────
        tk.Frame(pad, bg=C["border"], height=1).pack(fill="x", pady=(10, 8))
        GradientButton(pad, "💾  Save Profile",
                       cmd=self._save, w=460, h=48).pack()

    # ── Avatar helpers ────────────────────────────────────────────

    def _refresh_preview(self):
        """Redraw the large avatar preview circle."""
        self._av_cv.delete("all")
        # Handle preset marker
        if self._avatar_b64 and self._avatar_b64.startswith("PRESET:"):
            try:
                import json as _jj
                data  = _jj.loads(base64.b64decode(
                    self._avatar_b64[7:]).decode())
                color = data.get("color", "#888888")
                emoji = data.get("emoji", "?")
                self._av_cv.create_oval(5, 5, 105, 105,
                                        fill=color, outline=C["cyan"], width=3)
                self._av_cv.create_text(55, 56, text=emoji,
                                        font=("Segoe UI Emoji", 36))
            except Exception:
                pass
            return
        if self._avatar_b64 and _PIL:
            try:
                from io import BytesIO
                raw   = base64.b64decode(self._avatar_b64)
                img   = Image.open(BytesIO(raw)).resize((100, 100))
                photo = ImageTk.PhotoImage(img)
                self._av_cv._photo = photo
                self._av_cv.create_oval(5, 5, 105, 105,
                                        fill=C["card"], outline=C["cyan"], width=3)
                self._av_cv.create_image(5, 5, anchor="nw", image=photo)
                self._av_cv.create_oval(5, 5, 105, 105,
                                        fill="", outline=C["cyan"], width=3)
                return
            except Exception:
                pass
        # Fallback — letter avatar
        color = _avatar_color(self._username)
        self._av_cv.create_oval(5, 5, 105, 105,
                                fill=color, outline=C["cyan"], width=3)
        self._av_cv.create_text(55, 56,
                                text=self._username[0].upper()
                                     if self._username else "?",
                                fill="#FFF",
                                font=("Georgia", 36, "bold"))

    def _pick_preset(self, emoji: str, color: str, selected_cv):
        """User clicked a preset avatar tile — bakes emoji+color into a real PNG."""
        # Clear all selection rings
        for cv in self._preset_cvs:
            cv.itemconfig("sel", outline="")
        # Highlight selected tile
        selected_cv.itemconfig("sel", outline=C["cyan"], width=3)
        self._selected_preset = (emoji, color)

        # Store color+emoji as special marker so we can reconstruct it
        # Format: "preset:{hex_color}:{emoji}"
        import json as _jj
        marker = base64.b64encode(
            _jj.dumps({"type":"preset","color":color,"emoji":emoji}).encode()
        ).decode()
        self._avatar_b64 = "PRESET:" + marker

        # Update preview canvas to show emoji on colored circle
        self._av_cv.delete("all")
        self._av_cv.create_oval(5, 5, 105, 105,
                                fill=color, outline=C["cyan"], width=3)
        self._av_cv.create_text(55, 56, text=emoji,
                                font=("Segoe UI Emoji", 36))
        self._selected_preset = (emoji, color)

    def _upload_avatar(self):
        """Open file explorer to pick a custom image."""
        path = filedialog.askopenfilename(
            title="Select Profile Picture",
            filetypes=[
                ("Images", "*.png *.jpg *.jpeg *.gif *.webp *.bmp"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        # Clear preset selection
        for cv in self._preset_cvs:
            cv.itemconfig("sel", outline="")
        self._selected_preset = None
        try:
            if _PIL:
                from io import BytesIO
                img = Image.open(path).convert("RGBA")
                # Crop to square first for clean circular look
                w, h = img.size
                mn   = min(w, h)
                left = (w - mn) // 2
                top  = (h - mn) // 2
                img  = img.crop((left, top, left + mn, top + mn))
                img  = img.resize((128, 128), Image.LANCZOS)
                buf  = BytesIO()
                img.save(buf, format="PNG")
                self._avatar_b64 = base64.b64encode(buf.getvalue()).decode()
                self._refresh_preview()
            else:
                with open(path, "rb") as f:
                    raw = f.read()
                if len(raw) > 512 * 1024:
                    messagebox.showwarning("File too large",
                        "Image must be under 512 KB.")
                    return
                self._avatar_b64 = base64.b64encode(raw).decode()
                messagebox.showinfo("Uploaded",
                    "Photo saved! Install Pillow for a live preview.")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _remove_avatar(self):
        """Clear the avatar — revert to letter avatar."""
        self._avatar_b64 = ""
        self._selected_preset = None
        for cv in self._preset_cvs:
            cv.itemconfig("sel", outline="")
        self._refresh_preview()

    def _save(self):
        self._on_save({
            "display_name": self._dn_var.get().strip(),
            "bio":          self._bio.get("1.0", "end").strip(),
            "avatar":       self._avatar_b64,
            "status_emoji": self._emoji_var.get(),
            "status_text":  self._status_var.get().strip() or "Online",
        })
        self.destroy()


# ══════════════════════════════════════════════════════════════════
#  SESSIONS PANEL
# ══════════════════════════════════════════════════════════════════

class SessionsPanel(tk.Toplevel):
    def __init__(self, root, sessions: list, my_session_id: str, on_kick):
        super().__init__(root)
        self.title("Active Sessions")
        self.resizable(False, False)
        self.configure(bg=C["card"])
        self.attributes("-topmost", True)
        self.geometry(f"420x380+{root.winfo_x() + 160}+{root.winfo_y() + 80}")
        self._on_kick = on_kick
        self._my_sid  = my_session_id
        self._build(sessions)

    def _build(self, sessions):
        pad = tk.Frame(self, bg=C["card"], padx=20, pady=16)
        pad.pack(fill="both", expand=True)
        tk.Label(pad, text="🖥  ACTIVE SESSIONS", font=FH2,
                 fg=C["cyan"], bg=C["card"]).pack(pady=(0, 12))
        tk.Label(pad, text="All devices logged into your account.",
                 font=FM, fg=C["dim"], bg=C["card"]).pack(pady=(0, 10))

        for s in sessions:
            sid    = s.get("session_id", "")
            ip     = s.get("ip", "?")
            ts     = s.get("login_time", 0)
            stamp  = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "?"
            is_me  = (sid == self._my_sid)

            row = tk.Frame(pad, bg=C["elevated"], padx=12, pady=8)
            row.pack(fill="x", pady=3)
            left = tk.Frame(row, bg=C["elevated"])
            left.pack(side="left", fill="x", expand=True)
            label = "🟢  THIS SESSION" if is_me else "🔵  Other Session"
            tk.Label(left, text=label, font=FM_B,
                     fg=C["success"] if is_me else C["info"],
                     bg=C["elevated"]).pack(anchor="w")
            tk.Label(left, text=f"IP: {ip}  ·  Login: {stamp}",
                     font=FM, fg=C["dim"], bg=C["elevated"]).pack(anchor="w")
            if not is_me:
                tk.Button(row, text="Kick", font=FM_B,
                          bg=C["danger"], fg="#FFF", relief="flat",
                          cursor="hand2",
                          command=lambda sid=sid: self._kick(sid)).pack(side="right", padx=(8, 0))

        tk.Frame(pad, bg=C["border"], height=1).pack(fill="x", pady=10)
        tk.Button(pad, text="Close", font=FM_B,
                  bg=C["elevated"], fg=C["text"], relief="flat",
                  cursor="hand2", command=self.destroy).pack()

    def _kick(self, sid):
        if messagebox.askyesno("Kick Session", "Remove this session?"):
            self._on_kick(sid)
            self.destroy()


# ══════════════════════════════════════════════════════════════════
#  MESSAGE BUBBLE
# ══════════════════════════════════════════════════════════════════

class Bubble(tk.Frame):
    def __init__(self, parent, text, sender, stamp, is_me,
                 is_group=False, from_history=False,
                 msg_id=None, reply_preview=None,
                 reactions=None, file_data=None, og=None,
                 avatar_b64="",
                 on_reply=None, on_edit=None, on_delete=None,
                 on_react=None, on_avatar_click=None):
        super().__init__(parent, bg=C["bg"])

        self._msg_id    = msg_id
        self._text      = text
        self._on_react  = on_react

        if is_group and not is_me:
            bg  = C["group_bg"]
            bdr = C["group_bdr"]
        elif is_me:
            bg  = C["me_bg"]
            bdr = C["me_bdr"]
        else:
            bg  = C["them_bg"]
            bdr = C["them_bdr"]

        side = "e" if is_me else "w"
        wrap = tk.Frame(self, bg=C["bg"])
        wrap.pack(anchor=side, padx=14, pady=3)

        if not is_me:
            row = tk.Frame(wrap, bg=C["bg"])
            row.pack(anchor="w", padx=4, pady=(0, 2))
            av = _make_avatar_canvas(row, sender, size=20,
                                     avatar_b64=avatar_b64, bg=C["bg"])
            av.pack(side="left", padx=(0, 5))
            if on_avatar_click:
                av.bind("<Button-1>", lambda e: on_avatar_click(sender))
                av.config(cursor="hand2")
            lbl_text = f"{sender}  {'👥' if is_group else ''}"
            name_lbl = tk.Label(row, text=lbl_text, font=FU_SB, fg=bdr, bg=C["bg"])
            name_lbl.pack(side="left")
            if on_avatar_click:
                name_lbl.bind("<Button-1>", lambda e: on_avatar_click(sender))
                name_lbl.config(cursor="hand2")

        bub = tk.Frame(wrap, bg=bg, padx=14, pady=10,
                       highlightbackground=bdr, highlightthickness=1)
        bub.pack()
        tk.Frame(bub, bg=bdr, height=2).pack(fill="x", pady=(0, 5))

        enc_tag = ("📂 history · e2e" if from_history
                   else "👥 group · e2e" if is_group
                   else "🔒 e2e encrypted")
        tk.Label(bub, text=enc_tag, font=("Consolas", 7),
                 fg=bdr, bg=bg).pack(anchor="w", pady=(0, 3))

        if reply_preview:
            rp       = tk.Frame(bub, bg=bdr, padx=1, pady=1)
            rp.pack(fill="x", pady=(0, 6))
            rp_inner = tk.Frame(rp, bg=bg, padx=8, pady=4)
            rp_inner.pack(fill="x")
            tk.Label(rp_inner, text=f"↩ {reply_preview.get('sender', '')}",
                     font=FM_B, fg=bdr, bg=bg).pack(anchor="w")
            tk.Label(rp_inner, text=reply_preview.get("text", "")[:60],
                     font=FM, fg=C["dim"], bg=bg).pack(anchor="w")

        if file_data and isinstance(file_data, dict):
            mime    = file_data.get("mime", "")
            name_f  = file_data.get("name", "file")
            data_b64 = file_data.get("data_b64", "")
            if mime.startswith("image/") and data_b64 and _PIL:
                try:
                    from io import BytesIO
                    raw   = base64.b64decode(data_b64)
                    img   = Image.open(BytesIO(raw))
                    img.thumbnail((300, 200))
                    photo = ImageTk.PhotoImage(img)
                    img_lbl = tk.Label(bub, image=photo, bg=bg)
                    img_lbl._photo = photo
                    img_lbl.pack(anchor="w", pady=(0, 4))
                except Exception:
                    pass

            def _save_file(d=file_data):
                path = filedialog.asksaveasfilename(initialfile=d.get("name", "file"))
                if path:
                    try:
                        with open(path, "wb") as f:
                            f.write(base64.b64decode(d.get("data_b64", "")))
                        messagebox.showinfo("Saved", f"Saved to {path}")
                    except Exception as ex:
                        messagebox.showerror("Error", str(ex))

            sz_kb = file_data.get("size", 0) // 1024
            tk.Button(bub, text=f"📎 {name_f}  ({sz_kb} KB)",
                      font=FM, bg=bdr, fg="#FFF", relief="flat",
                      cursor="hand2", command=_save_file).pack(anchor="w", pady=(0, 4))

        self._msg_lbl = tk.Label(bub, text=text, font=FU,
                                  fg=C["text"], bg=bg,
                                  wraplength=360, justify="left")
        self._msg_lbl.pack(anchor="w")

        if og and isinstance(og, dict) and og.get("title"):
            og_frame = tk.Frame(bub, bg=C["elevated"],
                                highlightbackground=C["border"],
                                highlightthickness=1, padx=8, pady=6)
            og_frame.pack(fill="x", pady=(6, 0))
            tk.Label(og_frame, text=og.get("title", "")[:80],
                     font=FM_B, fg=C["text"], bg=C["elevated"],
                     wraplength=340, justify="left").pack(anchor="w")
            desc = og.get("description", "")
            if desc:
                tk.Label(og_frame, text=desc[:120], font=FM,
                         fg=C["dim"], bg=C["elevated"],
                         wraplength=340, justify="left").pack(anchor="w")
            tk.Label(og_frame, text=og.get("url", "")[:60],
                     font=("Consolas", 7),
                     fg=C["cyan"], bg=C["elevated"]).pack(anchor="w")

        foot = tk.Frame(bub, bg=bg)
        foot.pack(anchor="e", pady=(5, 0))
        tk.Label(foot, text=stamp, font=("Consolas", 7),
                 fg=C["dim"], bg=bg).pack(side="left")
        if is_me:
            self._tick_lbl = tk.Label(foot, text="  ✓✓",
                                       font=FU_S, fg=C["cyan"], bg=bg)
            self._tick_lbl.pack(side="left")
        self._destruct_lbl = tk.Label(foot, text="",
                                      font=("Consolas", 7, "bold"),
                                      fg=C["danger"], bg=bg)
        self._destruct_lbl.pack(side="left")

        self._react_frame = tk.Frame(bub, bg=bg)
        self._react_frame.pack(anchor="w", pady=(4, 0))
        self._reactions = dict(reactions or {})
        self._react_bg  = bg
        self._render_reactions()

        self._menu = tk.Menu(self, tearoff=0, bg=C["card"],
                             fg=C["text"], activebackground=C["cyan"],
                             activeforeground="#FFF")
        self._menu.add_command(
            label="📋  Copy",
            command=lambda: (self.clipboard_clear(), self.clipboard_append(text)),
        )
        if on_reply and msg_id:
            self._menu.add_command(
                label="↩  Reply",
                command=lambda: on_reply(msg_id, text, sender),
            )
        if on_react and msg_id:
            self._menu.add_cascade(label="😊  React",
                                   menu=self._build_react_menu())
        if is_me and on_edit and msg_id is not None:
            self._menu.add_command(
                label="✏  Edit",
                command=lambda: on_edit(msg_id, text),
            )
        if is_me and on_delete and msg_id is not None:
            self._menu.add_command(
                label="🗑  Delete for everyone",
                command=lambda: on_delete(msg_id),
            )
        self._menu.add_separator()
        self._menu.add_command(label=f"ℹ  {sender}", state="disabled")

        for widget in [self, wrap, bub, self._msg_lbl, foot]:
            widget.bind("<Button-3>", self._show_menu)

    def _build_react_menu(self):
        m = tk.Menu(self._menu, tearoff=0, bg=C["card"],
                    fg=C["text"], activebackground=C["cyan"],
                    activeforeground="#FFF")
        for emoji in ["👍", "❤", "😂", "😮", "😢"]:
            m.add_command(
                label=emoji,
                command=lambda e=emoji: self._on_react(self._msg_id, e),
            )
        return m

    def _render_reactions(self):
        for w in self._react_frame.winfo_children():
            w.destroy()
        for emoji, count in self._reactions.items():
            pill = tk.Label(
                self._react_frame, text=f"{emoji} {count}",
                font=("Segoe UI Emoji", 9),
                bg=C["elevated"], fg=C["text"],
                padx=5, pady=1, relief="flat", cursor="hand2",
            )
            pill.pack(side="left", padx=2)
            if self._on_react and self._msg_id:
                pill.bind("<Button-1>",
                          lambda e, em=emoji: self._on_react(self._msg_id, em))

    def update_reactions(self, counts: dict):
        self._reactions = counts
        self._render_reactions()

    def mark_edited(self):
        cur = self._msg_lbl.cget("text")
        if not cur.endswith(" (edited)"):
            self._msg_lbl.config(text=cur + " (edited)")

    def start_destruct_timer(self, remaining):
        self._destruct_remaining = remaining
        self._do_destruct_tick()

    def _do_destruct_tick(self):
        if not self.winfo_exists():
            return
        r = getattr(self, "_destruct_remaining", 0)
        if r <= 0:
            self._destruct_lbl.config(text="  💥 0s")
            return
        color = "#FF0000" if r <= 5 else "#FF6600" if r <= 15 else C["warning"]
        self._destruct_lbl.config(text=f"  🔥 {r}s", fg=color)
        self._destruct_remaining -= 1
        self.after(1000, self._do_destruct_tick)

    def mark_deleted(self):
        self._msg_lbl.config(text="🗑  This message was deleted.",
                             fg=C["ghost"], font=FM)

    def _show_menu(self, e):
        self._menu.tk_popup(e.x_root, e.y_root)


class SystemBubble(tk.Frame):
    def __init__(self, parent, text):
        super().__init__(parent, bg=C["bg"])
        inner = tk.Frame(self, bg=C["surface"], padx=14, pady=4)
        inner.pack(pady=6)
        tk.Label(inner, text=f"⚡  {text}", font=FM,
                 fg=C["dim"], bg=C["surface"]).pack()


class DateSeparator(tk.Frame):
    def __init__(self, parent, label):
        super().__init__(parent, bg=C["bg"])
        row = tk.Frame(self, bg=C["bg"])
        row.pack(fill="x", pady=8, padx=20)
        tk.Frame(row, bg=C["border"], height=1).pack(
            side="left", fill="x", expand=True, pady=6)
        tk.Label(row, text=f"  {label}  ", font=FM,
                 fg=C["ghost"], bg=C["surface"],
                 padx=8, pady=2).pack(side="left")
        tk.Frame(row, bg=C["border"], height=1).pack(
            side="left", fill="x", expand=True, pady=6)


# ══════════════════════════════════════════════════════════════════
#  LOGIN / REGISTER
# ══════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════
#  2FA TOTP SETUP DIALOG
# ══════════════════════════════════════════════════════════════════

class TotpSetupDialog(tk.Toplevel):
    """Guides the user through enabling 2FA."""

    def __init__(self, root, secret, uri, on_verify):
        super().__init__(root)
        self.title("Set Up Two-Factor Authentication")
        self.resizable(False, False)
        self.configure(bg=C["card"])
        self.attributes("-topmost", True)
        w, h = 420, 560
        sx = root.winfo_x() + (root.winfo_width()  - w) // 2
        sy = root.winfo_y() + (root.winfo_height() - h) // 2
        self.geometry(f"{w}x{h}+{sx}+{sy}")
        self._on_verify = on_verify
        self._secret    = secret
        self._build(secret, uri)

    def _build(self, secret, uri):
        pad = tk.Frame(self, bg=C["card"], padx=28, pady=22)
        pad.pack(fill="both", expand=True)

        tk.Label(pad, text="🔐  TWO-FACTOR AUTHENTICATION",
                 font=FH2, fg=C["cyan"], bg=C["card"]).pack(pady=(0, 4))
        tk.Label(pad, text="Scan the QR code with Google Authenticator or Authy.",
                 font=FM, fg=C["dim"], bg=C["card"]).pack(pady=(0, 14))

        qr_frame = tk.Frame(pad, bg=C["card"])
        qr_frame.pack(pady=(0, 10))
        try:
            import qrcode
            from io import BytesIO
            qr  = qrcode.make(uri)
            buf = BytesIO()
            qr.save(buf, format="PNG")
            buf.seek(0)
            if _PIL:
                from PIL import Image as _Img, ImageTk as _ITk
                img   = _Img.open(buf).resize((200, 200))
                photo = _ITk.PhotoImage(img)
                lbl   = tk.Label(qr_frame, image=photo, bg=C["card"])
                lbl._photo = photo
                lbl.pack()
            else:
                tk.Label(qr_frame, text="[Install Pillow to see QR]",
                         font=FM, fg=C["warning"], bg=C["card"]).pack()
        except Exception as e:
            tk.Label(qr_frame, text=f"QR error: {e}",
                     font=FM, fg=C["danger"], bg=C["card"]).pack()

        tk.Frame(pad, bg=C["border"], height=1).pack(fill="x", pady=8)
        tk.Label(pad, text="Or enter this code manually:",
                 font=FM_B, fg=C["dim"], bg=C["card"]).pack(anchor="w")
        sec_row = tk.Frame(pad, bg=C["elevated"], padx=10, pady=8)
        sec_row.pack(fill="x", pady=(4, 10))
        spaced = " ".join(secret[i:i+4] for i in range(0, len(secret), 4))
        sec_lbl = tk.Label(sec_row, text=spaced,
                           font=("Consolas", 13, "bold"),
                           fg=C["cyan"], bg=C["elevated"])
        sec_lbl.pack(side="left")
        def _copy():
            self.clipboard_clear(); self.clipboard_append(secret)
            sec_lbl.config(text="✓ Copied!")
            self.after(1500, lambda: sec_lbl.config(text=spaced))
        tk.Button(sec_row, text="📋 Copy", font=FM,
                  bg=C["cyan"], fg="#fff", relief="flat",
                  cursor="hand2", command=_copy).pack(side="right")

        tk.Frame(pad, bg=C["border"], height=1).pack(fill="x", pady=8)
        tk.Label(pad, text="Enter the 6-digit code from your app to activate:",
                 font=FM_B, fg=C["text"], bg=C["card"]).pack(anchor="w")
        cf = tk.Frame(pad, bg=C["card"])
        cf.pack(pady=(6, 0))
        self._code_var = tk.StringVar()
        ce = tk.Entry(cf, textvariable=self._code_var,
                      font=("Consolas", 20, "bold"),
                      width=8, justify="center",
                      bg=C["input_bg"], fg=C["cyan"],
                      insertbackground=C["cyan"],
                      relief="flat", bd=6)
        ce.pack(side="left", padx=(0, 8))
        ce.focus_set()
        ce.bind("<Return>", lambda e: self._do_verify())
        self._msg_lbl = tk.Label(pad, text="", font=FM,
                                 fg=C["danger"], bg=C["card"])
        self._msg_lbl.pack(pady=(6, 0))
        GradientButton(pad, "✓  Activate 2FA",
                       cmd=self._do_verify, w=360, h=44).pack(pady=(10, 0))
        tk.Button(pad, text="Cancel", font=FM,
                  bg=C["elevated"], fg=C["dim"], relief="flat",
                  cursor="hand2", command=self.destroy).pack(pady=(6, 0))

    def _do_verify(self):
        code = self._code_var.get().strip()
        if len(code) != 6 or not code.isdigit():
            self._msg_lbl.config(text="⚠ Enter a 6-digit code.")
            return
        self._on_verify(code)

    def show_result(self, ok, message):
        if ok:
            self.destroy()
        else:
            self._msg_lbl.config(text=f"✗  {message}", fg=C["danger"])


# ══════════════════════════════════════════════════════════════════
#  2FA LOGIN SCREEN
# ══════════════════════════════════════════════════════════════════

class TotpLoginScreen(tk.Frame):
    """Shown after password login when 2FA is required."""

    def __init__(self, parent, username, on_success, on_back):
        super().__init__(parent, bg=C["bg"])
        self._username   = username
        self._on_success = on_success
        self._on_back    = on_back
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        card = tk.Frame(self, bg=C["card"], padx=50, pady=44)
        card.grid(row=0, column=0)
        tk.Label(card, text="🔐",
                 font=("Segoe UI Emoji", 36), bg=C["card"]).pack(pady=(0,8))
        tk.Label(card, text="Two-Factor Authentication",
                 font=FH2, fg=C["cyan"], bg=C["card"]).pack()
        tk.Label(card, text=f"Enter the 6-digit code for  {self._username}",
                 font=FM, fg=C["dim"], bg=C["card"]).pack(pady=(4,20))

        # 6 individual digit boxes
        df = tk.Frame(card, bg=C["card"])
        df.pack(pady=(0, 16))
        self._dvars   = []
        self._dentries = []
        for i in range(6):
            var = tk.StringVar()
            e   = tk.Entry(df, textvariable=var, width=2,
                           justify="center",
                           font=("Consolas", 26, "bold"),
                           bg=C["input_bg"], fg=C["cyan"],
                           insertbackground=C["cyan"],
                           highlightbackground=C["border"],
                           highlightthickness=1,
                           relief="flat", bd=8)
            e.pack(side="left", padx=4)
            self._dvars.append(var)
            self._dentries.append(e)
            e.bind("<KeyRelease>", lambda ev, idx=i: self._onkey(ev, idx))
        self._dentries[0].focus_set()

        self._msg = tk.Label(card, text="", font=FM,
                             fg=C["danger"], bg=C["card"])
        self._msg.pack(pady=(0,12))
        GradientButton(card, "⟶   VERIFY",
                       cmd=self._verify, w=440, h=48).pack(pady=(0,8))
        GradientButton(card, "←   BACK",
                       cmd=self._on_back, w=440, h=40,
                       c1=C["elevated"], c2=C["card"],
                       fg=C["dim"]).pack()
        tk.Label(card, text="Open your authenticator app to get the code.",
                 font=FM, fg=C["ghost"], bg=C["card"]).pack(pady=(16,0))

    def _onkey(self, event, idx):
        val = self._dvars[idx].get()
        if val and len(val) > 1:
            self._dvars[idx].set(val[-1]); val = val[-1]
        if val.isdigit() and idx < 5:
            self._dentries[idx+1].focus_set()
        if event.keysym == "BackSpace" and not val and idx > 0:
            self._dentries[idx-1].focus_set()
        code = "".join(v.get() for v in self._dvars)
        if len(code) == 6 and code.isdigit():
            self.after(100, self._verify)

    def _verify(self):
        code = "".join(v.get() for v in self._dvars)
        if len(code) != 6 or not code.isdigit():
            self._msg.config(text="⚠ Enter all 6 digits.")
            return
        self._msg.config(text="◌  Verifying…", fg=C["cyan"])
        self._on_success(code)

    def show_error(self, message):
        self._msg.config(text=f"✗  {message}", fg=C["danger"])
        for var in self._dvars: var.set("")
        self._dentries[0].focus_set()


# ══════════════════════════════════════════════════════════════════
#  CHAT PIN LOCK
# ══════════════════════════════════════════════════════════════════

import hashlib as _hashlib
import json   as _json
import pathlib as _pathlib

_CHAT_PINS_FILE = str(_pathlib.Path(__file__).parent / '.chat_pins')

def _load_chat_pins() -> dict:
    try:
        with open(_CHAT_PINS_FILE, 'r') as f:
            return _json.load(f)
    except Exception:
        return {}

def _save_chat_pins(pins: dict):
    with open(_CHAT_PINS_FILE, 'w') as f:
        _json.dump(pins, f)

def _hash_pin(pin: str) -> str:
    return _hashlib.sha256(pin.encode()).hexdigest()

def _set_chat_pin(contact: str, pin: str):
    pins = _load_chat_pins()
    pins[contact] = _hash_pin(pin)
    _save_chat_pins(pins)

def _remove_chat_pin(contact: str):
    pins = _load_chat_pins()
    pins.pop(contact, None)
    _save_chat_pins(pins)

def _chat_has_pin(contact: str) -> bool:
    return contact in _load_chat_pins()

def _verify_chat_pin(contact: str, pin: str) -> bool:
    pins = _load_chat_pins()
    return pins.get(contact, '') == _hash_pin(pin)


class ChatPinDialog(tk.Toplevel):
    '''
    Modal PIN entry dialog shown when opening a locked chat.
    Has a numpad + keyboard support.
    '''
    def __init__(self, root, contact: str, on_unlock, on_cancel):
        super().__init__(root)
        self.title('Locked Chat')
        self.resizable(False, False)
        self.overrideredirect(True)
        self.attributes('-topmost', True)
        W, H = 360, 560
        sx = root.winfo_x() + (root.winfo_width()  - W) // 2
        sy = root.winfo_y() + (root.winfo_height() - H) // 2
        self.geometry(f'{W}x{H}+{sx}+{sy}')
        self._contact   = contact
        self._on_unlock = on_unlock
        self._on_cancel = on_cancel
        self._pin       = ''
        self._attempts  = 0
        self._build()
        self.bind('<Key>', self._on_key)

    def _build(self):
        BG   = '#080F1C'
        TEAL = '#00D4AA'
        self.configure(bg=BG)
        tk.Frame(self, bg=TEAL, height=3).pack(fill='x')

        hdr = tk.Frame(self, bg='#0A1628', pady=10)
        hdr.pack(fill='x')
        tk.Label(hdr, text=f'🔒  {self._contact}  —  LOCKED CHAT',
                 font=('Consolas', 9, 'bold'),
                 fg=TEAL, bg='#0A1628').pack()

        tk.Label(self, text='🔒',
                 font=('Segoe UI Emoji', 32), bg=BG).pack(pady=(18, 4))
        tk.Label(self, text='Enter PIN to unlock',
                 font=('Georgia', 11), fg='#A0B0C0', bg=BG).pack()

        # PIN dots
        dots_row = tk.Frame(self, bg=BG)
        dots_row.pack(pady=16)
        self._dots = []
        for i in range(4):
            cv = tk.Canvas(dots_row, width=20, height=20,
                           bg=BG, highlightthickness=0)
            cv.pack(side='left', padx=8)
            cv.create_oval(2,2,18,18, fill='#1A3A4A',
                           outline=TEAL, width=2, tags='d')
            self._dots.append(cv)

        self._msg = tk.Label(self, text='', font=FM,
                             fg='#E74C3C', bg=BG)
        self._msg.pack(pady=(0, 8))

        # Numpad
        pad = tk.Frame(self, bg=BG)
        pad.pack()
        for row_keys in [['1','2','3'],['4','5','6'],['7','8','9'],['⌫','0','✓']]:
            rf = tk.Frame(pad, bg=BG)
            rf.pack()
            for sym in row_keys:
                cv = tk.Canvas(rf, width=76, height=76,
                               bg=BG, highlightthickness=0, cursor='hand2')
                cv.pack(side='left', padx=4, pady=4)
                if sym == '⌫':
                    fill, outline, fg_col = '#1A1A2A', '#E74C3C', '#E74C3C'
                elif sym == '✓':
                    fill, outline, fg_col = '#0A2A1A', TEAL, TEAL
                else:
                    fill, outline, fg_col = '#0A1A2A', '#1A3A5A', '#FFFFFF'
                cv.create_oval(4,4,72,72, fill=fill,
                               outline=outline, width=2, tags='oval')
                cv.create_text(38,38, text=sym,
                               font=('Georgia',16,'bold'), fill=fg_col, tags='lbl')
                if sym == '⌫':
                    cv.bind('<Button-1>', lambda e: self._backspace())
                    cv.bind('<Enter>', lambda e,c=cv,o=fill: c.itemconfig('oval', fill='#2A0A0A'))
                    cv.bind('<Leave>', lambda e,c=cv,o=fill: c.itemconfig('oval', fill=o))
                elif sym == '✓':
                    cv.bind('<Button-1>', lambda e: self._submit())
                    cv.bind('<Enter>', lambda e,c=cv,o=fill: c.itemconfig('oval', fill='#0A3A2A'))
                    cv.bind('<Leave>', lambda e,c=cv,o=fill: c.itemconfig('oval', fill=o))
                else:
                    cv.bind('<Button-1>', lambda e,d=sym: self._press(d))
                    cv.bind('<Enter>', lambda e,c=cv,o=fill: c.itemconfig('oval', fill='#0A2A3A'))
                    cv.bind('<Leave>', lambda e,c=cv,o=fill: c.itemconfig('oval', fill=o))

        tk.Button(self, text='Cancel', font=FM,
                  bg=BG, fg='#4A6A7A', relief='flat',
                  cursor='hand2', command=self._cancel).pack(pady=(10,0))

    def _on_key(self, event):
        if event.char.isdigit(): self._press(event.char)
        elif event.keysym in ('BackSpace','Delete'): self._backspace()
        elif event.keysym == 'Return': self._submit()
        elif event.keysym == 'Escape': self._cancel()

    def _press(self, d):
        if len(self._pin) < 4:
            self._pin += d
            self._update_dots()
        if len(self._pin) == 4:
            self.after(120, self._submit)

    def _backspace(self):
        self._pin = self._pin[:-1]
        self._update_dots()

    def _update_dots(self):
        TEAL = '#00D4AA'
        for i, cv in enumerate(self._dots):
            cv.delete('d')
            if i < len(self._pin):
                cv.create_oval(2,2,18,18, fill=TEAL,
                               outline=TEAL, width=2, tags='d')
            else:
                cv.create_oval(2,2,18,18, fill='#1A3A4A',
                               outline=TEAL, width=2, tags='d')

    def _submit(self):
        pin = self._pin
        self._pin = ''
        self._update_dots()
        if _verify_chat_pin(self._contact, pin):
            self.destroy()
            self._on_unlock()
        else:
            self._attempts += 1
            if self._attempts >= 3:
                self._msg.config(text='Too many attempts!')
                self.after(2000, self._cancel)
            else:
                rem = 3 - self._attempts
                self._msg.config(
                    text=f'Wrong PIN. {rem} attempt(s) left.')

    def _cancel(self):
        self.destroy()
        self._on_cancel()


class ChatPinSetupDialog(tk.Toplevel):
    '''
    Set or remove a PIN for a specific chat.
    '''
    def __init__(self, root, contact: str, on_done):
        super().__init__(root)
        self.title(f'Lock Chat — {contact}')
        self.resizable(False, False)
        self.configure(bg=C['card'])
        self.attributes('-topmost', True)
        W, H = 380, 400
        sx = root.winfo_x() + (root.winfo_width()  - W) // 2
        sy = root.winfo_y() + (root.winfo_height() - H) // 2
        self.geometry(f'{W}x{H}+{sx}+{sy}')
        self._contact = contact
        self._on_done = on_done
        self._step    = 1
        self._first   = ''
        self._build()

    def _build(self):
        has = _chat_has_pin(self._contact)
        pad = tk.Frame(self, bg=C['card'], padx=30, pady=24)
        pad.pack(fill='both', expand=True)
        tk.Label(pad, text=f'🔒  LOCK CHAT',
                 font=FH2, fg=C['cyan'], bg=C['card']).pack(pady=(0,2))
        tk.Label(pad, text=self._contact,
                 font=FU_B, fg=C['dim'], bg=C['card']).pack(pady=(0,14))

        if has:
            tk.Label(pad,
                     text='🔒 This chat is currently LOCKED.',
                     font=FM_B, fg=C['success'], bg=C['card']).pack(pady=(0,16))
            GradientButton(pad, '🔓  Remove PIN / Unlock',
                           cmd=self._remove,
                           w=320, h=44,
                           c1=C['danger'], c2='#8B0000').pack(pady=(0,8))
            tk.Button(pad, text='Cancel', font=FM,
                      bg=C['elevated'], fg=C['dim'],
                      relief='flat', cursor='hand2',
                      command=self.destroy).pack()
            return

        tk.Label(pad, text='Set a 4-digit PIN for this chat:',
                 font=FM, fg=C['dim'], bg=C['card']).pack(pady=(0,10))

        self._step_lbl = tk.Label(pad, text='Enter PIN:',
                                  font=FM_B, fg=C['text'], bg=C['card'])
        self._step_lbl.pack(anchor='w')

        self._var = tk.StringVar()
        self._var.trace_add('write', self._on_change)
        e = tk.Entry(pad, textvariable=self._var,
                     show='●', width=8, justify='center',
                     font=('Consolas',24,'bold'),
                     bg=C['input_bg'], fg=C['cyan'],
                     insertbackground=C['cyan'],
                     relief='flat', bd=8)
        e.pack(pady=(4,4))
        e.focus_set()
        e.bind('<Return>', lambda ev: self._next())

        # dots
        df = tk.Frame(pad, bg=C['card'])
        df.pack(pady=(2,10))
        self._sdots = []
        for i in range(4):
            cv = tk.Canvas(df, width=16, height=16,
                           bg=C['card'], highlightthickness=0)
            cv.pack(side='left', padx=6)
            cv.create_oval(2,2,14,14, fill=C['ghost'],
                           outline='', tags='d')
            self._sdots.append(cv)

        self._msg = tk.Label(pad, text='', font=FM,
                             fg=C['danger'], bg=C['card'])
        self._msg.pack(pady=(0,8))

        GradientButton(pad, 'Next →',
                       cmd=self._next, w=320, h=44).pack(pady=(0,8))
        tk.Button(pad, text='Cancel', font=FM,
                  bg=C['elevated'], fg=C['dim'],
                  relief='flat', cursor='hand2',
                  command=self.destroy).pack()

    def _on_change(self, *args):
        val = self._var.get()
        clean = ''.join(c for c in val if c.isdigit())[:4]
        if clean != val: self._var.set(clean)
        for i, cv in enumerate(self._sdots):
            cv.delete('d')
            color = C['success'] if i < len(clean) else C['ghost']
            cv.create_oval(2,2,14,14, fill=color, outline='', tags='d')

    def _next(self):
        pin = self._var.get()
        if len(pin) != 4:
            self._msg.config(text='⚠ PIN must be 4 digits.')
            return
        if self._step == 1:
            self._first = pin
            self._var.set('')
            self._step = 2
            self._step_lbl.config(text='Confirm PIN:')
            self._msg.config(text='')
        else:
            if pin == self._first:
                _set_chat_pin(self._contact, pin)
                self._on_done(True)
                self.destroy()
            else:
                self._msg.config(text='✗ PINs do not match.')
                self._var.set('')
                self._step = 1
                self._first = ''
                self._step_lbl.config(text='Enter PIN:')

    def _remove(self):
        _remove_chat_pin(self._contact)
        self._on_done(False)
        self.destroy()


class LoginScreen(tk.Frame):
    def __init__(self, parent, client: ChatClient, on_success, on_register):
        super().__init__(parent, bg=C["bg"])
        self._client      = client
        self._on_success  = on_success
        self._on_register = on_register
        self._particles   = []
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self._bg_cv = tk.Canvas(self, bg=C["bg"], highlightthickness=0)
        self._bg_cv.place(relx=0, rely=0, relwidth=1, relheight=1)
        for _ in range(50):
            self._particles.append({
                "x": _secrets.randbelow(1000) / 1000, "y": _secrets.randbelow(1000) / 1000,
                "vx": (_secrets.randbelow(1000) / 1000 - .5) * .0012,
                "vy": (_secrets.randbelow(1000) / 1000 - .5) * .0012,
                "r": _secrets.randbelow(3) + 1,
                "col": [C["cyan"], C["purple"], C["ghost"]][_secrets.randbelow(3)],
            })
        self._animate_bg()

        card = tk.Frame(self, bg=C["card"], padx=50, pady=44)
        card.grid(row=0, column=0)

        logo_cv = tk.Canvas(card, width=440, height=80,
                            bg=C["card"], highlightthickness=0)
        logo_cv.pack(pady=(0, 6))
        _grad_h(logo_cv, 0, 0, 440, 80, C["bg"], C["surface"])
        for r, col in [(34, "#0A2040"), (26, C["surface"]),
                       (18, "#005566"), (12, C["cyan"])]:
            logo_cv.create_oval(220 - r, 40 - r, 220 + r, 40 + r,
                                outline=col, width=2, fill="")
        logo_cv.create_text(220, 40, text="🔐", font=("Segoe UI Emoji", 18))
        logo_cv.create_text(220, 62, text="SECURECHAT",
                            font=("Consolas", 18, "bold"), fill=C["cyan"])

        tk.Label(card, text="[ encrypted  ·  private  ·  secure ]",
                 font=FM, fg=C["purple"], bg=C["card"]).pack()

        self._sl_cv = tk.Canvas(card, width=440, height=3,
                                bg=C["card"], highlightthickness=0)
        self._sl_cv.pack(fill="x", pady=12)
        self._sl_x = 0
        self._animate_sl()

        self._user = CyberEntry(card, "USERNAME", "your@username",
                                width=26, bg=C["card"])
        self._user.pack(fill="x", pady=(0, 12))
        self._pwd  = CyberEntry(card, "PASSWORD", "••••••••",
                                secret=True, width=26, bg=C["card"])
        self._pwd.pack(fill="x", pady=(0, 8))

        self._msg = tk.Label(card, text="", font=FM,
                             bg=C["card"], fg=C["danger"])
        self._msg.pack(pady=(4, 12))

        GradientButton(card, "⟶   AUTHENTICATE",
                       cmd=self._do_login, w=440, h=48).pack(pady=(0, 10))
        GradientButton(card, "+   CREATE ACCOUNT",
                       cmd=self._on_register, w=440, h=40,
                       c1=C["elevated"], c2=C["card"],
                       fg=C["cyan"]).pack()

        tk.Label(card,
                 text="AES-256 · RSA-2048 E2E · Argon2id · DH forward secrecy",
                 font=FM, fg=C["ghost"], bg=C["card"]).pack(pady=(20, 0))

    def _animate_bg(self):
        if not self.winfo_exists():
            return
        w = self.winfo_width() or 1200
        h = self.winfo_height() or 720
        self._bg_cv.delete("all")
        self._bg_cv.create_rectangle(0, 0, w, h, fill=C["bg"], outline="")
        for p in self._particles:
            p["x"] = (p["x"] + p["vx"]) % 1.0
            p["y"] = (p["y"] + p["vy"]) % 1.0
            cx, cy = int(p["x"] * w), int(p["y"] * h)
            r = p["r"]
            self._bg_cv.create_oval(cx - r, cy - r, cx + r, cy + r,
                                    fill=p["col"], outline="")
        for gx in range(0, w, 80):
            self._bg_cv.create_line(gx, 0, gx, h, fill=C["surface"], width=1)
        for gy in range(0, h, 80):
            self._bg_cv.create_line(0, gy, w, gy, fill=C["surface"], width=1)
        self.after(40, self._animate_bg)

    def _animate_sl(self):
        if not self.winfo_exists():
            return
        self._sl_cv.delete("all")
        for i, col in enumerate(["#003344", "#006688", C["cyan"], "#006688", "#003344"]):
            self._sl_cv.create_line(self._sl_x + i - 2, 1,
                                    self._sl_x + i + 40 - 2, 1,
                                    fill=col, width=2)
        self._sl_x = (self._sl_x + 10) % 490
        self.after(24, self._animate_sl)

    def _do_login(self):
        u = self._user.get().strip()
        p = self._pwd.get().strip()
        if not u or not p:
            self._msg.config(text="⚠  Fill in both fields.", fg=C["warning"])
            return
        self._msg.config(text="◌  Connecting…", fg=C["cyan"])
        self.after(80, lambda: self._connect(u, p))

    def _connect(self, u, p):
        ok, reason = self._client.connect()
        if not ok:
            self._msg.config(text=f"✗  {reason}", fg=C["danger"])
            return
        self._msg.config(text="◌  Authenticating…", fg=C["cyan"])
        self.after(80, lambda: self._auth(u, p))

    def _auth(self, u, p):
        ok, reason = self._client.login(u, p)
        if ok:
            self._on_success(u)
        else:
            self._client.disconnect()
            self._msg.config(text=f"✗  {reason}", fg=C["danger"])


class RegisterScreen(tk.Frame):
    def __init__(self, parent, client: ChatClient, on_success, on_back):
        super().__init__(parent, bg=C["bg"])
        self._client     = client
        self._on_success = on_success
        self._on_back    = on_back
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        card = tk.Frame(self, bg=C["card"], padx=50, pady=40)
        card.grid(row=0, column=0)
        tk.Label(card, text="◈  NEW IDENTITY", font=FH2,
                 fg=C["cyan"], bg=C["card"]).pack(pady=(0, 4))
        tk.Label(card, text="[ establish secure credentials ]",
                 font=FM, fg=C["purple"], bg=C["card"]).pack()
        tk.Frame(card, bg=C["border"], height=1).pack(fill="x", pady=14)

        self._u  = CyberEntry(card, "USERNAME", "Choose a callsign",
                              width=26, bg=C["card"])
        self._u.pack(fill="x", pady=(0, 12))
        self._p  = CyberEntry(card, "PASSWORD", "Min 6 characters",
                              secret=True, width=26, bg=C["card"])
        self._p.pack(fill="x", pady=(0, 12))
        self._p2 = CyberEntry(card, "CONFIRM PASSWORD", "Repeat password",
                              secret=True, width=26, bg=C["card"])
        self._p2.pack(fill="x", pady=(0, 10))

        row = tk.Frame(card, bg=C["card"])
        row.pack(fill="x", pady=(0, 6))
        tk.Label(row, text="STRENGTH ", font=FM_B,
                 fg=C["dim"], bg=C["card"]).pack(side="left")
        self._segs = []
        for _ in range(5):
            s = tk.Frame(row, width=60, height=6, bg=C["ghost"])
            s.pack(side="left", padx=2)
            self._segs.append(s)
        self._str_lbl = tk.Label(row, text="", font=FM,
                                 fg=C["dim"], bg=C["card"])
        self._str_lbl.pack(side="left", padx=(8, 0))

        self._msg = tk.Label(card, text="", font=FM,
                             bg=C["card"], fg=C["danger"])
        self._msg.pack(pady=(4, 12))

        GradientButton(card, "+   REGISTER",
                       cmd=self._do_register, w=440, h=48).pack(pady=(0, 8))
        GradientButton(card, "←   BACK TO LOGIN",
                       cmd=self._on_back, w=440, h=40,
                       c1=C["elevated"], c2=C["card"],
                       fg=C["dim"]).pack()
        self._p._e.bind("<KeyRelease>", self._check_strength)

    def _check_strength(self, e):
        p     = self._p._e.get()
        score = sum([
            len(p) >= 6,
            any(c.isupper() for c in p),
            any(c.isdigit() for c in p),
            any(c in "!@#$%^&*()" for c in p),
            len(p) >= 14,
        ])
        pal   = [C["danger"], "#FF7043", C["warning"], "#9CCC65", C["success"]]
        names = ["Weak", "Fair", "Moderate", "Strong", "Excellent"]
        for i, s in enumerate(self._segs):
            s.config(bg=pal[min(score - 1, 4)] if i < score else C["ghost"])
        if score:
            self._str_lbl.config(text=names[min(score - 1, 4)],
                                 fg=pal[min(score - 1, 4)])

    def _do_register(self):
        u  = self._u.get().strip()
        p  = self._p.get().strip()
        p2 = self._p2.get().strip()
        if not all([u, p, p2]):
            self._msg.config(text="⚠  All fields required.", fg=C["warning"])
            return
        if p != p2:
            self._msg.config(text="✗  Passwords don't match.", fg=C["danger"])
            return
        if len(p) < 6:
            self._msg.config(text="✗  Password too short.", fg=C["danger"])
            return
        self._msg.config(text="◌  Connecting…", fg=C["cyan"])
        self.after(80, lambda: self._connect(u, p))

    def _connect(self, u, p):
        ok, reason = self._client.connect()
        if not ok:
            self._msg.config(text=f"✗  {reason}", fg=C["danger"])
            return
        self._msg.config(text="◌  Creating identity…", fg=C["cyan"])
        self.after(80, lambda: self._finish(u, p))

    def _finish(self, u, p):
        ok, reason = self._client.register(u, p)
        if ok:
            self._msg.config(text=f"✓  {reason}", fg=C["success"])
            self.after(800, lambda: self._on_success(u))
        else:
            self._client.disconnect()
            self._msg.config(text=f"✗  {reason}", fg=C["danger"])


# ══════════════════════════════════════════════════════════════════
#  SIDEBAR
# ══════════════════════════════════════════════════════════════════

class Sidebar(tk.Frame):
    def __init__(self, parent, username, on_select, on_logout,
                 on_dark_toggle, on_profile, on_sessions, on_2fa=None, on_lock_chat=None):
        super().__init__(parent, bg=C["sidebar"], width=272)
        self.pack_propagate(False)
        self._me             = username
        self._on_select      = on_select
        self._on_logout      = on_logout
        self._on_dark_toggle = on_dark_toggle
        self._on_profile     = on_profile
        self._on_sessions    = on_sessions
        self._on_2fa         = on_2fa or (lambda: None)
        self._on_lock_cb     = on_lock_chat
        self._active         = None
        self._rows:   dict   = {}
        self._badges: dict   = {}
        self._all_users: list = []
        self._pinned:    set  = set()
        self._profiles:  dict = {}
        self._build()

    def _build(self):
        hdr_cv = tk.Canvas(self, height=72, bg=C["sid_head"], highlightthickness=0)
        hdr_cv.pack(fill="x")
        hdr_cv.bind("<Configure>",
                    lambda e: _grad_h(hdr_cv, 0, 0, e.width, 72,
                                      C["sid_head"], C["sidebar"]))

        hdr = tk.Frame(hdr_cv, bg=C["sid_head"])
        hdr_cv.create_window(4, 4, window=hdr, anchor="nw")

        self._av_cv = _make_avatar_canvas(hdr, self._me, size=46, bg=C["sid_head"])
        self._av_cv.pack(side="left", padx=(6, 10), pady=13)
        self._av_cv.bind("<Button-1>", lambda e: self._on_profile())
        self._av_cv.config(cursor="hand2")

        meta = tk.Frame(hdr, bg=C["sid_head"])
        meta.pack(side="left")
        self._name_lbl = tk.Label(meta, text=self._me, font=FU_B,
                                  fg=C["text"], bg=C["sid_head"])
        self._name_lbl.pack(anchor="w")
        self._status_lbl = tk.Label(meta, text="🟢  Online", font=FM,
                                    fg=C["success"], bg=C["sid_head"])
        self._status_lbl.pack(anchor="w")

        btns = tk.Frame(hdr_cv, bg=C["sid_head"])
        hdr_cv.create_window(268, 36, window=btns, anchor="e")
        for sym, cmd in [("🌙", self._on_dark_toggle),
                         ("🔐", self._on_2fa),
                         ("⚙", self._on_sessions),
                         ("⏻", self._on_logout)]:
            lbl = tk.Label(btns, text=sym,
                           font=("Segoe UI Emoji", 12),
                           fg=C["danger"] if sym == "⏻" else C["dim"],
                           bg=C["sid_head"], cursor="hand2")
            lbl.pack(side="left", padx=2)
            lbl.bind("<Button-1>", lambda e, c=cmd: c())

        sf = tk.Frame(self, bg=C["sidebar"], padx=10, pady=6)
        sf.pack(fill="x")
        sw = tk.Frame(sf, bg=C["elevated"])
        sw.pack(fill="x")
        tk.Label(sw, text="🔍", font=FU_S,
                 bg=C["elevated"], fg=C["dim"]).pack(side="left", padx=(8, 4))
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", self._on_search)
        tk.Entry(sw, textvariable=self._search_var, font=FU_S,
                 bg=C["elevated"], fg=C["text"],
                 insertbackground=C["text"],
                 relief="flat", bd=0).pack(side="left", fill="x", expand=True, pady=8)

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")
        self._add_special_row("__GROUP__", "👥", "Group Chat", "All online · E2E",
                               C["group_bdr"])
        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")
        self._add_special_row("__BROADCAST__", "📢", "Broadcast", "Send to all · plain",
                               C["purple"], card=True)
        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        tk.Label(self, text="  DIRECT MESSAGES", font=FM_B,
                 fg=C["ghost"], bg=C["sidebar"]).pack(anchor="w", pady=(8, 4))
        self._clist = tk.Frame(self, bg=C["sidebar"])
        self._clist.pack(fill="both", expand=True)
        tk.Label(self, text="🔒 RSA-2048 · AES-256 · DH-FS",
                 font=FM, fg=C["ghost"], bg=C["sidebar"]).pack(pady=6)

    def _add_special_row(self, key, icon, title, subtitle, color, card=False):
        row_bg = C["card"] if card else C["elevated"]
        gc     = tk.Frame(self, bg=row_bg, cursor="hand2")
        gc.pack(fill="x")
        gc_inner = tk.Frame(gc, bg=row_bg, padx=12, pady=10)
        gc_inner.pack(fill="x")
        gc_av = tk.Canvas(gc_inner, width=38, height=38,
                          bg=row_bg, highlightthickness=0)
        gc_av.pack(side="left", padx=(0, 10))
        gc_av.create_oval(2, 2, 36, 36, fill=color, outline="")
        gc_av.create_text(19, 19, text=icon, font=("Segoe UI Emoji", 12))
        gc_r = tk.Frame(gc_inner, bg=row_bg)
        gc_r.pack(side="left", fill="x", expand=True)
        tk.Label(gc_r, text=title, font=FU_B, fg=C["text"],
                 bg=row_bg).pack(anchor="w")
        tk.Label(gc_r, text=subtitle, font=FU_S,
                 fg=C["success"], bg=row_bg).pack(anchor="w")
        badge = UnreadBadge(gc_inner)
        badge.pack(side="right")
        self._badges[key] = badge
        for w in [gc, gc_inner, gc_r]:
            try:
                w.bind("<Button-1>", lambda e, k=key: self._select(k))
            except Exception:
                pass
        self._rows[key] = gc_inner

    def update_own_profile(self, profile: dict):
        dn    = profile.get("display_name", "") or self._me
        emoji = profile.get("status_emoji", "🟢")
        stxt  = profile.get("status_text", "Online")
        self._name_lbl.config(text=dn)
        self._status_lbl.config(text=f"{emoji}  {stxt}")
        av_b64 = profile.get("avatar", "")
        self._profiles[self._me] = profile
        self._av_cv.delete("all")

        # Handle PRESET marker
        if av_b64 and av_b64.startswith("PRESET:"):
            try:
                import json as _jj
                data   = _jj.loads(base64.b64decode(av_b64[7:]).decode())
                color  = data.get("color", _avatar_color(self._me))
                emj    = data.get("emoji", self._me[0].upper())
                self._av_cv.create_oval(2, 2, 44, 44,
                                        fill=color, outline=C["cyan"], width=2)
                self._av_cv.create_text(23, 24, text=emj,
                                        font=("Segoe UI Emoji", 20))
            except Exception:
                self._av_cv.create_oval(2, 2, 44, 44,
                                        fill=_avatar_color(self._me),
                                        outline=C["cyan"], width=2)
                self._av_cv.create_text(23, 23, text=self._me[0].upper(),
                                        fill="#FFF", font=FH3)
            return

        # Handle real uploaded image
        if av_b64 and _PIL:
            try:
                from io import BytesIO
                raw   = base64.b64decode(av_b64)
                img   = Image.open(BytesIO(raw)).resize((46, 46))
                photo = ImageTk.PhotoImage(img)
                self._av_cv._photo = photo
                self._av_cv.create_image(0, 0, anchor="nw", image=photo)
                return
            except Exception:
                pass

        # Fallback letter avatar
        self._av_cv.create_oval(2, 2, 44, 44,
                                fill=_avatar_color(self._me),
                                outline=C["cyan"], width=2)
        self._av_cv.create_text(23, 23, text=self._me[0].upper(),
                                fill="#FFF", font=FH3)

    def update_profiles(self, profiles: dict):
        self._profiles.update(profiles)
        # Refresh current contact display if their profile was updated
        if self._contact and self._contact in profiles:
            self.load_contact(self._contact)
        self._render_list(self._all_users)

    def update_users(self, users: list):
        from_server = [u for u in users if u != self._me]
        extras      = [u for u in self._pinned if u not in from_server]
        self._all_users = from_server + extras
        self._render_list(self._all_users)

    def ensure_contact(self, name: str):
        self._pinned.add(name)
        if name not in self._all_users:
            self._all_users.append(name)
            self._render_list(self._all_users)

    def _on_search(self, *args):
        q = self._search_var.get().lower().strip()
        filtered = ([u for u in self._all_users if q in u.lower()]
                    if q else self._all_users)
        self._render_list(filtered)

    def _render_list(self, users):
        saved = {n: b.count for n, b in self._badges.items()}
        for w in self._clist.winfo_children():
            w.destroy()
        for name in list(self._rows.keys()):
            if name not in ("__GROUP__", "__BROADCAST__"):
                del self._rows[name]
        for name in list(self._badges.keys()):
            if name not in ("__GROUP__", "__BROADCAST__"):
                del self._badges[name]
        if not users:
            tk.Label(self._clist, text="No other users online",
                     font=FM, fg=C["ghost"], bg=C["sidebar"]).pack(pady=24)
            return
        for name in users:
            self._make_row(name, saved.get(name, 0))

    def _make_row(self, name, unread=0):
        is_active = (name == self._active)
        row_bg    = C["sid_active"] if is_active else C["sidebar"]
        profile   = self._profiles.get(name, {})
        av_b64    = profile.get("avatar", "")
        dn        = profile.get("display_name", "") or name
        status_e  = profile.get("status_emoji", "🟢")
        status_t  = profile.get("status_text", "Online")

        row = tk.Frame(self._clist, bg=row_bg, cursor="hand2")
        row.pack(fill="x")
        inner = tk.Frame(row, bg=row_bg, padx=10, pady=8)
        inner.pack(fill="x")
        inner.bind("<Button-1>", lambda e: self._select(name))

        av = _make_avatar_canvas(inner, name, size=38,
                                 avatar_b64=av_b64, bg=row_bg)
        av.pack(side="left", padx=(0, 10))
        av.bind("<Button-1>", lambda e: self._select(name))

        right = tk.Frame(inner, bg=row_bg)
        right.pack(side="left", fill="x", expand=True)
        right.bind("<Button-1>", lambda e: self._select(name))
        tk.Label(right, text=dn, font=FU_B,
                 fg=C["text"], bg=row_bg).pack(anchor="w")
        tk.Label(right, text=f"{status_e} {status_t}", font=FU_S,
                 fg=C["success"], bg=row_bg).pack(anchor="w")

        badge = UnreadBadge(inner)
        badge.pack(side="right")
        badge.set(unread)
        self._badges[name] = badge

        def _hon(event, n=name):
            if n != self._active:
                self._set_row_bg(inner, C["sid_hover"])

        def _hoff(event, n=name):
            bg = C["sid_active"] if n == self._active else C["sidebar"]
            self._set_row_bg(inner, bg)

        inner.bind("<Enter>", _hon)
        inner.bind("<Leave>", _hoff)
        self._rows[name] = inner

        # Right-click menu for lock/unlock chat
        menu = tk.Menu(inner, tearoff=0, bg=C["card"],
                       fg=C["text"], activebackground=C["cyan"],
                       activeforeground="#FFF")
        if _chat_has_pin(name):
            menu.add_command(
                label="🔓  Remove Chat Lock",
                command=lambda n=name: self._on_lock_chat(n),
            )
        else:
            menu.add_command(
                label="🔒  Lock this Chat",
                command=lambda n=name: self._on_lock_chat(n),
            )
        for w in [inner, av, right]:
            try:
                w.bind("<Button-3>", lambda e, m=menu: m.tk_popup(e.x_root, e.y_root))
            except Exception:
                pass

    @staticmethod
    def _set_row_bg(frame, bg):
        try:
            frame.config(bg=bg)
        except Exception:
            pass
        for c in frame.winfo_children():
            try:
                c.config(bg=bg)
            except Exception:
                pass

    def _select(self, name):
        badge = self._badges.get(name)
        if badge:
            badge.reset()
        if self._active and self._active in self._rows:
            old_bg = (C["elevated"] if self._active in ("__GROUP__", "__BROADCAST__")
                      else C["sidebar"])
            self._set_row_bg(self._rows[self._active], old_bg)
        self._active = name
        if name in self._rows:
            self._set_row_bg(self._rows[name], C["sid_active"])
        self._on_select(name)

    def _on_lock_chat(self, name: str):
        if hasattr(self, '_on_lock_cb') and self._on_lock_cb:
            self._on_lock_cb(name)

    def notify_unread(self, contact: str):
        badge = self._badges.get(contact)
        if badge:
            badge.increment()


# ══════════════════════════════════════════════════════════════════
#  CHAT PANE
# ══════════════════════════════════════════════════════════════════

class ChatPane(tk.Frame):
    def __init__(self, parent, username, client: ChatClient):
        super().__init__(parent, bg=C["bg"])
        self._me       = username
        self._client   = client
        self._contact  = None
        self._history: dict  = {}
        self._bubbles: dict  = {}
        self._profiles: dict = {}
        self._reply_to = None
        self._showing_placeholder = False
        self._typing_after = None
        self._search_open  = False
        self._profile_target = None
        self._last_date: dict = {}
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self.topbar_cv = tk.Canvas(self, height=64, bg=C["topbar"],
                                   highlightthickness=0)
        self.topbar_cv.grid(row=0, column=0, sticky="ew")

        self._contact_lbl = tk.Label(self.topbar_cv, text="← Select a contact",
                                     font=FH3, fg=C["text"], bg=C["topbar"])
        self._status_lbl  = tk.Label(self.topbar_cv, text="",
                                     font=FU_S, fg=C["dim"], bg=C["topbar"])
        self._badge_e2e   = tk.Label(self.topbar_cv, text="E2E",
                                     font=FM_B, bg=C["surface"], fg=C["cyan"])
        self._badge_enc   = tk.Label(self.topbar_cv, text="AES-256",
                                     font=FM_B, bg=C["surface"], fg=C["purple"])
        self._export_btn  = tk.Label(self.topbar_cv, text="💾",
                                     font=("Segoe UI Emoji", 13),
                                     fg=C["dim"], bg=C["topbar"], cursor="hand2")
        self._export_btn.bind("<Button-1>", lambda e: self._export_chat())
        self._search_btn  = tk.Label(self.topbar_cv, text="🔍",
                                     font=("Segoe UI Emoji", 13),
                                     fg=C["dim"], bg=C["topbar"], cursor="hand2")
        self._search_btn.bind("<Button-1>", lambda e: self._toggle_search())


        # NEW: Voice call button in topbar
        self._call_btn = tk.Label(self.topbar_cv, text="📞",
                                  font=("Segoe UI Emoji", 13),
                                  fg=C["success"], bg=C["topbar"], cursor="hand2")
        self._call_btn.bind("<Button-1>", lambda e: self.event_generate("<<StartCall>>"))

        def _draw_topbar(e=None):
            w = self.topbar_cv.winfo_width() or 900
            self.topbar_cv.delete("all")
            _grad_h(self.topbar_cv, 0, 0, w, 64, C["topbar"], C["surface"])
            self.topbar_cv.create_window(18, 16, window=self._contact_lbl, anchor="nw")
            self.topbar_cv.create_window(18, 42, window=self._status_lbl,  anchor="nw")
            self.topbar_cv.create_window(w - 10,  20, window=self._badge_e2e,  anchor="e")
            self.topbar_cv.create_window(w - 10,  44, window=self._badge_enc,  anchor="e")
            self.topbar_cv.create_window(w - 100, 32, window=self._export_btn, anchor="e")
            self.topbar_cv.create_window(w - 140, 32, window=self._search_btn, anchor="e")
            # call button
            self.topbar_cv.create_window(w - 180, 32, window=self._call_btn,   anchor="e")


        self.topbar_cv.bind("<Configure>", _draw_topbar)
        self.bind_all("<Control-f>", lambda e: self._toggle_search())

        self._search_bar = tk.Frame(self, bg=C["surface"], padx=12, pady=6)
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", self._do_search)
        tk.Label(self._search_bar, text="🔍 Search:", font=FM_B,
                 fg=C["dim"], bg=C["surface"]).pack(side="left")
        tk.Entry(self._search_bar, textvariable=self._search_var,
                 font=FU_S, bg=C["input_bg"], fg=C["text"],
                 relief="flat", bd=4, width=30).pack(side="left", padx=6)
        self._search_result_lbl = tk.Label(self._search_bar, text="",
                                           font=FM, fg=C["dim"], bg=C["surface"])
        self._search_result_lbl.pack(side="left")
        tk.Button(self._search_bar, text="✕", font=FM_B,
                  bg=C["surface"], fg=C["danger"], relief="flat",
                  cursor="hand2", command=self._close_search).pack(side="right")

        self._scroll = ScrollChat(self)
        self._scroll.grid(row=1, column=0, sticky="nsew")
        self._feed = self._scroll.inner

        self._reply_strip = tk.Frame(self, bg=C["elevated"], padx=12, pady=6)
        self._reply_lbl   = tk.Label(self._reply_strip, text="",
                                     font=FM, fg=C["dim"], bg=C["elevated"])
        self._reply_lbl.pack(side="left", fill="x", expand=True)
        tk.Button(self._reply_strip, text="✕", font=FM,
                  bg=C["elevated"], fg=C["danger"], relief="flat",
                  cursor="hand2", command=self._cancel_reply).pack(side="right")

        bar = tk.Frame(self, bg=C["surface"], padx=14, pady=10)
        bar.grid(row=3, column=0, sticky="ew")
        bar.columnconfigure(0, weight=1)

        ttl_frame = tk.Frame(bar, bg=C["surface"])
        ttl_frame.grid(row=0, column=2, padx=(8, 0))
        tk.Label(ttl_frame, text="🔥", font=FM,
                 bg=C["surface"], fg=C["dim"]).pack(side="left")
        self._ttl_var = tk.StringVar(value="Never")
        ttl_options = ["Never", "10 sec", "30 sec", "1 min",
                       "5 min", "1 hour", "24 hours", "7 days"]
        ttk.OptionMenu(ttl_frame, self._ttl_var, "Never", *ttl_options).pack(side="left")

        attach_btn = tk.Label(bar, text="📎", font=("Segoe UI Emoji", 14),
                              fg=C["dim"], bg=C["surface"], cursor="hand2")
        attach_btn.grid(row=0, column=3, padx=(6, 0))
        attach_btn.bind("<Button-1>", lambda e: self._attach_file())

        self._entry = tk.Text(bar, height=2, font=FU,
                              bg=C["input_bg"], fg=C["text"],
                              insertbackground=C["cyan"],
                              relief="flat", wrap="word")
        self._entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._entry.bind("<Return>",     self._on_return)
        self._entry.bind("<KeyRelease>", self._on_keyrelease)

        tk.Button(bar, text="➤", font=FH3,
                  bg=C["cyan"], fg="white", relief="flat",
                  cursor="hand2", command=self._send).grid(row=0, column=1)

        self._show_empty("Select a contact from the sidebar to start chatting")

    # ── Search ────────────────────────────────────────────────────

    def _toggle_search(self):
        self._search_open = not self._search_open
        if self._search_open:
            self._search_bar.grid(row=2, column=0, sticky="ew")
        else:
            self._close_search()

    def _close_search(self):
        self._search_open = False
        self._search_bar.grid_forget()
        self._search_var.set("")
        self._search_result_lbl.config(text="")

    def _do_search(self, *args):
        q = self._search_var.get().strip().lower()
        if not q or not self._contact:
            self._search_result_lbl.config(text="")
            return
        history = self._history.get(self._contact, [])
        matches = [e for e in history if q in e.get("text", "").lower()]
        self._search_result_lbl.config(text=f"{len(matches)} result(s)")
        if matches:
            mid = matches[-1].get("msg_id")
            bub = self._bubbles.get(mid)
            if bub:
                bub.update_idletasks()
                try:
                    self._scroll.canvas.yview_moveto(
                        bub.winfo_y() / max(self._feed.winfo_height(), 1)
                    )
                except Exception:
                    pass

    # ── Reply ─────────────────────────────────────────────────────

    def _set_reply(self, msg_id, text, sender):
        self._reply_to = (msg_id, text, sender)
        self._reply_strip.grid(row=2, column=0, sticky="ew")
        preview = text[:60] + ("…" if len(text) > 60 else "")
        self._reply_lbl.config(text=f"↩ Replying to {sender}: {preview}")
        self._entry.focus_set()

    def _cancel_reply(self):
        self._reply_to = None
        self._reply_strip.grid_forget()

    # ── Attach file ───────────────────────────────────────────────

    def _attach_file(self):
        path = filedialog.askopenfilename(
            title="Attach File",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif"),
                       ("All files", "*.*")],
        )
        if not path:
            return
        file_dict = encode_file(path)
        if not file_dict:
            messagebox.showwarning("Too large", "File must be under 512 KB.")
            return
        if not self._contact:
            messagebox.showinfo("Info", "Select a contact first.")
            return
        stamp       = time.strftime("%H:%M")
        ttl         = self._get_ttl()
        reply_to_id = self._reply_to[0] if self._reply_to else None

        if self._contact == "__GROUP__":
            self._client.send_group_message("", file_data=file_dict, ttl=ttl,
                                            reply_to_id=reply_to_id)
        elif self._contact != "__BROADCAST__":
            self._client.send_message(self._contact, "", file_data=file_dict,
                                      ttl=ttl, reply_to_id=reply_to_id)

        self._add_entry(self._contact, {
            "text": "", "sender": self._me, "stamp": stamp,
            "timestamp": time.time(),
            "is_me": True, "is_group": self._contact == "__GROUP__",
            "file_data": file_dict,
        })
        self._cancel_reply()

    def _get_ttl(self):
        ttl_map = {
            "Never":    None,
            "10 sec":   10,
            "30 sec":   30,
            "1 min":    60,
            "5 min":    300,
            "1 hour":   3600,
            "24 hours": 86400,
            "7 days":   604800,
        }
        return ttl_map.get(self._ttl_var.get())

    # ── Typing ────────────────────────────────────────────────────

    def _on_keyrelease(self, event):
        if (self._contact and
                self._contact not in ("__GROUP__", "__BROADCAST__") and
                event.keysym not in ("Return", "Escape")):
            try:
                self._client.send_typing(self._contact)
            except Exception:
                pass

    def show_typing(self, sender: str):
        if self._contact not in (sender, "__GROUP__"):
            return
        if "typing" not in self._status_lbl.cget("text"):
            self._status_lbl.config(
                text=f"✏  {sender} is typing…", fg=C["warning"]
            )
        if self._typing_after:
            self.after_cancel(self._typing_after)
        self._typing_after = self.after(3000, self._clear_typing)

    def _clear_typing(self):
        self._typing_after = None
        if self._contact not in ("__GROUP__", "__BROADCAST__", "", None):
            self._status_lbl.config(text="🔒 end-to-end encrypted · online",
                                    fg=C["dim"])
        elif self._contact == "__GROUP__":
            self._status_lbl.config(text="end-to-end encrypted · group room",
                                    fg=C["dim"])

    # ── Export ────────────────────────────────────────────────────

    def _export_chat(self):
        if not self._contact or not self._history.get(self._contact):
            messagebox.showinfo("Export", "No conversation to export.")
            return
        name = self._contact.strip("_").lower()
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialfile=f"securechat_{name}_{time.strftime('%Y%m%d_%H%M%S')}.txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"SecureChat export — {self._contact}\n")
                f.write(f"Exported: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 60 + "\n\n")
                for e in self._history.get(self._contact, []):
                    f.write(f"[{e.get('stamp','?')}] {e.get('sender','?')}: "
                            f"{e.get('text','')}\n")
            messagebox.showinfo("Export", f"Saved to:\n{path}")
        except Exception as ex:
            messagebox.showerror("Error", str(ex))

    # ── Empty state ───────────────────────────────────────────────

    def _show_empty(self, text="No messages yet"):
        self._showing_placeholder = True
        for w in self._feed.winfo_children():
            w.destroy()
        tk.Label(self._feed, text=text, font=FU,
                 fg=C["ghost"], bg=C["bg"]).pack(expand=True, pady=80)

    # ── Input ─────────────────────────────────────────────────────

    def _on_return(self, event):
        if not (event.state & 0x1):
            self._send()
        return "break"

    # ── Load contact ──────────────────────────────────────────────

    def load_contact(self, name: str):
        self._contact = name
        self._cancel_reply()

        if name == "__GROUP__":
            self._contact_lbl.config(text="👥  Group Chat  —  All Users")
            self._status_lbl.config(text="end-to-end encrypted · group room",
                                    fg=C["dim"])
            self._badge_e2e.config(text="GROUP E2E", fg=C["success"])
            self._badge_enc.config(text="AES-256",   fg=C["success"])
        elif name == "__BROADCAST__":
            self._contact_lbl.config(text="📢  Broadcast  —  All Users")
            self._status_lbl.config(text="unencrypted broadcast", fg=C["dim"])
            self._badge_e2e.config(text="BROADCAST", fg=C["warning"])
            self._badge_enc.config(text="PLAIN",     fg=C["warning"])
        else:
            self._contact_lbl.config(text=f"  {name}")
            self._status_lbl.config(text="🔒 end-to-end encrypted · online",
                                    fg=C["dim"])
            self._badge_e2e.config(text="E2E",     fg=C["cyan"])
            self._badge_enc.config(text="AES-256", fg=C["purple"])

        for w in self._feed.winfo_children():
            w.destroy()
        self._bubbles = {}
        self._showing_placeholder = False
        self._last_date[name] = None

        history = self._history.get(name, [])
        if not history:
            self._show_empty("No messages yet — say hello!")
            return

        last_date = None
        for entry in history:
            ts       = entry.get("timestamp", 0)
            date_str = (time.strftime("%d %b %Y", time.localtime(ts))
                        if ts else None)
            if date_str and date_str != last_date:
                DateSeparator(self._feed, date_str).pack(fill="x")
                last_date = date_str
            self._render_bubble(entry)

        self._last_date[name] = last_date
        self._scroll.bottom()

    # ── Render bubble ─────────────────────────────────────────────

    def _render_bubble(self, entry: dict):
        sender    = entry.get("sender", "")
        text      = entry.get("text", "")
        stamp     = entry.get("stamp", "")
        is_me     = entry.get("is_me", False)
        is_group  = entry.get("is_group", False)
        from_hist = entry.get("from_history", False)
        msg_id    = entry.get("msg_id")
        reply_p   = entry.get("reply_preview")
        reactions = entry.get("reactions", {})
        file_d    = entry.get("file_data")
        og        = entry.get("og")
        deleted   = entry.get("deleted", False)
        edited    = entry.get("edited", False)
        av_b64    = self._profiles.get(sender, {}).get("avatar", "")

        if deleted:
            text = "🗑  This message was deleted."

        bub = Bubble(
            self._feed, text, sender, stamp, is_me,
            is_group=is_group, from_history=from_hist,
            msg_id=msg_id, reply_preview=reply_p,
            reactions=reactions, file_data=file_d, og=og,
            avatar_b64=av_b64,
            on_reply=self._set_reply   if msg_id else None,
            on_edit=self._do_edit      if is_me and msg_id is not None else None,
            on_delete=self._do_delete  if is_me and msg_id is not None else None,
            on_react=self._do_react    if msg_id else None,
            on_avatar_click=self._on_avatar_click,
        )
        bub.pack(fill="x")
        if edited:
            bub.mark_edited()
        if msg_id:
            self._bubbles[msg_id] = bub
        return bub

    def _on_avatar_click(self, username: str):
        self._profile_target = username
        self.event_generate("<<OpenProfile>>")

    # ── History ───────────────────────────────────────────────────

    def load_history(self, channel: str, messages: list):
        if channel not in self._history:
            self._history[channel] = []
        existing_ids = {e.get("msg_id") for e in self._history[channel]}
        for m in messages:
            sender   = m.get("sender", "")
            text     = m.get("message", "")
            ts       = m.get("timestamp", 0)
            stamp    = time.strftime("%H:%M", time.localtime(ts)) if ts else "?"
            is_me    = (sender == self._me)
            is_group = (channel == "__GROUP__")
            mid      = m.get("id")
            entry = {
                "sender": sender, "text": text, "stamp": stamp,
                "timestamp": ts, "is_me": is_me, "is_group": is_group,
                "from_history": True, "msg_id": mid,
                "reply_preview": m.get("reply_preview"),
                "reactions": m.get("reactions", {}),
                "edited": m.get("edited", False),
                "deleted": m.get("deleted", False),
            }
            if mid not in existing_ids:
                self._history[channel].append(entry)
                existing_ids.add(mid)
        if self._contact == channel:
            self.load_contact(channel)

    # ── Send ──────────────────────────────────────────────────────

    def _send(self):
        if not self._contact:
            return
        txt = self._entry.get("1.0", "end").strip()
        if not txt:
            return
        stamp         = time.strftime("%H:%M")
        ttl           = self._get_ttl()
        reply_to_id   = self._reply_to[0] if self._reply_to else None
        reply_preview = None
        if self._reply_to:
            _, rtext, rsender = self._reply_to
            reply_preview = {"sender": rsender, "text": rtext}

        entry = {
            "sender": self._me, "text": txt, "stamp": stamp,
            "timestamp": time.time(), "is_me": True,
            "is_group": self._contact == "__GROUP__",
            "from_history": False, "reply_preview": reply_preview,
            "reactions": {}, "msg_id": None,
        }

        if self._contact == "__GROUP__":
            self._client.send_group_message(txt, reply_to_id=reply_to_id, ttl=ttl)
        elif self._contact == "__BROADCAST__":
            self._client.send_broadcast(txt)
        else:
            self._client.send_message(self._contact, txt,
                                      reply_to_id=reply_to_id, ttl=ttl)

        self._add_entry(self._contact, entry)
        self._cancel_reply()
        self._entry.delete("1.0", "end")

    # ── Add entry ─────────────────────────────────────────────────

    def _add_entry(self, key, entry: dict):
        if key not in self._history:
            self._history[key] = []
        self._history[key].append(entry)

        if self._contact == key:
            if self._showing_placeholder:
                for w in self._feed.winfo_children():
                    w.destroy()
                self._showing_placeholder = False

            ts       = entry.get("timestamp", 0)
            date_str = (time.strftime("%d %b %Y", time.localtime(ts))
                        if ts else None)
            if date_str and date_str != self._last_date.get(key):
                DateSeparator(self._feed, date_str).pack(fill="x")
                self._last_date[key] = date_str

            self._render_bubble(entry)
            self._scroll.bottom()

    # ── Edit / delete / react ─────────────────────────────────────

    def _do_edit(self, msg_id, old_text):
        new_text = simpledialog.askstring("Edit Message", "Edit your message:",
                                          initialvalue=old_text)
        if new_text and new_text.strip() != old_text:
            self._client.send_edit(msg_id, new_text.strip())

    def _do_delete(self, msg_id):
        if messagebox.askyesno("Delete", "Delete this message for everyone?"):
            self._client.send_delete(msg_id)

    def _do_react(self, msg_id, emoji):
        self._client.send_reaction(msg_id, emoji)

    # ── Receive ───────────────────────────────────────────────────

    def receive_message(self, sender: str, text: str, extra: dict = None):
        extra = extra or {}
        stamp = time.strftime("%H:%M")
        entry = {
            "sender": sender, "text": text, "stamp": stamp,
            "timestamp": time.time(), "is_me": False, "is_group": False,
            "from_history": False, "msg_id": extra.get("msg_id"),
            "reply_preview": None, "reactions": {},
            "og": extra.get("og"), "file_data": extra.get("file_data"),
        }
        if extra.get("reply_to_id"):
            for ch_hist in self._history.values():
                for e in ch_hist:
                    if e.get("msg_id") == extra["reply_to_id"]:
                        entry["reply_preview"] = {
                            "sender": e["sender"], "text": e["text"],
                        }
                        break
        self._add_entry(sender, entry)

    def receive_broadcast(self, sender: str, text: str):
        stamp = time.strftime("%H:%M")
        self._add_entry("__BROADCAST__", {
            "sender": sender, "text": text, "stamp": stamp,
            "timestamp": time.time(), "is_me": False, "is_group": False,
            "from_history": False, "msg_id": None,
            "reply_preview": None, "reactions": {},
        })

    def receive_group_message(self, sender: str, text: str, extra: dict = None):
        extra = extra or {}
        stamp = time.strftime("%H:%M")
        self._add_entry("__GROUP__", {
            "sender": sender, "text": text, "stamp": stamp,
            "timestamp": time.time(), "is_me": False, "is_group": True,
            "from_history": False, "msg_id": extra.get("msg_id"),
            "reply_preview": None, "reactions": {},
            "file_data": extra.get("file_data"),
        })

    # ── Apply server events ───────────────────────────────────────

    def apply_edit(self, msg_id, new_text):
        for hist in self._history.values():
            for e in hist:
                if e.get("msg_id") == msg_id:
                    e["text"]   = new_text
                    e["edited"] = True
        bub = self._bubbles.get(msg_id)
        if bub:
            bub._msg_lbl.config(text=new_text)
            bub.mark_edited()

    def apply_delete(self, msg_id):
        for hist in self._history.values():
            for e in hist:
                if e.get("msg_id") == msg_id:
                    e["text"]    = ""
                    e["deleted"] = True
        bub = self._bubbles.get(msg_id)
        if bub:
            bub.mark_deleted()

    def apply_reaction(self, msg_id, counts: dict):
        for hist in self._history.values():
            for e in hist:
                if e.get("msg_id") == msg_id:
                    e["reactions"] = counts
        bub = self._bubbles.get(msg_id)
        if bub:
            bub.update_reactions(counts)

    def show_system(self, text: str):
        SystemBubble(self._feed, text).pack(fill="x")
        self._scroll.bottom()

    def update_profiles(self, profiles: dict):
        self._profiles.update(profiles)


# ══════════════════════════════════════════════════════════════════
#  APP
# ══════════════════════════════════════════════════════════════════

_DARK_MODE = False


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SecureChat  //  v6.5  🔐")
        self.geometry("1220x760")
        self.minsize(940, 600)
        self.configure(bg=C["bg"])
        self._client      = None
        self._chat        = None
        self._sidebar     = None
        self._profiles:  dict = {}
        self._sessions:  list = []
        # NEW: voice call state
        self._voice_call  = None   # VoiceCall instance when active
        self._totp_dialog = None   # TotpSetupDialog reference
        self._totp_enabled = False  # cached 2FA status
        self._pending_2fa_user = None  # username waiting for 2FA after login
        self._call_window = None   # CallWindow Toplevel
        self._call_peer      = None   # peer username during active call
        # Chat PIN state
        self._unlocked_chats: set = set()  # contacts unlocked this session
        self._show_login()

    def _clear(self):
        for w in self.winfo_children():
            w.destroy()
        self.update_idletasks()

    def _toggle_dark(self):
        global _DARK_MODE
        _DARK_MODE = not _DARK_MODE
        C.update(DARK if _DARK_MODE else LIGHT)
        if self._chat:
            username = self._chat._me
            saved_history  = dict(self._chat._history)
            saved_profiles = dict(self._chat._profiles)
            self.configure(bg=C["bg"])
            self._boot_chat(username, self._client,
                            saved_history, saved_profiles)

    def _new_client(self):
        return ChatClient(
            on_message        = lambda s, t, ex={}: self.after(
                0, lambda s=s, t=t, ex=ex: self._dispatch_message(s, t, ex)),
            on_broadcast      = lambda s, t: self.after(
                0, lambda s=s, t=t: self._dispatch_broadcast(s, t)),
            on_system         = lambda t: self.after(
                0, lambda t=t: self._dispatch_system(t)),
            on_online_list    = lambda u: self.after(
                0, lambda u=u: self._dispatch_online(u)),
            on_group_message  = lambda s, t, ex={}: self.after(
                0, lambda s=s, t=t, ex=ex: self._dispatch_group(s, t, ex)),
            on_typing         = lambda s: self.after(
                0, lambda s=s: self._dispatch_typing(s)),
            on_history        = lambda ch, m: self.after(
                0, lambda ch=ch, m=m: self._dispatch_history(ch, m)),
            on_profile_update = lambda u, p: self.after(
                0, lambda u=u, p=p: self._dispatch_profile(u, p)),
            on_own_profile    = lambda p: self.after(
                0, lambda p=p: self._dispatch_own_profile(p)),
            on_profile_bundle = lambda d: self.after(
                0, lambda d=d: self._dispatch_profile_bundle(d)),
            on_edit           = lambda i, t: self.after(
                0, lambda i=i, t=t: self._dispatch_edit(i, t)),
            on_delete         = lambda i: self.after(
                0, lambda i=i: self._dispatch_delete(i)),
            on_reaction       = lambda i, c: self.after(
                0, lambda i=i, c=c: self._dispatch_reaction(i, c)),
            on_session_list   = lambda s: self.after(
                0, lambda s=s: self._dispatch_sessions(s)),
            on_dh             = lambda m: self.after(
                0, lambda m=m: self._dispatch_dh(m)),
            on_self_destruct  = lambda mid, rem: self.after(
                0, lambda mid=mid, rem=rem: self._dispatch_self_destruct(mid, rem)),
            on_totp_setup     = lambda s, u: self.after(
                0, lambda s=s, u=u: self._dispatch_totp_setup(s, u)),
            on_totp_result    = lambda ok, msg, act: self.after(
                0, lambda ok=ok, msg=msg, act=act: self._dispatch_totp_result(ok, msg, act)),
            on_totp_status    = lambda e: self.after(
                0, lambda e=e: self._dispatch_totp_status(e)),
            # NEW: voice call callbacks
            on_call_offer     = lambda p: self.after(
                0, lambda p=p: self._on_call_offer(p)),
            on_call_answer    = lambda p, a: self.after(
                0, lambda p=p, a=a: self._on_call_answer(p, a)),
            on_call_end       = lambda p: self.after(
                0, lambda p=p: self._on_call_end(p)),
            on_call_audio     = lambda p, d: self.after(
                0, lambda p=p, d=d: self._on_call_audio(p, d)),
        )

    def _show_login(self):
        self._clear()
        if self._client:
            self._client.disconnect()
        self._client = self._new_client()
        LoginScreen(self, self._client,
                    on_success=self._boot_chat_new,
                    on_register=self._show_register).pack(fill="both", expand=True)

    def _show_register(self):
        self._clear()
        if self._client:
            self._client.disconnect()
        self._client = self._new_client()
        RegisterScreen(self, self._client,
                       on_success=self._boot_chat_new,
                       on_back=self._show_login).pack(fill="both", expand=True)

    def _boot_chat_new(self, username):
        self._boot_chat(username, self._client)

    def _boot_chat(self, username, client,
                   saved_history=None, saved_profiles=None):
        self._clear()
        self._client = client
        container = tk.Frame(self, bg=C["bg"])
        container.pack(fill="both", expand=True)

        self._chat = ChatPane(container, username, self._client)
        if saved_history:
            self._chat._history = saved_history
        if saved_profiles:
            self._chat._profiles = saved_profiles
        self._chat.bind("<<OpenProfile>>", self._open_profile_from_event)
        # NEW: wire call button event
        self._chat.bind("<<StartCall>>",      self._on_start_call_btn)

        self._sidebar = Sidebar(
            container, username,
            on_select      = self._on_chat_select,
            on_logout      = self._logout,
            on_dark_toggle = self._toggle_dark,
            on_profile     = self._open_own_profile_editor,
            on_sessions    = self._open_sessions_panel,
            on_2fa         = self._open_2fa_settings,
            on_lock_chat   = self._open_chat_lock_settings,
        )
        self._sidebar.pack(side="left", fill="y")
        tk.Frame(container, bg=C["border"], width=1).pack(side="left", fill="y")
        self._chat.pack(side="left", fill="both", expand=True)

    def _logout(self):
        self._end_call()   # clean up any active call
        if self._client:
            self._client.disconnect()
        self._client  = None
        self._chat    = None
        self._sidebar = None
        self._show_login()

    # ══════════════════════════════════════════════════════════════
    #  VOICE CALL HANDLERS  (NEW)
    # ══════════════════════════════════════════════════════════════

    def _on_start_call_btn(self, event=None):
        """User clicked the 📞 button in the topbar."""
        if not self._chat or not self._chat._contact:
            return
        contact = self._chat._contact
        if contact in ("__GROUP__", "__BROADCAST__", None):
            messagebox.showinfo("Voice Call",
                                "Voice calls are only available in Direct Messages.")
            return
        if self._voice_call:
            messagebox.showinfo("Voice Call", "A call is already in progress.")
            return
        # Send call invitation
        self._client.call_offer(contact)
        self._call_peer = contact
        if self._chat:
            self._chat.show_system(f"📞 Calling {contact}… waiting for answer")

    def _on_call_offer(self, peer: str):
        """Incoming call from peer — show beautiful accept/decline dialog."""
        if self._voice_call:
            self._client.call_answer(peer, False)
            return

        def _accept():
            self._client.call_answer(peer, True)
            self._start_call(peer)

        def _decline():
            self._client.call_answer(peer, False)
            if self._chat:
                self._chat.show_system(f"📵 Declined call from {peer}.")

        IncomingCallDialog(self, peer,
                           on_accept=_accept,
                           on_decline=_decline)

    def _on_call_answer(self, peer: str, accepted: bool):
        """Peer responded to our call offer."""
        if accepted:
            self._start_call(peer)
        else:
            self._call_peer = None
            if self._chat:
                self._chat.show_system(f"📵 {peer} declined the call.")

    def _on_call_end(self, peer: str):
        """Peer hung up."""
        if self._chat:
            self._chat.show_system(f"📵 {peer} ended the call.")
        self._end_call(notify_peer=False)

    def _on_call_audio(self, peer: str, audio_b64: str):
        """Encrypted audio chunk arrived from peer — play it."""
        if self._voice_call:
            self._voice_call.play(audio_b64)

    def _start_call(self, peer: str):
        """
        Begin a VoiceCall using the DH-FS shared secret.
        Falls back to a derived key from RSA fingerprints if DH not ready yet.
        Opens the CallWindow floating dialog.
        """
        from client import VoiceCall, _PYAUDIO_OK
        import hashlib
        if not _PYAUDIO_OK:
            messagebox.showerror(
                "pyaudio missing",
                "Voice calls require pyaudio.\n\nInstall it with:\n  pip install pyaudio",
            )
            return

        shared = self._client._dh_state.get(peer, {}).get("shared")
        if not shared:
            # Fallback: derive a shared key from both RSA public key fingerprints
            my_fp   = self._client.get_fingerprint()
            peer_fp = self._client.get_peer_fingerprint(peer)
            if peer_fp == "Key not yet received":
                if self._chat:
                    self._chat.show_system(
                        f"⚠ {peer} has not shared their key yet. "
                        "Wait a few more seconds and try again."
                    )
                return
            # Deterministic shared secret from both fingerprints
            combined = "".join(sorted([my_fp, peer_fp]))
            shared   = hashlib.sha256(combined.encode()).digest()
            if self._chat:
                self._chat.show_system(
                    f"🔒 Call using RSA-derived key (DH-FS key not ready yet)"
                )

        try:
            self._voice_call = VoiceCall(
                shared_key   = shared,
                on_audio_out = lambda d, p=peer: self._client.send_audio(p, d),
            )
            self._voice_call.start()
        except Exception as e:
            messagebox.showerror("Call Error", str(e))
            return

        self._call_peer   = peer
        self._call_window = CallWindow(
            self,
            peer       = peer,
            on_hangup  = self._hangup,
            voice_call = self._voice_call,
        )
        if self._chat:
            self._chat.show_system(
                f"🔒 Encrypted call started with {peer}  "
                f"(AES-256-GCM · DH-FS key)"
            )

    def _hangup(self):
        """User pressed hang-up button."""
        if self._call_peer and self._client:
            self._client.call_end(self._call_peer)
        self._end_call(notify_peer=False)

    def _end_call(self, notify_peer: bool = True):
        """Clean up call state regardless of who ended it."""
        if self._voice_call:
            self._voice_call.stop()
            self._voice_call = None
        if self._call_window:
            self._call_window.close()
            self._call_window = None
        peer = self._call_peer
        self._call_peer = None
        if peer and self._chat:
            self._chat.show_system(f"📵 Call with {peer} ended.")

    # ══════════════════════════════════════════════════════════════
    #  EXISTING DISPATCHERS
    # ══════════════════════════════════════════════════════════════

    def _open_own_profile_editor(self):
        if not self._chat:
            return
        own = self._profiles.get(self._chat._me, {})
        own["username"] = self._chat._me

        def _save(updated):
            self._client.send_profile_update(**{
                k: updated[k]
                for k in ["display_name", "bio", "avatar",
                          "status_emoji", "status_text"]
            })
            # Immediately update local profile so UI refreshes without waiting
            me = self._chat._me if self._chat else ""
            updated["username"] = me
            self._profiles[me] = updated
            if self._sidebar:
                self._sidebar.update_own_profile(updated)

        ProfileEditor(self, own, on_save=_save)

    def _open_profile_from_event(self, event):
        username = getattr(self._chat, "_profile_target", None)
        if username:
            if self._client:
                self._client.request_profile(username)
            self._open_profile_popup(username)

    def _open_profile_popup(self, username: str):
        if not self._chat:
            return
        profile = self._profiles.get(username, {})
        fp      = self._client.get_peer_fingerprint(username)
        ProfilePopup(self, username, profile, fp,
                     on_dm=self._chat.load_contact)

    def _open_sessions_panel(self):
        if not self._client:
            return
        sid = getattr(self._client, "session_id", None)
        SessionsPanel(self, self._sessions, sid,
                      on_kick=self._client.kick_session)

    def _dispatch_message(self, sender, text, extra):
        chat    = self._chat
        sidebar = self._sidebar
        if not chat:
            return
        chat.receive_message(sender, text, extra)
        if chat._contact != sender:
            if sidebar:
                sidebar.ensure_contact(sender)
                sidebar.notify_unread(sender)
            Toast(self, sender, text)

    def _dispatch_broadcast(self, sender, text):
        chat    = self._chat
        sidebar = self._sidebar
        if not chat:
            return
        chat.receive_broadcast(sender, text)
        if chat._contact != "__BROADCAST__" and sidebar:
            sidebar.notify_unread("__BROADCAST__")

    def _dispatch_system(self, text):
        if self._chat:
            self._chat.show_system(text)

    def _dispatch_online(self, users):
        if self._sidebar:
            self._sidebar.update_users(users)

    def _dispatch_group(self, sender, text, extra):
        chat    = self._chat
        sidebar = self._sidebar
        if not chat:
            return
        chat.receive_group_message(sender, text, extra)
        if chat._contact != "__GROUP__":
            if sidebar:
                sidebar.notify_unread("__GROUP__")
            Toast(self, f"👥 {sender}", text)

    def _dispatch_typing(self, sender):
        if self._chat:
            self._chat.show_typing(sender)

    def _dispatch_history(self, channel, messages):
        if self._chat:
            self._chat.load_history(channel, messages)

    def _dispatch_profile(self, username, profile):
        # Merge — keep existing avatar if new profile has none
        existing = self._profiles.get(username, {})
        if not profile.get("avatar") and existing.get("avatar"):
            profile["avatar"] = existing["avatar"]
        self._profiles[username] = profile
        if self._sidebar:
            self._sidebar.update_profiles({username: profile})
        if self._chat:
            self._chat.update_profiles({username: profile})

    def _dispatch_own_profile(self, profile):
        me = self._chat._me if self._chat else ""
        self._profiles[me] = profile
        if self._sidebar:
            self._sidebar.update_own_profile(profile)
        # Also update ChatPane profiles so bubbles show correct avatar
        if self._chat:
            self._chat.update_profiles({me: profile})

    def _dispatch_profile_bundle(self, profiles: dict):
        self._profiles.update(profiles)
        if self._sidebar:
            self._sidebar.update_profiles(profiles)
        if self._chat:
            self._chat.update_profiles(profiles)

    def _dispatch_edit(self, msg_id, new_text):
        if self._chat:
            self._chat.apply_edit(msg_id, new_text)

    def _dispatch_delete(self, msg_id):
        if self._chat:
            self._chat.apply_delete(msg_id)

    def _dispatch_reaction(self, msg_id, counts):
        if self._chat:
            self._chat.apply_reaction(msg_id, counts)

    def _dispatch_sessions(self, sessions):
        self._sessions = sessions

    def _dispatch_self_destruct(self, msg_id, remaining):
        if self._chat:
            bub = self._chat._bubbles.get(msg_id)
            if bub:
                bub.start_destruct_timer(remaining)

    def _dispatch_totp_setup(self, secret, uri):
        if self._totp_dialog and self._totp_dialog.winfo_exists():
            pass  # already open
        else:
            self._totp_dialog = TotpSetupDialog(
                self, secret, uri,
                on_verify=lambda code: self._client.verify_totp_enable(code),
            )

    def _dispatch_totp_result(self, ok, message, action):
        if action == "enable":
            self._totp_enabled = ok
            if self._totp_dialog and self._totp_dialog.winfo_exists():
                self._totp_dialog.show_result(ok, message)
            if ok and self._chat:
                self._chat.show_system("🔐 Two-factor authentication enabled!")
            elif not ok and self._chat:
                self._chat.show_system(f"✗ 2FA error: {message}")
        elif action == "disable":
            if ok:
                self._totp_enabled = False
                if self._chat:
                    self._chat.show_system("🔓 Two-factor authentication disabled.")
            else:
                messagebox.showerror("2FA", message)

    def _dispatch_totp_status(self, enabled):
        self._totp_enabled = enabled

    def _open_2fa_settings(self):
        if not self._client:
            return
        # Ask server for current status with longer wait
        self._client.request_totp_status()
        self.after(800, self._show_2fa_menu)

    def _show_2fa_menu(self):
        if self._totp_enabled:
            msg = 'Disable 2FA on this account?'
            result = messagebox.askyesno('2FA Settings', msg)
            if result:
                code = simpledialog.askstring(
                    'Disable 2FA',
                    'Enter your 6-digit code:',
                    parent=self)
                if code and code.strip():
                    self._client.disable_totp(code.strip())
        else:
            self._client.request_totp_setup()
            if self._chat:
                self._chat.show_system(
                    '🔐 2FA setup started. QR code window opening...')


    # ── Chat PIN methods ──────────────────────────────────────────────


    def _on_chat_select(self, name: str):
        if name in ('__GROUP__', '__BROADCAST__'):
            if self._chat:
                self._chat.load_contact(name)
            return
        # Request fresh profile (with avatar) when opening a chat
        if self._client:
            self._client.request_profile(name)
        # Always ask PIN when switching INTO a locked chat
        if _chat_has_pin(name):
            ChatPinDialog(
                self, name,
                on_unlock = lambda n=name: self._unlock_chat(n),
                on_cancel = lambda: None,
            )
        else:
            if self._chat:
                self._chat.load_contact(name)

    def _unlock_chat(self, name: str):
        if self._chat:
            self._chat.load_contact(name)

    def _open_chat_lock_settings(self, name: str):
        def _on_done(locked: bool):
            # Re-render sidebar to update lock icon
            if self._sidebar:
                self._sidebar._render_list(self._sidebar._all_users)
            if locked and self._chat:
                self._chat.show_system(
                    f'🔒 Chat with {name} is now LOCKED with a PIN.')
                # Re-lock the chat
                self._unlocked_chats.discard(name)
            elif not locked and self._chat:
                self._chat.show_system(
                    f'🔓 Chat with {name} is now UNLOCKED.')
                self._unlocked_chats.add(name)
        ChatPinSetupDialog(self, name, on_done=_on_done)

    def _dispatch_dh(self, msg):
        peer = msg.get("peer", "")
        if (self._chat and self._client and
                self._chat._contact == peer and
                self._client.has_dh_secret(peer)):
            self._chat._badge_e2e.config(text="E2E+DH-FS", fg=C["success"])


# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    App().mainloop()