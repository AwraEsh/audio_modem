from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

import numpy as np

from audio_backend import AudioBackendError, list_audio_devices, play_audio, sounddevice_available, write_wav_file
from common import ModemSettings, clamp_settings, encode_text_to_audio, summarize_audio_length
from dialogs import FieldSpec, SettingsDialog
from ui_theme import configure_dark_theme


SENDER_FIELDS = [
    FieldSpec("freq_low", "Low frequency (0 bit)", "The tone used for bit 0. Keep it clearly below the high tone.", "float", 80.0, 8000.0, 10.0),
    FieldSpec("freq_high", "High frequency (1 bit)", "The tone used for bit 1. A larger gap usually improves stability.", "float", 80.0, 8000.0, 10.0),
    FieldSpec("symbol_rate", "Symbol rate", "How many symbols are sent per second. Higher is faster, lower is easier to decode.", "float", 10.0, 250.0, 1.0),
    FieldSpec("bit_repeat", "Bit repeat", "Each data bit is transmitted this many times. A value of 2 is a good balance.", "int", 1, 8, 1.0),
    FieldSpec("amplitude", "Amplitude", "Overall output loudness. Too high can distort, too low can disappear in noise.", "float", 0.05, 0.95, 0.01),
    FieldSpec("sync_start_freq", "Sync chirp start", "The chirp begins here and sweeps upward to sync the receiver.", "float", 80.0, 8000.0, 10.0),
    FieldSpec("sync_end_freq", "Sync chirp end", "The chirp ends here. Keep it clearly above the start frequency.", "float", 80.0, 8000.0, 10.0),
    FieldSpec("sync_ms", "Sync length (ms)", "How long the chirp burst lasts. Longer sync is more reliable, but slower.", "float", 40.0, 800.0, 5.0),
    FieldSpec("guard_silence_ms", "Guard silence (ms)", "A tiny pause between the sync burst and the data symbols.", "float", 0.0, 300.0, 5.0),
    FieldSpec("lead_silence_ms", "Lead silence (ms)", "Small silence before the frame. Helps the receiver lock onto the first symbol.", "float", 0.0, 800.0, 5.0),
    FieldSpec("trail_silence_ms", "Trail silence (ms)", "Small silence after the frame. Helps when playback or capture lags a little.", "float", 0.0, 800.0, 5.0),
]


class SenderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Audio Modem — Text to Voice")
        self.root.geometry("940x720")
        self.root.minsize(840, 620)

        configure_dark_theme(root)

        self.settings = clamp_settings(ModemSettings())
        self.advanced_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Type text, choose an output device, then press Transmit.")
        self.backend_var = tk.StringVar(value=self._backend_note())
        self.device_map: dict[str, int | None] = {}
        self.selected_device_id: int | None = None
        self.last_audio: np.ndarray | None = None
        self.last_bits: str = ""

        self._build_ui()
        self.refresh_devices()

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=18)
        container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(container, text="Text to Voice", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            container,
            text="Convert text into a local FSK waveform. Everything stays on your machine.",
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

        settings_row = ttk.Frame(device_frame)
        settings_row.pack(fill=tk.X, pady=(10, 0))

        ttk.Button(settings_row, text="Settings", command=self.open_settings).pack(side=tk.LEFT)
        ttk.Label(
            settings_row,
            text="Tune the carrier tones, symbol rate, and frame padding here.",
            style="Subtitle.TLabel",
        ).pack(side=tk.LEFT, padx=(12, 0))

        message_frame = ttk.LabelFrame(container, text="Message", padding=12)
        message_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 12))

        self.text_box = scrolledtext.ScrolledText(
            message_frame,
            height=16,
            wrap=tk.WORD,
            font=("Segoe UI", 12),
            background="#1a1d24",
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

        self.save_button = ttk.Button(button_row, text="Save WAV", command=self.save_wav)
        self.save_button.pack(side=tk.LEFT, padx=(8, 0))

        ttk.Button(button_row, text="Clear", command=self.clear).pack(side=tk.LEFT, padx=(8, 0))

        self.progress = ttk.Progressbar(container, mode="indeterminate")
        self.progress.pack(fill=tk.X, pady=(2, 8))

        ttk.Separator(container).pack(fill=tk.X, pady=(4, 10))
        ttk.Label(container, textvariable=self.backend_var).pack(anchor="w")
        ttk.Label(container, textvariable=self.status_var).pack(anchor="w", pady=(4, 0))

        self._set_save_enabled(False)

    def _backend_note(self) -> str:
        if sounddevice_available():
            return "Audio backend: sounddevice / PortAudio"
        return "Audio backend: fallback playback only. Device selection may be limited without sounddevice."

    def refresh_devices(self) -> None:
        devices = list_audio_devices("output", advanced=self.advanced_var.get(), samplerate=self.settings.sample_rate)
        values: list[str] = ["System default output"]
        self.device_map = {"System default output": None}

        for device in devices:
            label = device.label()
            values.append(label)
            self.device_map[label] = device.id

        self.output_combo["values"] = values
        self.output_combo.set("System default output")

        if len(values) == 1:
            self.status_var.set("No selectable output devices were found. System default will be used.")
        else:
            self.status_var.set(f"Found {len(values) - 1} output device(s).")

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

    def _set_save_enabled(self, enabled: bool) -> None:
        self.save_button.configure(state="normal" if enabled else "disabled")

    def clear(self) -> None:
        self.text_box.delete("1.0", tk.END)
        self._set_save_enabled(False)
        self.last_audio = None
        self.last_bits = ""

    def _selected_device(self) -> int | None:
        return self.device_map.get(self.output_device_var.get())

    def open_settings(self) -> None:
        updated = SettingsDialog(self.root, "Sender Settings", self.settings, SENDER_FIELDS).show()
        if updated is None:
            return
        self.settings = clamp_settings(updated)
        self.backend_var.set(self._backend_note())
        self.refresh_devices()
        self.status_var.set("Settings updated.")

    def transmit(self) -> None:
        text = self.text_box.get("1.0", tk.END).strip()
        if not text:
            messagebox.showinfo("Nothing to send", "Please type a message first.", parent=self.root)
            return

        selected_device = self._selected_device()
        self._set_busy(True)
        self.status_var.set("Encoding audio...")

        def worker() -> None:
            try:
                audio, bits = encode_text_to_audio(text, self.settings)
                self.last_audio = audio
                self.last_bits = bits

                self.root.after(0, lambda: self._set_save_enabled(True))

                backend = play_audio(audio, samplerate=self.settings.sample_rate, device=selected_device)
                self._set_status(f"Transmission finished using {backend}. Audio length: {summarize_audio_length(audio, self.settings.sample_rate)}.")
            except Exception as exc:
                err = str(exc)
                self._set_status("Transmission failed.")
                self.root.after(0, lambda msg=err: messagebox.showerror("Transmit error", msg, parent=self.root))
            finally:
                self._set_busy(False)

        threading.Thread(target=worker, daemon=True).start()

    def save_wav(self) -> None:
        if self.last_audio is None or self.last_audio.size == 0:
            messagebox.showinfo("Nothing to save", "Transmit a message first so the generated audio exists.", parent=self.root)
            return

        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save generated audio",
            defaultextension=".wav",
            filetypes=[("WAV audio", "*.wav")],
            initialfile="audio_modem_tx.wav",
        )
        if not path:
            return

        try:
            write_wav_file(path, self.last_audio, samplerate=self.settings.sample_rate)
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc), parent=self.root)
            return

        self.status_var.set(f"Saved audio to {path}")


if __name__ == "__main__":
    root = tk.Tk()
    SenderApp(root)
    root.mainloop()
