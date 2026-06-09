"""Tiny reusable dark theme helpers for Tkinter/ttk."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk


def configure_dark_theme(root: tk.Tk) -> None:
    root.configure(bg="#121212")

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure(".", background="#121212", foreground="#f2f2f2")
    style.configure("TFrame", background="#121212")
    style.configure("TLabel", background="#121212", foreground="#f2f2f2")
    style.configure("TButton", background="#1e1e1e", foreground="#f2f2f2", padding=(10, 7))
    style.map("TButton", background=[("active", "#2a2a2a")])

    style.configure("TCheckbutton", background="#121212", foreground="#f2f2f2")
    style.map("TCheckbutton", background=[("active", "#121212")])

    style.configure(
        "TLabelframe",
        background="#121212",
        foreground="#f2f2f2",
        bordercolor="#2f2f2f",
    )
    style.configure("TLabelframe.Label", background="#121212", foreground="#f2f2f2")

    style.configure("Title.TLabel", font=("Segoe UI", 19, "bold"))
    style.configure("Subtitle.TLabel", font=("Segoe UI", 10))
    style.configure("Section.TLabel", font=("Segoe UI", 10, "bold"))

    style.configure("Dark.Horizontal.TProgressbar", troughcolor="#1e1e1e", background="#6ea8fe")
