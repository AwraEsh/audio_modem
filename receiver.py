from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext

import numpy as np

from audio_backend import AudioBackendError, Recorder
from common import audio_to_bits, parse_frame_bits, summarize_audio_length


class ReceiverApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Audio Modem — Voice → Text")
        self.root.geometry("720x520")

        self.status_var = tk.StringVar(value="Start listening, then transmit from the other side.")
        self.recording = False
        self.recorder: Recorder | None = None

        tk.Label(root, text="Voice to Text", font=("Arial", 18, "bold")).pack(pady=(12, 6))
        tk.Label(
            root,
            text=(
                "click the start lis.. shit and when the message endedm that that end of somshit butt.\n"
                "this shi is local and simple."
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

    def start_listening(self) -> None:
        if self.recording:
            return
        try:
            self.recorder = Recorder()
            self.recorder.start()
            self.recording = True
            self.status_var.set(f"recording... backend={self.recorder.mode}. now run it from the sender side.")
        except AudioBackendError as exc:
            messagebox.showerror(
                "Record error",
                f"{exc}\n\nروی لینوکس، اگر sounddevice کار نکند، ffmpeg باید بتواند از میکروفون پیش‌فرض ضبط کند."
            )
        except Exception as exc:  # pragma: no cover
            messagebox.showerror("Record error", str(exc))

    def stop_and_decode(self) -> None:
        if not self.recording or self.recorder is None:
            messagebox.showinfo("Not recording", "first click the Start listening botton")
            return

        self.recording = False
        recorder = self.recorder
        self.recorder = None

        self.status_var.set(" decoding....")
        self.root.update_idletasks()

        def worker() -> None:
            try:
                audio = recorder.stop()
                if audio.size == 0:
                    raise RuntimeError("no sound has recorded bitch.")

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
                    f"Decode successful — recorded {summarize_audio_length(audio)}. backend={recorder.mode}."
                )
            except Exception as exc:  # pragma: no cover
                self.status_var.set("Decode failed.")
                messagebox.showerror("Decode error", f"{exc}")

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    root = tk.Tk()
    app = ReceiverApp(root)
    root.mainloop()
