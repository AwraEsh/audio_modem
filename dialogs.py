"""Small reusable settings dialog with scroll, reset, export, import."""
from __future__ import annotations

from dataclasses import dataclass, replace
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from common import ModemSettings, clamp_settings, save_settings_to_file, load_settings_from_file


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
    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        current_settings: ModemSettings,
        default_settings: ModemSettings,
        fields: list[FieldSpec],
    ) -> None:
        self.parent = parent
        self.title = title
        self.current = current_settings
        self.default = default_settings
        self.fields = fields
        self.result = None
        self._vars: dict[str, tk.StringVar] = {}

    def show(self):
        self.win = tk.Toplevel(self.parent)
        self.win.title(self.title)
        self.win.transient(self.parent.winfo_toplevel())
        self.win.grab_set()
        self.win.resizable(True, True)
        self.win.geometry("640x580")
        self.win.minsize(520, 480)

        # رنگ پس‌زمینه برای هماهنگی با دارک مود
        self.win.configure(bg="#111317")

        body = ttk.Frame(self.win, padding=16)
        body.pack(fill=tk.BOTH, expand=True)

        ttk.Label(body, text=self.title, style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            body,
            text="These values affect both transmission quality and decoding stability. Keep the defaults unless needed.",
            style="Subtitle.TLabel",
            wraplength=560,
        ).pack(anchor="w", pady=(4, 10))

        # ---------- منطقه اسکرول شونده ----------
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

        # اسکرول با ماوس (فقط روی کانواس)
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind("<MouseWheel>", _on_mousewheel)
        scrollable_frame.bind("<MouseWheel>", _on_mousewheel)
        # ------------------------------------

        # ساخت فیلدها درون scrollable_frame
        for field in self.fields:
            row = ttk.Frame(scrollable_frame)
            row.pack(fill=tk.X, pady=8)

            label_col = ttk.Frame(row)
            label_col.pack(fill=tk.X)
            ttk.Label(label_col, text=field.label, font=("Segoe UI", 10, "bold")).pack(anchor="w")
            ttk.Label(label_col, text=field.description, style="Subtitle.TLabel", wraplength=580).pack(anchor="w", pady=(2, 0))

            var = tk.StringVar(value=str(getattr(self.current, field.attr)))
            self._vars[field.attr] = var
            entry = ttk.Entry(row, textvariable=var, width=20)
            entry.pack(anchor="w", pady=(4, 0))

        # دکمه‌های پایین (خارج از اسکرول)
        btn_frame = ttk.Frame(body)
        btn_frame.pack(fill=tk.X, pady=(16, 0))

        # دکمه Reset
        ttk.Button(btn_frame, text="Reset to Defaults", command=self._reset_to_defaults).pack(side=tk.LEFT, padx=(0, 8))
        # دکمه Export
        ttk.Button(btn_frame, text="Export Settings", command=self._export_settings).pack(side=tk.LEFT, padx=(0, 8))
        # دکمه Import
        ttk.Button(btn_frame, text="Import Settings", command=self._import_settings).pack(side=tk.LEFT)

        # دکمه‌های Apply / Cancel در سمت راست
        ttk.Button(btn_frame, text="Cancel", command=self._cancel).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(btn_frame, text="Apply", command=self._apply).pack(side=tk.RIGHT)

        self.win.bind("<Escape>", lambda _e: self._cancel())
        self.win.bind("<Return>", lambda _e: self._apply())
        self.parent.wait_window(self.win)
        return self.result

    def _reset_to_defaults(self):
        """Reset all fields to default values from self.default."""
        for field in self.fields:
            default_val = getattr(self.default, field.attr)
            self._vars[field.attr].set(str(default_val))

    def _export_settings(self):
        """Save current settings (as shown in dialog) to a JSON file."""
        # جمع‌آوری مقادیر فعلی
        temp_settings = self._current_settings_from_vars()
        file_path = filedialog.asksaveasfilename(
            parent=self.win,
            title="Export Modem Settings",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
            initialfile="modem_settings.json",
        )
        if file_path:
            try:
                save_settings_to_file(temp_settings, file_path)
                messagebox.showinfo("Export Successful", f"Settings saved to:\n{file_path}", parent=self.win)
            except Exception as e:
                messagebox.showerror("Export Failed", str(e), parent=self.win)

    def _import_settings(self):
        """Load settings from a JSON file and update the entry fields."""
        file_path = filedialog.askopenfilename(
            parent=self.win,
            title="Import Modem Settings",
            filetypes=[("JSON files", "*.json")],
        )
        if file_path:
            try:
                loaded = load_settings_from_file(file_path)
                # به‌روزرسانی همه فیلدها با مقادیر بارگذاری شده
                for field in self.fields:
                    value = getattr(loaded, field.attr)
                    self._vars[field.attr].set(str(value))
                messagebox.showinfo("Import Successful", "Settings loaded. Click Apply to use them.", parent=self.win)
            except Exception as e:
                messagebox.showerror("Import Failed", str(e), parent=self.win)

    def _current_settings_from_vars(self) -> ModemSettings:
        """Build a ModemSettings object from current entry values."""
        updates = {}
        for field in self.fields:
            raw = self._vars[field.attr].get().strip()
            if field.kind == "int":
                value = int(float(raw))
            elif field.kind == "float":
                value = float(raw)
            else:
                value = raw
            # اعمال محدودیت min/max
            if field.minimum is not None and value < field.minimum:
                value = field.minimum
            if field.maximum is not None and value > field.maximum:
                value = field.maximum
            updates[field.attr] = value
        return replace(self.current, **updates)

    def _cancel(self) -> None:
        self.result = None
        if self.win.winfo_exists():
            self.win.destroy()

    def _apply(self) -> None:
        self.result = self._current_settings_from_vars()
        if self.win.winfo_exists():
            self.win.destroy()