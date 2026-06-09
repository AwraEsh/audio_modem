"""Dark theme for the Tkinter apps."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk


BG = "#111317"
PANEL = "#171a21"
TEXT = "#f0f3f8"
MUTED = "#aab4c3"
ACCENT = "#4c8bf5"
ENTRY = "#20242d"
BORDER = "#2a2f3a"
SELECT = "#264b8e"


def configure_dark_theme(root: tk.Tk) -> None:
    root.configure(bg=BG)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure(".", background=BG, foreground=TEXT, fieldbackground=ENTRY)
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"), foreground=TEXT)
    style.configure("Subtitle.TLabel", font=("Segoe UI", 10), foreground=MUTED)
    style.configure("TLabelFrame", background=BG, foreground=TEXT, bordercolor=BORDER)
    style.configure("TLabelframe.Label", background=BG, foreground=TEXT)
    style.configure("TButton", padding=(12, 7), font=("Segoe UI", 10))
    style.map("TButton", background=[("active", PANEL)])
    style.configure("TRadiobutton", background=BG, foreground=TEXT)
    style.map("TRadiobutton", foreground=[("active", TEXT)])
    style.configure("TCheckbutton", background=BG, foreground=TEXT)
    style.map("TCheckbutton", foreground=[("active", TEXT)])
    style.configure("TEntry", fieldbackground=ENTRY, foreground=TEXT, insertcolor=TEXT)
    style.configure("TCombobox", fieldbackground=ENTRY, foreground=TEXT, insertcolor=TEXT)
    style.map("TCombobox", fieldbackground=[("readonly", ENTRY)], selectbackground=[("readonly", SELECT)])
    style.configure("TSeparator", background=BORDER)
    style.configure("Dark.Horizontal.TProgressbar", troughcolor=PANEL, background=ACCENT, bordercolor=PANEL, lightcolor=ACCENT, darkcolor=ACCENT)

    # Keep standard dialogs readable.
    root.option_add("*Dialog.msg.font", "Segoe UI 10")
    root.option_add("*Dialog.msg.foreground", TEXT)
    root.option_add("*Dialog.background", BG)
