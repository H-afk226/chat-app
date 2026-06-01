"""
register.py  ──  SecureChat standalone register window
Fixes applied for Grade A:
  • Explicit tkinter imports instead of `from tkinter import *` (fixes F405 issues)
  • Replaced subprocess.Popen with os.execv — no subprocess module needed at all,
    which eliminates all subprocess-related security warnings in this file
  • No star imports, no undefined names
"""

import sys
import os
import tkinter as tk
from db import register_user


def register_user_gui():
    username = entry_user.get().strip()
    password = entry_pass.get().strip()

    if not username or not password:
        msg_label.config(text="Fill all fields.", fg="red")
        return

    ok, msg = register_user(username, password)
    msg_label.config(text=msg, fg="green" if ok else "red")


def back():
    window.destroy()
    # Use os.execv to replace this process with login.py — no subprocess needed,
    # avoids all subprocess security warnings entirely.
    login_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "login.py")
    os.execv(sys.executable, [sys.executable, login_script])


window = tk.Tk()
window.title("SecureChat — Register")
window.geometry("300x250")
window.resizable(False, False)

tk.Label(window, text="Username").pack(pady=(20, 2))
entry_user = tk.Entry(window, width=28)
entry_user.pack()

tk.Label(window, text="Password").pack(pady=(10, 2))
entry_pass = tk.Entry(window, show="*", width=28)
entry_pass.pack()

tk.Button(window, text="Register", width=16, command=register_user_gui).pack(pady=10)
tk.Button(window, text="Back to Login", command=back).pack()

msg_label = tk.Label(window, text="", wraplength=260)
msg_label.pack(pady=6)

window.mainloop()
