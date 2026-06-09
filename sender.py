from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from audio_backend import AudioBackendError, list_audio_devices, play_audio, sounddevice_available
from common import SAMPLE_RATE, build_frame_bits, bits_to_audio, text_to_payload
from ui_theme import configure_dark_theme


class SenderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Audio Modem — Text to Voice")
        self.root.geometry("900x660")
        self.root.minsize(800, 580)

        configure_dark_theme(root)

        self.advanced_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Type a message, choose an output device, then press Transmit.")
        self.backend_var = tk.StringVar(value=self._backend_note())
        self.device_map: dict[str, int | None] = {}
        self.selected_device_id: int | None = None

        self._build_ui()
        self.refresh_devices()

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=18)
        container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(container, text="Text to Voice", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            container,
            text="Convert text into a local audio signal using a simple FSK modem.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(4, 12))

        device_frame = ttk.LabelFrame(container, text="Output Device", padding=12)
        device_frame.pack(fill=tk.X, pady=(0, 12))

        top_row = ttk.Frame(device_frame)
        top_row.pack(fill=tk.X)

        self.output_device_var = tk.StringVar()
        self.output_combo = ttk.Combobox(top_row, textvariable=self.output_device_var, state="readonly")
        self.output_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Checkbutton(
            top_row,
            text="Show advanced devices",
            variable=self.advanced_var,
            command=self.refresh_devices,
        ).pack(side=tk.LEFT, padx=(10, 0))

        ttk.Button(top_row, text="Refresh", command=self.refresh_devices).pack(side=tk.LEFT, padx=(10, 0))

        message_frame = ttk.LabelFrame(container, text="Message", padding=12)
        message_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 12))

        self.text_box = scrolledtext.ScrolledText(
            message_frame,
            height=16,
            wrap=tk.WORD,
            font=("Segoe UI", 12),
            background="#1a1a1a",
            foreground="#f2f2f2",
            insertbackground="#f2f2f2",
            selectbackground="#345",
            relief=tk.FLAT,
            borderwidth=0,
        )
        self.text_box.pack(fill=tk.BOTH, expand=True)
        self.text_box.insert("1.0", "Hello from Arash")

        button_row = ttk.Frame(container)
        button_row.pack(fill=tk.X, pady=(0, 10))

        self.transmit_button = ttk.Button(button_row, text="Transmit", command=self.transmit)
        self.transmit_button.pack(side=tk.LEFT)

        ttk.Button(button_row, text="Clear", command=self.clear).pack(side=tk.LEFT, padx=(8, 0))

        self.progress = ttk.Progressbar(container, mode="indeterminate")
        self.progress.pack(fill=tk.X, pady=(2, 8))

        ttk.Separator(container).pack(fill=tk.X, pady=(4, 10))
        ttk.Label(container, textvariable=self.backend_var).pack(anchor="w")
        ttk.Label(container, textvariable=self.status_var).pack(anchor="w", pady=(4, 0))

    def _backend_note(self) -> str:
        if sounddevice_available():
            return "Audio backend: sounddevice / PortAudio"
        return "Audio backend: fallback playback is available, but device selection is limited without sounddevice."

    def refresh_devices(self) -> None:
        devices = list_audio_devices("output", advanced=self.advanced_var.get())
        values: list[str] = ["System default output"]
        self.device_map = {"System default output": None}

        for device in devices:
            label = device.label()
            values.append(label)
            self.device_map[label] = device.id

        self.output_combo["values"] = values
        self.output_combo.set("System default output")

        if len(values) == 1:
            self.status_var.set("No selectable output devices were found. System default will be used if available.")
        else:
            self.status_var.set(f"Found {len(values) - 1} output device(s).")

    def clear(self) -> None:
        self.text_box.delete("1.0", tk.END)

    def _set_status(self, text: str) -> None:
        self.root.after(0, lambda: self.status_var.set(text))

    def _set_busy(self, busy: bool) -> None:
        def apply() -> None:
            self.transmit_button.configure(state="disabled" if busy else "normal")
            if busy:
                self.progress.start(12)
            else:
                self.progress.stop()

        self.root.after(0, apply)

    def transmit(self) -> None:
        text = self.text_box.get("1.0", tk.END).rstrip("\n")
        if not text.strip():
            messagebox.showwarning("Empty message", "Please type something first.", parent=self.root)
            return

        chosen = self.output_device_var.get().strip()
        self.selected_device_id = self.device_map.get(chosen)

        self._set_busy(True)
        self._set_status("Building the frame...")

        try:
            payload = text_to_payload(text)
            bits = build_frame_bits(payload)
            audio = bits_to_audio(bits)
        except Exception as exc:
            self._set_busy(False)
            messagebox.showerror("Build failed", str(exc), parent=self.root)
            return

        def worker() -> None:
            try:
                self._set_status(f"Playing {len(payload)} byte(s) locally...")
                backend = play_audio(audio, samplerate=SAMPLE_RATE, device=self.selected_device_id)
                self._set_status(f"Transmission finished. Playback backend: {backend}.")
            except AudioBackendError as exc:
                self._set_status("Playback failed.")
                self.root.after(0, lambda: messagebox.showerror("Playback error", str(exc), parent=self.root))
            except Exception as exc:  # pragma: no cover
                self._set_status("Playback failed.")
                self.root.after(0, lambda: messagebox.showerror("Playback error", str(exc), parent=self.root))
            finally:
                self._set_busy(False)

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    root = tk.Tk()
    SenderApp(root)
    root.mainloop()
