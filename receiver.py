from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np

from audio_backend import AudioBackendError, Recorder, create_input_stream, list_audio_devices, read_wav_file, sounddevice_available
from common import ModemSettings, clamp_settings, decode_audio_to_text, summarize_audio_length
from dialogs import FieldSpec, SettingsDialog
from ui_theme import configure_dark_theme


RECEIVER_FIELDS = [
    FieldSpec("freq_low", "Low frequency (0 bit)", "Must match the transmitter. A mismatch here breaks the demodulator immediately.", "float", 80.0, 8000.0, 10.0),
    FieldSpec("freq_high", "High frequency (1 bit)", "Must match the transmitter. Keep a clear gap from the low tone.", "float", 80.0, 8000.0, 10.0),
    FieldSpec("symbol_rate", "Symbol rate", "How many symbols are expected per second. Keep this the same as the sender.", "float", 10.0, 250.0, 1.0),
    FieldSpec("bit_repeat", "Bit repeat", "Must match the sender. Repeated bits make the link more tolerant to noise.", "int", 1, 8, 1.0),
    FieldSpec("sync_start_freq", "Sync chirp start", "Must match the sender. This is the starting frequency of the chirp burst.", "float", 80.0, 8000.0, 10.0),
    FieldSpec("sync_end_freq", "Sync chirp end", "Must match the sender. This is the ending frequency of the chirp burst.", "float", 80.0, 8000.0, 10.0),
    FieldSpec("sync_ms", "Sync length (ms)", "Must match the sender. Longer sync makes detection more reliable.", "float", 40.0, 800.0, 5.0),
    FieldSpec("guard_silence_ms", "Guard silence (ms)", "Must match the sender. This tiny gap is skipped before the data starts.", "float", 0.0, 300.0, 5.0),
    FieldSpec("search_tolerance_samples", "Search tolerance (samples)", "How far around the estimated start the decoder should search before giving up.", "int", 0, 64, 1.0),
    FieldSpec("live_buffer_seconds", "Live buffer (seconds)", "How much recent audio is kept for live decoding. Bigger values help slow frames.", "float", 2.0, 30.0, 1.0),
    FieldSpec("lead_silence_ms", "Lead silence (ms)", "Expected silence before the frame. Keep it close to the sender setting.", "float", 0.0, 800.0, 5.0),
    FieldSpec("trail_silence_ms", "Trail silence (ms)", "Expected silence after the frame. Keep it close to the sender setting.", "float", 0.0, 800.0, 5.0),
]


class WaveformCanvas:
    def __init__(self, parent: tk.Misc) -> None:
        self.canvas = tk.Canvas(parent, height=140, background="#12151b", highlightthickness=1, highlightbackground="#2b3040")
        self.canvas.pack(fill=tk.X)
        self._idle_text = self.canvas.create_text(10, 10, anchor="nw", fill="#aab4c3", text="Preview is off.")
        self._wave = None
        self._line = None

    def clear(self) -> None:
        self.canvas.delete("all")
        self._idle_text = self.canvas.create_text(10, 10, anchor="nw", fill="#aab4c3", text="Preview is off.")

    def draw(self, samples: np.ndarray | None, label: str) -> None:
        self.canvas.delete("all")
        width = max(10, int(self.canvas.winfo_width() or self.canvas.winfo_reqwidth()))
        height = max(10, int(self.canvas.winfo_height() or self.canvas.winfo_reqheight()))

        if samples is None or samples.size == 0:
            self._idle_text = self.canvas.create_text(10, 10, anchor="nw", fill="#aab4c3", text=label)
            return

        y = np.asarray(samples, dtype=np.float32).flatten()
        if y.size > 800:
            step = int(np.ceil(y.size / 800))
            y = y[::step]
        y = np.nan_to_num(y, copy=False)
        peak = float(np.max(np.abs(y)))
        if peak > 0:
            y = y / peak

        x = np.linspace(0, width, num=y.size, endpoint=True)
        mid = height / 2.0
        amp = (height * 0.40)
        points = []
        for xi, yi in zip(x, y):
            points.extend([float(xi), float(mid - yi * amp)])

        self.canvas.create_line(0, mid, width, mid, fill="#2b3040")
        if len(points) >= 4:
            self.canvas.create_line(points, fill="#4c8bf5", width=2, smooth=True)
        self.canvas.create_text(10, 10, anchor="nw", fill="#e8eef9", text=label)


class ReceiverApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Audio Modem — Voice to Text")
        self.root.geometry("1080x820")
        self.root.minsize(960, 700)

        configure_dark_theme(root)

        self.settings = clamp_settings(ModemSettings())
        self.advanced_var = tk.BooleanVar(value=False)
        self.live_mode_var = tk.BooleanVar(value=True)

        self.status_var = tk.StringVar(value="Choose an input device, preview the mic, then decode live or manually.")
        self.backend_var = tk.StringVar(value=self._backend_note())
        self.level_text_var = tk.StringVar(value="Mic level: idle")
        self.mode_hint_var = tk.StringVar(value="Live decode is enabled.")
        self.device_map: dict[str, int | None] = {}
        self.selected_device_id: int | None = None

        self.preview_active = False
        self.listening_active = False
        self.recorder: Recorder | None = None

        self._preview_stream = None
        self._capture_stream = None
        self._capture_lock = threading.Lock()
        self._captured_chunks: list[np.ndarray] = []
        self._captured_samples = 0
        self._latest_block = np.zeros(0, dtype=np.float32)
        self._latest_level = 0.0
        self._latest_peak = 0.0
        self._decode_thread_running = False
        self._last_live_text = ""
        self._current_output = ""

        self._build_ui()
        self.refresh_devices()
        self._sync_mode_ui()
        self._schedule_meter_update()
        self._schedule_waveform_update()

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=18)
        container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(container, text="Voice to Text", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            container,
            text="Preview the selected microphone, then decode directly from the live stream or from a WAV file.",
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

        settings_row = ttk.Frame(device_frame)
        settings_row.pack(fill=tk.X, pady=(10, 0))

        ttk.Button(settings_row, text="Settings", command=self.open_settings).pack(side=tk.LEFT)
        ttk.Label(
            settings_row,
            text="Tune the receiver side frequencies, sync tolerance, and live buffer here.",
            style="Subtitle.TLabel",
        ).pack(side=tk.LEFT, padx=(12, 0))

        meter_frame = ttk.Frame(device_frame)
        meter_frame.pack(fill=tk.X, pady=(12, 0))

        self.meter = ttk.Progressbar(meter_frame, style="Dark.Horizontal.TProgressbar", mode="determinate", maximum=100.0)
        self.meter.pack(fill=tk.X)
        ttk.Label(meter_frame, textvariable=self.level_text_var).pack(anchor="w", pady=(4, 0))
        ttk.Label(meter_frame, textvariable=self.backend_var, style="Subtitle.TLabel").pack(anchor="w", pady=(4, 0))

        self.waveform = WaveformCanvas(device_frame)

        mode_frame = ttk.LabelFrame(container, text="Decode Mode", padding=12)
        mode_frame.pack(fill=tk.X, pady=(0, 12))

        ttk.Radiobutton(
            mode_frame,
            text="Live decode",
            value=True,
            variable=self.live_mode_var,
            command=self._sync_mode_ui,
        ).pack(side=tk.LEFT)
        ttk.Radiobutton(
            mode_frame,
            text="Manual record",
            value=False,
            variable=self.live_mode_var,
            command=self._sync_mode_ui,
        ).pack(side=tk.LEFT, padx=(18, 0))
        ttk.Label(mode_frame, textvariable=self.mode_hint_var, style="Subtitle.TLabel").pack(anchor="w", pady=(8, 0))

        control_frame = ttk.Frame(container)
        control_frame.pack(fill=tk.X, pady=(0, 12))

        self.preview_button = ttk.Button(control_frame, text="Start Preview", command=self.toggle_preview)
        self.preview_button.pack(side=tk.LEFT)

        self.start_button = ttk.Button(control_frame, text="Start Live Decode", command=self.start_listening)
        self.start_button.pack(side=tk.LEFT, padx=(10, 0))

        self.stop_button = ttk.Button(control_frame, text="Stop Live", command=self.stop_and_decode)
        self.stop_button.pack(side=tk.LEFT, padx=(8, 0))

        ttk.Button(control_frame, text="Decode File", command=self.decode_file).pack(side=tk.LEFT, padx=(18, 0))
        ttk.Button(control_frame, text="Clear", command=self.clear_output).pack(side=tk.LEFT, padx=(8, 0))

        output_frame = ttk.LabelFrame(container, text="Decoded Text", padding=12)
        output_frame.pack(fill=tk.BOTH, expand=True)

        self.output = tk.Text(
            output_frame,
            height=14,
            wrap=tk.WORD,
            font=("Segoe UI", 12),
            background="#1a1d24",
            foreground="#f2f2f2",
            insertbackground="#f2f2f2",
            selectbackground="#345",
            relief=tk.FLAT,
            borderwidth=0,
        )
        self.output.pack(fill=tk.BOTH, expand=True)
        self.output.insert("1.0", "Decoded text will appear here.\n")
        self.output.configure(state=tk.DISABLED)

        ttk.Separator(container).pack(fill=tk.X, pady=(10, 8))
        ttk.Label(container, textvariable=self.status_var).pack(anchor="w")

    def _backend_note(self) -> str:
        if sounddevice_available():
            return "Audio backend: sounddevice / PortAudio"
        return "Audio backend: preview/live decode need sounddevice. File decode can still work."

    def refresh_devices(self) -> None:
        devices = list_audio_devices("input", advanced=self.advanced_var.get(), samplerate=self.settings.sample_rate)
        values: list[str] = ["System default input"]
        self.device_map = {"System default input": None}

        for device in devices:
            label = device.label()
            values.append(label)
            self.device_map[label] = device.id

        self.input_combo["values"] = values
        self.input_combo.set("System default input")

        if len(values) == 1:
            self.status_var.set("No selectable input devices were found. System default will be used.")
        else:
            self.status_var.set(f"Found {len(values) - 1} input device(s).")

    def _selected_device(self) -> int | None:
        return self.device_map.get(self.input_device_var.get())

    def clear_output(self) -> None:
        self.output.configure(state=tk.NORMAL)
        self.output.delete("1.0", tk.END)
        self.output.insert("1.0", "Decoded text will appear here.\n")
        self.output.configure(state=tk.DISABLED)
        self._current_output = ""
        self._last_live_text = ""

    def _set_status(self, text: str) -> None:
        self.root.after(0, lambda: self.status_var.set(text))

    def _set_output(self, text: str) -> None:
        def apply() -> None:
            self.output.configure(state=tk.NORMAL)
            self.output.delete("1.0", tk.END)
            self.output.insert("1.0", text)
            self.output.configure(state=tk.DISABLED)
            self._current_output = text

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
        else:
            self.meter["value"] = 0.0
            self.level_text_var.set("Mic level: idle")

        self.root.after(80, self._schedule_meter_update)


    def _schedule_waveform_update(self) -> None:
        if self.preview_active or self.listening_active:
            label = "Preview running." if self.preview_active else "Listening..."
            self.waveform.draw(self._latest_block, label)
        else:
            self.waveform.draw(None, "Preview is off.")
        self.root.after(80, self._schedule_waveform_update)

    def _sync_mode_ui(self) -> None:
        live_mode = self.live_mode_var.get()
        if live_mode:
            self.mode_hint_var.set("Live decode is enabled.")
            self.start_button.configure(text="Start Live Decode")
            self.stop_button.configure(text="Stop Live")
        else:
            self.mode_hint_var.set("Manual record is enabled.")
            self.start_button.configure(text="Start Recording")
            self.stop_button.configure(text="Stop and Decode")

        if self.listening_active:
            self.start_button.configure(state="disabled")
            self.stop_button.configure(state="normal")
        else:
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")

    def open_settings(self) -> None:
        updated = SettingsDialog(self.root, "Receiver Settings", self.settings, RECEIVER_FIELDS).show()
        if updated is None:
            return
        self.settings = clamp_settings(updated)
        self.backend_var.set(self._backend_note())
        self.refresh_devices()
        self.status_var.set("Settings updated.")

    def toggle_preview(self) -> None:
        if self.preview_active:
            self.stop_preview()
        else:
            self.start_preview()

    def _make_input_callback(self, *, store_audio: bool):
        def callback(indata, frames, time, status):  # noqa: ANN001
            del frames, time
            if status:
                pass
            chunk = indata.copy().reshape(-1).astype(np.float32, copy=False)
            if chunk.size == 0:
                return

            # Light denoise: keep a gentle floor, but preserve the waveform.
            chunk = np.nan_to_num(chunk, copy=False)
            peak = float(np.max(np.abs(chunk)))
            rms = float(np.sqrt(np.mean(np.square(chunk))))
            self._set_meter(rms, peak)
            self._latest_block = chunk[-min(chunk.size, 2048):].copy()

            if store_audio:
                with self._capture_lock:
                    self._captured_chunks.append(chunk)
                    self._captured_samples += int(chunk.size)
                    max_samples = int(self.settings.live_buffer_seconds * self.settings.sample_rate)
                    while self._captured_samples > max_samples and self._captured_chunks:
                        first = self._captured_chunks[0]
                        if self._captured_samples - first.size >= max_samples:
                            self._captured_samples -= int(first.size)
                            self._captured_chunks.pop(0)
                        else:
                            trim = self._captured_samples - max_samples
                            if trim > 0:
                                self._captured_chunks[0] = first[trim:]
                                self._captured_samples -= trim
                            break

        return callback

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

        device_id = self._selected_device()
        self.selected_device_id = device_id

        try:
            self._preview_stream = create_input_stream(
                samplerate=self.settings.sample_rate,
                device=device_id,
                callback=self._make_input_callback(store_audio=False),
            )
            self._preview_stream.start()
        except AudioBackendError as exc:
            messagebox.showerror("Preview error", str(exc), parent=self.root)
            return

        self.preview_active = True
        self.preview_button.configure(text="Stop Preview")
        self.status_var.set("Preview running. Speak into the selected microphone.")
        self._sync_mode_ui()

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

        self.preview_button.configure(text="Start Preview")
        self.waveform.clear()
        self.status_var.set("Preview stopped.")
        self._sync_mode_ui()

    def _start_capture(self) -> str:
        self.selected_device_id = self._selected_device()
        self._captured_chunks = []
        self._captured_samples = 0
        self._last_live_text = ""

        if sounddevice_available():
            self._capture_stream = create_input_stream(
                samplerate=self.settings.sample_rate,
                device=self.selected_device_id,
                callback=self._make_input_callback(store_audio=True),
            )
            self._capture_stream.start()
            self.recorder = None
            return "sounddevice"

        if self.live_mode_var.get():
            raise AudioBackendError("Live decode needs sounddevice / PortAudio. File decode still works without it.")

        self.recorder = Recorder(samplerate=self.settings.sample_rate, device=self.selected_device_id)
        self.recorder.start()
        self._capture_stream = None
        return self.recorder.mode

    def start_listening(self) -> None:
        if self.listening_active:
            return

        if self.preview_active:
            self.stop_preview()

        try:
            backend_name = self._start_capture()
        except Exception as exc:
            messagebox.showerror("Record error", str(exc), parent=self.root)
            return

        self.listening_active = True
        self._sync_mode_ui()

        if self.live_mode_var.get():
            self.status_var.set(f"Listening with live decode. Backend: {backend_name}.")
            self._schedule_live_decode()
        else:
            self.status_var.set(f"Recording... Backend: {backend_name}. Press Stop and Decode when done.")

    def _snapshot_audio(self) -> np.ndarray:
        with self._capture_lock:
            if not self._captured_chunks:
                return np.empty(0, dtype=np.float32)
            return np.concatenate(self._captured_chunks, axis=0).astype(np.float32, copy=False)

    def _schedule_live_decode(self) -> None:
        if not self.listening_active or not self.live_mode_var.get():
            return
        if self._decode_thread_running:
            self.root.after(220, self._schedule_live_decode)
            return

        audio = self._snapshot_audio()
        if audio.size < self.settings.sample_rate // 2:
            self.root.after(220, self._schedule_live_decode)
            return

        self._decode_thread_running = True

        def worker(snapshot: np.ndarray) -> None:
            try:
                text, error = decode_audio_to_text(snapshot, self.settings)
                if text is not None:
                    if text != self._last_live_text:
                        self._last_live_text = text
                        self._set_output(text)
                        self._set_status(
                            f"Live decode locked — {summarize_audio_length(snapshot, self.settings.sample_rate)} captured."
                        )
                else:
                    # Keep the UI calm; only surface unexpected failures.
                    if "sync" not in error.lower() and "frame" not in error.lower() and "crc" not in error.lower():
                        self._set_status(f"Listening... {error}")
            finally:
                self._decode_thread_running = False
                if self.listening_active and self.live_mode_var.get():
                    self.root.after(220, self._schedule_live_decode)

        threading.Thread(target=worker, args=(audio,), daemon=True).start()

    def stop_and_decode(self) -> None:
        if not self.listening_active:
            messagebox.showinfo("Not listening", "Press Start first.", parent=self.root)
            return

        self.listening_active = False
        self._sync_mode_ui()
        self.status_var.set("Stopping capture and decoding...")

        def worker() -> None:
            try:
                if self._capture_stream is not None:
                    try:
                        self._capture_stream.stop()
                        self._capture_stream.close()
                    finally:
                        self._capture_stream = None
                    audio = self._snapshot_audio()
                elif self.recorder is not None:
                    audio = self.recorder.stop()
                else:
                    audio = np.empty(0, dtype=np.float32)

                self.recorder = None

                if audio.size == 0:
                    raise RuntimeError("No audio was recorded.")

                text, error = decode_audio_to_text(audio, self.settings)
                if text is None:
                    raise RuntimeError(error)

                self._set_output(text)
                self._set_status(f"Decode successful — {summarize_audio_length(audio, self.settings.sample_rate)} captured.")
            except Exception as exc:
                err = str(exc)
                self._set_status("Decode failed.")
                self.root.after(0, lambda msg=err: messagebox.showerror("Decode error", msg, parent=self.root))
            finally:
                self.root.after(0, lambda: self._sync_mode_ui())

        threading.Thread(target=worker, daemon=True).start()

    def decode_file(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Open audio file",
            filetypes=[("WAV audio", "*.wav")],
        )
        if not path:
            return

        self.status_var.set("Decoding WAV file...")

        def worker(file_path: str) -> None:
            try:
                audio = read_wav_file(file_path)
                text, error = decode_audio_to_text(audio, self.settings)
                if text is None:
                    raise RuntimeError(error)
                self._set_output(text)
                self._set_status(f"Decoded file successfully — {summarize_audio_length(audio, self.settings.sample_rate)}.")
            except Exception as exc:
                err = str(exc)
                self._set_status("File decode failed.")
                self.root.after(0, lambda msg=err: messagebox.showerror("Decode error", msg, parent=self.root))

        threading.Thread(target=worker, args=(path,), daemon=True).start()


if __name__ == "__main__":
    root = tk.Tk()
    ReceiverApp(root)
    root.mainloop()
