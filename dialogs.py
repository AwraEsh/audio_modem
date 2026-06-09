"""Small reusable settings dialog."""
from __future__ import annotations

from dataclasses import dataclass, replace
import tkinter as tk
from tkinter import ttk


@dataclass(frozen=True)
class FieldSpec:
    attr: str
    label: str
    description: str
    kind: str = "float"  # int, float, text
    minimum: float | None = None
    maximum: float | None = None
    step: float = 1.0


class SettingsDialog:
    def __init__(self, parent: tk.Misc, title: str, settings, fields: list[FieldSpec]) -> None:
        self.parent = parent
        self.title = title
        self.settings = settings
        self.fields = fields
        self.result = None
        self._vars: dict[str, tk.StringVar] = {}

    def show(self):
        self.win = tk.Toplevel(self.parent)
        self.win.title(self.title)
        self.win.transient(self.parent.winfo_toplevel())
        self.win.grab_set()
        self.win.resizable(True, True)  # اجازه تغییر اندازه
        self.win.geometry("620x560")    # اندازه اولیه مناسب

        body = ttk.Frame(self.win, padding=16)
        body.pack(fill=tk.BOTH, expand=True)

        ttk.Label(body, text=self.title, style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            body,
            text="These values affect both transmission quality and decoding stability. Keep the defaults unless needed.",
            style="Subtitle.TLabel",
            wraplength=560,
        ).pack(anchor="w", pady=(4, 14))

        # ---------- قسمت اسکرول شونده ----------
        canvas_frame = ttk.Frame(body)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(canvas_frame, highlightthickness=0, bg="#111317")
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # حلقه ماوس برای اسکرول
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        # ------------------------------------

        # ساخت فیلدها داخل scrollable_frame
        for field in self.fields:
            row = ttk.Frame(scrollable_frame)
            row.pack(fill=tk.X, pady=7)

            label_col = ttk.Frame(row)
            label_col.pack(fill=tk.X)
            ttk.Label(label_col, text=field.label, font=("Segoe UI", 10, "bold")).pack(anchor="w")
            ttk.Label(label_col, text=field.description, style="Subtitle.TLabel", wraplength=580).pack(anchor="w", pady=(2, 0))

            var = tk.StringVar(value=str(getattr(self.settings, field.attr)))
            self._vars[field.attr] = var
            entry = ttk.Entry(row, textvariable=var, width=18)
            entry.pack(anchor="w", pady=(4, 0))

        # دکمه‌ها (خارج از ناحیه اسکرول)
        buttons = ttk.Frame(body)
        buttons.pack(fill=tk.X, pady=(16, 0))

        ttk.Button(buttons, text="Cancel", command=self._cancel).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(buttons, text="Apply", command=self._apply).pack(side=tk.RIGHT)

        self.win.bind("<Escape>", lambda _e: self._cancel())
        self.win.bind("<Return>", lambda _e: self._apply())
        self.parent.wait_window(self.win)
        return self.result

    def _cancel(self) -> None:
        self.result = None
        if self.win.winfo_exists():
            self.win.destroy()

    def _apply(self) -> None:
        updates = {}
        for field in self.fields:
            raw = self._vars[field.attr].get().strip()
            if field.kind == "int":
                value = int(float(raw))
            elif field.kind == "float":
                value = float(raw)
            else:
                value = raw

            if field.minimum is not None and value < field.minimum:
                value = field.minimum
            if field.maximum is not None and value > field.maximum:
                value = field.maximum

            updates[field.attr] = value

        self.result = replace(self.settings, **updates)
        if self.win.winfo_exists():
            self.win.destroy()
