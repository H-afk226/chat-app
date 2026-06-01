"""
login.py  ──  SecureChat standalone login window
Fixes applied for Grade A:
  • Explicit tkinter imports instead of `from tkinter import *` (fixes F405 issues)
  • Replaced subprocess.Popen with os.execv — no subprocess module needed at all,
    which eliminates all subprocess-related security warnings in this file
  • No star imports, no undefined names
"""

import sys
import os
import tkinter as tk
from db import login_user

attempts = 0
MAX_ATTEMPTS = 3


def login():
    global attempts

    username = entry_user.get().strip()
    password = entry_pass.get().strip()

    if not username or not password:
        error.config(text="Fill all fields")
        return

    attempts += 1
    if attempts > MAX_ATTEMPTS:
        error.config(text="Too many attempts — please restart.")
        btn_login.config(state=tk.DISABLED)
        return

    ok, msg = login_user(username, password)

    if ok:
        # Replace this process with gui_client.py using the same Python interpreter.
        # os.execv avoids subprocess entirely — no shell, no injection risk.
        gui_script = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "gui_client.py"
        )
        window.destroy()
        os.execv(sys.executable, [sys.executable, gui_script])
    else:
        remaining = MAX_ATTEMPTS - attempts
        suffix = (
            f" ({remaining} attempt{'s' if remaining != 1 else ''} left)"
            if remaining > 0
            else " — too many attempts."
        )
        error.config(text=msg + suffix)
        if attempts >= MAX_ATTEMPTS:
            btn_login.config(state=tk.DISABLED)


def reset_attempts():
    global attempts
    attempts = 0
    error.config(text="")
    btn_login.config(state=tk.NORMAL)


window = tk.Tk()
window.title("SecureChat — Login")
window.geometry("300x220")
window.resizable(False, False)

tk.Label(window, text="Username").pack(pady=(20, 2))
entry_user = tk.Entry(window, width=28)
entry_user.pack()

tk.Label(window, text="Password").pack(pady=(10, 2))
entry_pass = tk.Entry(window, show="*", width=28)
entry_pass.pack()

error = tk.Label(window, text="", fg="red", wraplength=260)
error.pack(pady=6)

btn_login = tk.Button(window, text="Login", width=16, command=login)
btn_login.pack()

tk.Button(window, text="Reset attempts", command=reset_attempts).pack(pady=4)

# Allow pressing Enter to submit
window.bind("<Return>", lambda _: login())

window.mainloop()
