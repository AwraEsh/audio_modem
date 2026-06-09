from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext

from audio_backend import AudioBackendError, play_audio
from common import SAMPLE_RATE, build_frame_bits, bits_to_audio, text_to_payload


class SenderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Audio Modem — Text → Voice")
        self.root.geometry("640x420")

        self.status_var = tk.StringVar(value="write a text and hit that transmit kilid")

        tk.Label(root, text="Text to Voice", font=("Arial", 18, "bold")).pack(pady=(12, 6))
        tk.Label(
            root,
            text="i transmit the text with UTF8 to voice and the reciver should use Voice → Text",
            wraplength=600,
            justify="center",
        ).pack(pady=(0, 10))

        self.text_box = scrolledtext.ScrolledText(root, height=12, wrap=tk.WORD, font=("Arial", 12))
        self.text_box.pack(fill=tk.BOTH, expand=True, padx=12)
        self.text_box.insert("1.0", "Hello from Arash")

        button_row = tk.Frame(root)
        button_row.pack(pady=10)
        tk.Button(button_row, text="Transmit", width=14, command=self.transmit).pack(side=tk.LEFT, padx=6)
        tk.Button(button_row, text="Clear", width=12, command=self.clear).pack(side=tk.LEFT, padx=6)

        tk.Label(root, textvariable=self.status_var, anchor="w", justify="left").pack(fill=tk.X, padx=12, pady=(4, 12))

    def clear(self) -> None:
        self.text_box.delete("1.0", tk.END)

    def transmit(self) -> None:
        text = self.text_box.get("1.0", tk.END).rstrip("\n")
        if not text.strip():
            messagebox.showwarning("Empty text", "dud just write somthin first 😭")
            return

        self.status_var.set("im cooking the signal...")
        self.root.update_idletasks()

        try:
            payload = text_to_payload(text)
            bits = build_frame_bits(payload)
            audio = bits_to_audio(bits)
        except Exception as exc:  # pragma: no cover
            messagebox.showerror("Build failed", str(exc))
            return

        def worker() -> None:
            try:
                self.status_var.set(
                    f"playing {len(payload)} bytes of data. connect the speaker or the AUX cable"
                )
                backend = play_audio(audio, samplerate=SAMPLE_RATE)
                self.status_var.set(f"end of sending. backend={backend}. that other dude should recive the message now.")
            except AudioBackendError as exc:
                self.status_var.set("i coudnt play the sound.")
                messagebox.showerror(
                    "Playback error",
                    f"{exc}\n\nif u dont have this on linux : sounddevice ، ffplay should be installed."
                )
            except Exception as exc:  # pragma: no cover
                self.status_var.set("i coudnt play the sound.")
                messagebox.showerror("Playback error", str(exc))

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    root = tk.Tk()
    app = SenderApp(root)
    root.mainloop()
