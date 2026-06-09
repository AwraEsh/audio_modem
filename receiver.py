from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext

import numpy as np
import sounddevice as sd

from common import audio_to_bits, parse_frame_bits, summarize_audio_length


class ReceiverApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Audio Modem — Voice → Text")
        self.root.geometry("720x520")

        self.status_var = tk.StringVar(value="Start listening, then transmit from the other side.")
        self.recording = False
        self.stream: sd.InputStream | None = None
        self.frames: list[np.ndarray] = []
        self.lock = threading.Lock()

        tk.Label(root, text="Voice to Text", font=("Arial", 18, "bold")).pack(pady=(12, 6))
        tk.Label(
            root,
            text=(
                "روی Start listening بزن، بعد سمت فرستنده را اجرا کن. وقتی پیام تمام شد روی Stop and Decode بزن.\n"
                "این نسخه ساده است و همه‌چیز لوکال انجام می‌شود."
            ),
            wraplength=680,
            justify="center",
        ).pack(pady=(0, 10))

        button_row = tk.Frame(root)
        button_row.pack(pady=8)
        tk.Button(button_row, text="Start listening", width=16, command=self.start_listening).pack(side=tk.LEFT, padx=6)
        tk.Button(button_row, text="Stop and decode", width=16, command=self.stop_and_decode).pack(side=tk.LEFT, padx=6)
        tk.Button(button_row, text="Clear", width=10, command=self.clear_output).pack(side=tk.LEFT, padx=6)

        self.output = scrolledtext.ScrolledText(root, height=14, wrap=tk.WORD, font=("Arial", 12))
        self.output.pack(fill=tk.BOTH, expand=True, padx=12, pady=(8, 8))
        self.output.insert("1.0", "Decoded text will appear here.\n")
        self.output.configure(state=tk.DISABLED)

        tk.Label(root, textvariable=self.status_var, anchor="w", justify="left").pack(fill=tk.X, padx=12, pady=(4, 12))

    def clear_output(self) -> None:
        self.output.configure(state=tk.NORMAL)
        self.output.delete("1.0", tk.END)
        self.output.insert("1.0", "Decoded text will appear here.\n")
        self.output.configure(state=tk.DISABLED)

    def _callback(self, indata, frames, time, status):  # noqa: ANN001
        if status:
            # Keep collecting; sounddevice may report overflow warnings.
            pass
        with self.lock:
            self.frames.append(indata.copy())

    def start_listening(self) -> None:
        if self.recording:
            return
        try:
            self.frames = []
            self.stream = sd.InputStream(channels=1, samplerate=44100, callback=self._callback)
            self.stream.start()
            self.recording = True
            self.status_var.set("در حال ضبط... حالا از سمت فرستنده ارسال کن.")
        except Exception as exc:  # pragma: no cover
            messagebox.showerror("Record error", f"{exc}\n\nاگر microphone access یا sound backend مشکل دارد، اول آن را درست کن.")

    def stop_and_decode(self) -> None:
        if not self.recording:
            messagebox.showinfo("Not recording", "اول Start listening را بزن.")
            return

        self.recording = False
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

        self.status_var.set("در حال decode...")
        self.root.update_idletasks()

        def worker() -> None:
            try:
                with self.lock:
                    if not self.frames:
                        raise RuntimeError("هیچ صدایی ضبط نشد.")
                    audio = np.concatenate(self.frames, axis=0).reshape(-1)

                bits = audio_to_bits(audio)
                payload, err = parse_frame_bits(bits)
                if err:
                    raise RuntimeError(err)
                text = payload.decode("utf-8", errors="replace")

                self.output.configure(state=tk.NORMAL)
                self.output.delete("1.0", tk.END)
                self.output.insert("1.0", text)
                self.output.configure(state=tk.DISABLED)

                self.status_var.set(
                    f"Decode successful — recorded {summarize_audio_length(audio)}. پیام بالا باز شد."
                )
            except Exception as exc:  # pragma: no cover
                self.status_var.set("Decode failed.")
                messagebox.showerror("Decode error", f"{exc}")

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    root = tk.Tk()
    app = ReceiverApp(root)
    root.mainloop()
