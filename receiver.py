from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from audio_backend import (
    AudioBackendError,
    Recorder,
    list_input_devices,
    sounddevice_available,
)
from common import audio_to_bits, parse_frame_bits, summarize_audio_length


class ReceiverApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Audio Modem — Voice to Text")
        self.root.geometry("820x620")
        self.root.minsize(760, 560)

        self._style_ui()

        self.recording = False
        self.recorder: Recorder | None = None
        self.device_map: dict[str, int] = {}
        self.selected_device_id: int | None = None

        self.status_var = tk.StringVar(value="Select an input device, press Start Listening, then transmit from the other side.")
        self.backend_note_var = tk.StringVar(value=self._backend_note())

        container = ttk.Frame(root, padding=16)
        container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(container, text="Voice to Text", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            container,
            text="Records audio locally, decodes it, and verifies the frame with CRC.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(4, 12))

        device_frame = ttk.LabelFrame(container, text="Input Device", padding=12)
        device_frame.pack(fill=tk.X, pady=(0, 12))
        self.input_device_var = tk.StringVar()
        self.input_combo = ttk.Combobox(device_frame, textvariable=self.input_device_var, state="readonly")
        self.input_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.refresh_button = ttk.Button(device_frame, text="Refresh", command=self.refresh_devices)
        self.refresh_button.pack(side=tk.LEFT, padx=(8, 0))

        control_frame = ttk.Frame(container)
        control_frame.pack(fill=tk.X, pady=(0, 12))
        self.start_button = ttk.Button(control_frame, text="Start Listening", command=self.start_listening)
        self.start_button.pack(side=tk.LEFT)
        self.stop_button = ttk.Button(control_frame, text="Stop and Decode", command=self.stop_and_decode, state="disabled")
        self.stop_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(control_frame, text="Clear", command=self.clear_output).pack(side=tk.LEFT, padx=(8, 0))

        output_frame = ttk.LabelFrame(container, text="Decoded Text", padding=12)
        output_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 12))
        self.output = scrolledtext.ScrolledText(output_frame, height=16, wrap=tk.WORD, font=("Arial", 12))
        self.output.pack(fill=tk.BOTH, expand=True)
        self.output.insert("1.0", "Decoded text will appear here.\n")
        self.output.configure(state=tk.DISABLED)

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
        devices = list_input_devices()
        if not devices:
            self.device_map = {}
            self.input_combo["values"] = ["System default input"]
            self.input_combo.current(0)
            self.input_combo.configure(state="disabled")
            self.selected_device_id = None
            self.refresh_button.configure(state="disabled")
            self.status_var.set("No selectable input devices were found. Using the default input backend.")
            return

        values: list[str] = ["System default input"]
        self.device_map = {"System default input": None}
        for device in devices:
            label = device.label()
            values.append(label)
            self.device_map[label] = device.id

        self.input_combo.configure(state="readonly")
        self.input_combo["values"] = values
        self.input_combo.set("System default input")
        self.selected_device_id = None
        self.refresh_button.configure(state="normal")
        self.status_var.set(f"Found {len(devices)} input device(s).")

    def clear_output(self) -> None:
        self.output.configure(state=tk.NORMAL)
        self.output.delete("1.0", tk.END)
        self.output.insert("1.0", "Decoded text will appear here.\n")
        self.output.configure(state=tk.DISABLED)

    def _set_status(self, text: str) -> None:
        self.root.after(0, lambda: self.status_var.set(text))

    def _show_error(self, title: str, text: str) -> None:
        self.root.after(0, lambda: messagebox.showerror(title, text, parent=self.root))

    def start_listening(self) -> None:
        if self.recording:
            return
        chosen = self.input_device_var.get().strip()
        self.selected_device_id = self.device_map.get(chosen)
        try:
            self.recorder = Recorder(device=self.selected_device_id)
            self.recorder.start()
            self.recording = True
            self.start_button.configure(state="disabled")
            self.stop_button.configure(state="normal")
            self.refresh_button.configure(state="disabled")
            self.status_var.set(f"Recording... backend={self.recorder.mode}. Now send from the transmitter.")
        except AudioBackendError as exc:
            messagebox.showerror(
                "Record error",
                f"{exc}\n\nIf sounddevice is unavailable, Linux recording falls back to ffmpeg when installed.",
                parent=self.root,
            )
        except Exception as exc:  # pragma: no cover
            messagebox.showerror("Record error", str(exc), parent=self.root)

    def stop_and_decode(self) -> None:
        if not self.recording or self.recorder is None:
            messagebox.showinfo("Not recording", "Press Start Listening first.", parent=self.root)
            return

        self.recording = False
        recorder = self.recorder
        self.recorder = None
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="disabled")
        self.refresh_button.configure(state="disabled")
        self.status_var.set("Decoding...")

        def worker() -> None:
            try:
                audio = recorder.stop()
                if audio.size == 0:
                    raise RuntimeError("No audio was recorded.")

                bits = audio_to_bits(audio)
                payload, err = parse_frame_bits(bits)
                if err:
                    raise RuntimeError(err)
                text = payload.decode("utf-8", errors="replace")

                def update_output() -> None:
                    self.output.configure(state=tk.NORMAL)
                    self.output.delete("1.0", tk.END)
                    self.output.insert("1.0", text)
                    self.output.configure(state=tk.DISABLED)

                self.root.after(0, update_output)
                self._set_status(
                    f"Decode successful — recorded {summarize_audio_length(audio)}. Backend used: {recorder.mode}."
                )
            except Exception as exc:  # pragma: no cover
                self._set_status("Decode failed.")
                self._show_error("Decode error", str(exc))
            finally:
                self.root.after(0, lambda: self.start_button.configure(state="normal"))
                self.root.after(0, lambda: self.stop_button.configure(state="disabled"))
                self.root.after(0, lambda: self.refresh_button.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    root = tk.Tk()
    app = ReceiverApp(root)
    root.mainloop()
