from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import numpy as np

from audio_backend import AudioBackendError, Recorder, create_input_stream, list_audio_devices, sounddevice_available
from common import SAMPLE_RATE, audio_to_bits, decode_audio_to_text, parse_frame_bits, summarize_audio_length
from ui_theme import configure_dark_theme


class ReceiverApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Audio Modem — Voice to Text")
        self.root.geometry("980x760")
        self.root.minsize(880, 640)

        configure_dark_theme(root)

        self.advanced_var = tk.BooleanVar(value=False)
        self.live_decode_var = tk.BooleanVar(value=True)

        self.status_var = tk.StringVar(
            value="Choose an input device, press Preview or Start Listening, then transmit from the other side."
        )
        self.backend_var = tk.StringVar(value=self._backend_note())
        self.level_text_var = tk.StringVar(value="Mic level: idle")
        self.device_map: dict[str, int | None] = {}
        self.selected_device_id: int | None = None

        self.preview_active = False
        self.listening_active = False
        self.recorder: Recorder | None = None

        self._preview_stream = None
        self._capture_stream = None
        self._capture_lock = threading.Lock()
        self._captured_chunks: list[np.ndarray] = []
        self._latest_level = 0.0
        self._latest_peak = 0.0
        self._decode_thread_running = False
        self._last_live_text = ""
        self._preview_token = 0

        self._build_ui()
        self.refresh_devices()
        self._schedule_meter_update()

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=18)
        container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(container, text="Voice to Text", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            container,
            text="Record audio locally, preview the selected microphone, and decode the frame with CRC protection.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(4, 12))

        device_frame = ttk.LabelFrame(container, text="Input Device", padding=12)
        device_frame.pack(fill=tk.X, pady=(0, 12))

        top_row = ttk.Frame(device_frame)
        top_row.pack(fill=tk.X)

        self.input_device_var = tk.StringVar()
        self.input_combo = ttk.Combobox(top_row, textvariable=self.input_device_var, state="readonly")
        self.input_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Checkbutton(
            top_row,
            text="Show advanced devices",
            variable=self.advanced_var,
            command=self.refresh_devices,
        ).pack(side=tk.LEFT, padx=(10, 0))

        ttk.Button(top_row, text="Refresh", command=self.refresh_devices).pack(side=tk.LEFT, padx=(10, 0))

        meter_frame = ttk.Frame(device_frame)
        meter_frame.pack(fill=tk.X, pady=(12, 0))

        self.meter = ttk.Progressbar(meter_frame, style="Dark.Horizontal.TProgressbar", mode="determinate", maximum=100.0)
        self.meter.pack(fill=tk.X)
        ttk.Label(meter_frame, textvariable=self.level_text_var).pack(anchor="w", pady=(4, 0))

        control_frame = ttk.Frame(container)
        control_frame.pack(fill=tk.X, pady=(0, 12))

        self.preview_button = ttk.Button(control_frame, text="Start Preview", command=self.start_preview)
        self.preview_button.pack(side=tk.LEFT)

        self.stop_preview_button = ttk.Button(control_frame, text="Stop Preview", command=self.stop_preview, state="disabled")
        self.stop_preview_button.pack(side=tk.LEFT, padx=(8, 0))

        self.start_button = ttk.Button(control_frame, text="Start Listening", command=self.start_listening)
        self.start_button.pack(side=tk.LEFT, padx=(18, 0))

        self.stop_button = ttk.Button(control_frame, text="Stop and Decode", command=self.stop_and_decode, state="disabled")
        self.stop_button.pack(side=tk.LEFT, padx=(8, 0))

        ttk.Checkbutton(
            control_frame,
            text="Live decode",
            variable=self.live_decode_var,
        ).pack(side=tk.LEFT, padx=(18, 0))

        ttk.Button(control_frame, text="Clear", command=self.clear_output).pack(side=tk.LEFT, padx=(8, 0))

        output_frame = ttk.LabelFrame(container, text="Decoded Text", padding=12)
        output_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 12))

        self.output = scrolledtext.ScrolledText(
            output_frame,
            height=18,
            wrap=tk.WORD,
            font=("Segoe UI", 12),
            background="#1a1a1a",
            foreground="#f2f2f2",
            insertbackground="#f2f2f2",
            selectbackground="#345",
            relief=tk.FLAT,
            borderwidth=0,
        )
        self.output.pack(fill=tk.BOTH, expand=True)
        self.output.insert("1.0", "Decoded text will appear here.\n")
        self.output.configure(state=tk.DISABLED)

        ttk.Separator(container).pack(fill=tk.X, pady=(4, 10))
        ttk.Label(container, textvariable=self.backend_var).pack(anchor="w")
        ttk.Label(container, textvariable=self.status_var).pack(anchor="w", pady=(4, 0))

    def _backend_note(self) -> str:
        if sounddevice_available():
            return "Audio backend: sounddevice / PortAudio"
        return "Audio backend: fallback recording is available, but preview/live decode need sounddevice."

    def refresh_devices(self) -> None:
        show_advanced = self.advanced_var.get()
        devices = list_audio_devices("input", advanced=show_advanced)

        values: list[str] = ["System default input"]
        self.device_map = {"System default input": None}

        for device in devices:
            label = device.label()
            values.append(label)
            self.device_map[label] = device.id

        self.input_combo["values"] = values
        self.input_combo.set("System default input")

        if len(values) == 1:
            self.status_var.set("No selectable input devices were found. System default will be used if available.")
        else:
            self.status_var.set(f"Found {len(values) - 1} input device(s).")

    def clear_output(self) -> None:
        self.output.configure(state=tk.NORMAL)
        self.output.delete("1.0", tk.END)
        self.output.insert("1.0", "Decoded text will appear here.\n")
        self.output.configure(state=tk.DISABLED)

    def _set_status(self, text: str) -> None:
        self.root.after(0, lambda: self.status_var.set(text))

    def _set_output(self, text: str) -> None:
        def apply() -> None:
            self.output.configure(state=tk.NORMAL)
            self.output.delete("1.0", tk.END)
            self.output.insert("1.0", text)
            self.output.configure(state=tk.DISABLED)

        self.root.after(0, apply)

    def _set_meter(self, level: float, peak: float) -> None:
        self._latest_level = level
        self._latest_peak = peak

    def _schedule_meter_update(self) -> None:
        if self.preview_active or self.listening_active:
            level = max(0.0, min(100.0, self._latest_level * 140.0))
            self.meter["value"] = level

            if self._latest_peak > 0:
                rms_db = 20.0 * np.log10(max(self._latest_level, 1e-6))
                peak_db = 20.0 * np.log10(max(self._latest_peak, 1e-6))
                self.level_text_var.set(f"Mic level: RMS {rms_db:.1f} dBFS | Peak {peak_db:.1f} dBFS")
            else:
                self.level_text_var.set("Mic level: idle")

        self.root.after(80, self._schedule_meter_update)

    def _open_device(self) -> int | None:
        chosen = self.input_device_var.get().strip()
        return self.device_map.get(chosen)

    def _wrap_capture_callback(self, *, store_audio: bool):
        def _callback(indata, frames, time_info, status):  # noqa: ANN001
            del frames, time_info, status
            mono = np.asarray(indata, dtype=np.float32).reshape(-1)
            if mono.size == 0:
                return

            rms = float(np.sqrt(np.mean(np.square(mono))))
            peak = float(np.max(np.abs(mono)))
            self._set_meter(rms, peak)

            if store_audio:
                chunk = mono.copy()
                with self._capture_lock:
                    self._captured_chunks.append(chunk)
                    # Keep the buffer finite so live decode stays fast.
                    total = sum(part.size for part in self._captured_chunks)
                    limit = int(SAMPLE_RATE * 18)
                    while total > limit and self._captured_chunks:
                        removed = self._captured_chunks.pop(0)
                        total -= removed.size

        return _callback

    def start_preview(self) -> None:
        if self.preview_active or self.listening_active:
            return

        if not sounddevice_available():
            messagebox.showinfo(
                "Preview unavailable",
                "Live preview needs sounddevice / PortAudio on this system.",
                parent=self.root,
            )
            return

        device_id = self._open_device()
        self.selected_device_id = device_id

        try:
            self._preview_stream = create_input_stream(
                samplerate=SAMPLE_RATE,
                device=device_id,
                callback=self._wrap_capture_callback(store_audio=False),
            )
            self._preview_stream.start()
        except AudioBackendError as exc:
            messagebox.showerror("Preview error", str(exc), parent=self.root)
            return

        self.preview_active = True
        self._preview_token += 1
        self.preview_button.configure(state="disabled")
        self.stop_preview_button.configure(state="normal")
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="disabled")
        self.status_var.set("Preview running. Speak into the selected microphone to check the level meter.")

    def stop_preview(self) -> None:
        if not self.preview_active:
            return

        self.preview_active = False
        if self._preview_stream is not None:
            try:
                self._preview_stream.stop()
                self._preview_stream.close()
            except Exception:
                pass
            self._preview_stream = None

        self.preview_button.configure(state="normal")
        self.stop_preview_button.configure(state="disabled")
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.status_var.set("Preview stopped.")

    def start_listening(self) -> None:
        if self.listening_active:
            return

        if self.preview_active:
            self.stop_preview()

        chosen = self._open_device()
        self.selected_device_id = chosen

        self._captured_chunks = []

        if sounddevice_available():
            try:
                self._capture_stream = create_input_stream(
                    samplerate=SAMPLE_RATE,
                    device=chosen,
                    callback=self._wrap_capture_callback(store_audio=True),
                )
                self._capture_stream.start()
                self.recorder = None
                backend_name = "sounddevice"
            except AudioBackendError as exc:
                messagebox.showerror("Record error", str(exc), parent=self.root)
                return
        else:
            try:
                self.recorder = Recorder(device=chosen)
                self.recorder.start()
                backend_name = self.recorder.mode
            except AudioBackendError as exc:
                messagebox.showerror("Record error", str(exc), parent=self.root)
                return

        self.listening_active = True
        self._last_live_text = ""
        self.preview_button.configure(state="disabled")
        self.stop_preview_button.configure(state="disabled")
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")

        if self.live_decode_var.get() and sounddevice_available():
            self.status_var.set(f"Listening with live decode enabled. Backend: {backend_name}.")
        else:
            self.status_var.set(f"Listening... Backend: {backend_name}. Press Stop and Decode when done.")

        if self.live_decode_var.get() and sounddevice_available():
            self._schedule_live_decode()

    def _schedule_live_decode(self) -> None:
        if not self.listening_active or not self.live_decode_var.get():
            return
        if self._decode_thread_running:
            self.root.after(180, self._schedule_live_decode)
            return

        with self._capture_lock:
            if not self._captured_chunks:
                self.root.after(180, self._schedule_live_decode)
                return
            audio = np.concatenate(self._captured_chunks, axis=0).astype(np.float32, copy=False)

        self._decode_thread_running = True

        def worker(snapshot: np.ndarray) -> None:
            try:
                text, error = decode_audio_to_text(snapshot)
                if text is None:
                    # Keep the UI quiet while the sync word has not shown up yet.
                    if "CRC" not in error and "Sync word" not in error and "incomplete" not in error.lower():
                        self._set_status(f"Listening... {error}")
                    return

                if text != self._last_live_text:
                    self._last_live_text = text
                    self._set_output(text)
                    self._set_status(
                        f"Live decode successful — recorded {summarize_audio_length(snapshot)}."
                    )
            finally:
                self._decode_thread_running = False
                if self.listening_active and self.live_decode_var.get():
                    self.root.after(180, self._schedule_live_decode)

        threading.Thread(target=worker, args=(audio,), daemon=True).start()

    def stop_and_decode(self) -> None:
        if not self.listening_active:
            messagebox.showinfo("Not listening", "Press Start Listening first.", parent=self.root)
            return

        self.listening_active = False

        self.preview_button.configure(state="normal")
        self.stop_preview_button.configure(state="disabled")
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="disabled")

        self.status_var.set("Stopping capture and decoding...")

        def worker() -> None:
            try:
                if self._capture_stream is not None:
                    try:
                        self._capture_stream.stop()
                        self._capture_stream.close()
                    finally:
                        self._capture_stream = None
                    with self._capture_lock:
                        audio = np.concatenate(self._captured_chunks, axis=0).astype(np.float32, copy=False) if self._captured_chunks else np.empty(0, dtype=np.float32)
                elif self.recorder is not None:
                    audio = self.recorder.stop()
                else:
                    audio = np.empty(0, dtype=np.float32)

                if audio.size == 0:
                    raise RuntimeError("No audio was recorded.")

                text, error = decode_audio_to_text(audio)
                if text is None:
                    raise RuntimeError(error)

                self._set_output(text)
                self._set_status(f"Decode successful — recorded {summarize_audio_length(audio)}.")
            except Exception as exc:
                self._set_status("Decode failed.")
                self.root.after(0, lambda: messagebox.showerror("Decode error", str(exc), parent=self.root))
            finally:
                self.root.after(0, lambda: self.start_button.configure(state="normal"))
                self.root.after(0, lambda: self.stop_button.configure(state="disabled"))
                self.root.after(0, lambda: self.preview_button.configure(state="normal"))
                self.root.after(0, lambda: self.stop_preview_button.configure(state="disabled"))
                self.recorder = None

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    root = tk.Tk()
    ReceiverApp(root)
    root.mainloop()
