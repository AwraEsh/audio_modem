from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from audio_backend import (
    AudioBackendError,
    list_output_devices,
    play_audio,
    sounddevice_available,
)
from common import SAMPLE_RATE, build_frame_bits, bits_to_audio, text_to_payload


class SenderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Audio Modem — Text to Voice")
        self.root.geometry("760x560")
        self.root.minsize(700, 500)

        self._style_ui()

        self.status_var = tk.StringVar(value="Write a message, choose an output device, then press Transmit.")
        self.backend_note_var = tk.StringVar(value=self._backend_note())
        self.device_map: dict[str, int] = {}
        self.selected_device_id: int | None = None
        self.devices_enabled = sounddevice_available()

        container = ttk.Frame(root, padding=16)
        container.pack(fill=tk.BOTH, expand=True)

        title = ttk.Label(container, text="Text to Voice", style="Title.TLabel")
        title.pack(anchor="w")
        ttk.Label(
            container,
            text="Converts text to a local audio signal using a simple FSK modem.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(4, 12))

        device_frame = ttk.LabelFrame(container, text="Output Device", padding=12)
        device_frame.pack(fill=tk.X, pady=(0, 12))
        self.output_device_var = tk.StringVar()
        self.output_combo = ttk.Combobox(device_frame, textvariable=self.output_device_var, state="readonly")
        self.output_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.refresh_button = ttk.Button(device_frame, text="Refresh", command=self.refresh_devices)
        self.refresh_button.pack(side=tk.LEFT, padx=(8, 0))

        text_frame = ttk.LabelFrame(container, text="Message", padding=12)
        text_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 12))
        self.text_box = scrolledtext.ScrolledText(text_frame, height=14, wrap=tk.WORD, font=("Arial", 12))
        self.text_box.pack(fill=tk.BOTH, expand=True)
        self.text_box.insert("1.0", "Hello from Arash")

        button_row = ttk.Frame(container)
        button_row.pack(fill=tk.X, pady=(0, 10))
        self.transmit_button = ttk.Button(button_row, text="Transmit", command=self.transmit)
        self.transmit_button.pack(side=tk.LEFT)
        ttk.Button(button_row, text="Clear", command=self.clear).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Separator(container).pack(fill=tk.X, pady=(4, 8))
        ttk.Label(container, textvariable=self.backend_note_var).pack(anchor="w")
        ttk.Label(container, textvariable=self.status_var).pack(anchor="w", pady=(4, 0))

        self.refresh_devices()

    def _style_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Title.TLabel", font=("Arial", 19, "bold"))
        style.configure("Subtitle.TLabel", font=("Arial", 10))
        style.configure("TButton", padding=(10, 6))
        style.configure("TLabelframe", padding=4)
        style.configure("TLabelframe.Label", font=("Arial", 10, "bold"))

    def _backend_note(self) -> str:
        if sounddevice_available():
            return "Audio backend: sounddevice / PortAudio"
        return "Audio backend: system fallback (device selection disabled until sounddevice becomes available)"

    def refresh_devices(self) -> None:
        devices = list_output_devices()
        if not devices:
            self.device_map = {}
            self.output_combo["values"] = ["System default output"]
            self.output_combo.current(0)
            self.output_combo.configure(state="disabled")
            self.selected_device_id = None
            self.refresh_button.configure(state="disabled")
            self.status_var.set("No selectable output devices were found. Using the default output backend.")
            return

        values: list[str] = ["System default output"]
        self.device_map = {"System default output": None}
        for device in devices:
            label = device.label()
            values.append(label)
            self.device_map[label] = device.id

        self.output_combo.configure(state="readonly")
        self.output_combo["values"] = values
        default_label = "System default output"
        self.output_combo.set(default_label)
        self.selected_device_id = None
        self.refresh_button.configure(state="normal")
        self.status_var.set(f"Found {len(devices)} output device(s).")

    def clear(self) -> None:
        self.text_box.delete("1.0", tk.END)

    def _set_status(self, text: str) -> None:
        self.root.after(0, lambda: self.status_var.set(text))

    def _show_error(self, title: str, text: str) -> None:
        self.root.after(0, lambda: messagebox.showerror(title, text, parent=self.root))

    def transmit(self) -> None:
        text = self.text_box.get("1.0", tk.END).rstrip("\n")
        if not text.strip():
            messagebox.showwarning("Empty message", "Please type something first.", parent=self.root)
            return

        chosen = self.output_device_var.get().strip()
        self.selected_device_id = self.device_map.get(chosen)

        self.transmit_button.configure(state="disabled")
        self.refresh_button.configure(state="disabled")
        self._set_status("Building frame...")

        try:
            payload = text_to_payload(text)
            bits = build_frame_bits(payload)
            audio = bits_to_audio(bits)
        except Exception as exc:  # pragma: no cover
            self.transmit_button.configure(state="normal")
            self.refresh_button.configure(state="normal")
            messagebox.showerror("Build failed", str(exc), parent=self.root)
            return

        def worker() -> None:
            try:
                self._set_status(f"Playing {len(payload)} byte(s) locally...")
                backend = play_audio(audio, samplerate=SAMPLE_RATE, device=self.selected_device_id)
                self._set_status(f"Transmission finished. Backend used: {backend}.")
            except AudioBackendError as exc:
                self._set_status("Playback failed.")
                self._show_error(
                    "Playback error",
                    f"{exc}\n\nIf sounddevice is unavailable, Linux playback falls back to ffplay when installed.",
                )
            except Exception as exc:  # pragma: no cover
                self._set_status("Playback failed.")
                self._show_error("Playback error", str(exc))
            finally:
                self.root.after(0, lambda: self.transmit_button.configure(state="normal"))
                self.root.after(0, lambda: self.refresh_button.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    root = tk.Tk()
    app = SenderApp(root)
    root.mainloop()
