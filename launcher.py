from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk

ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable


def launch(script_name: str) -> None:
    script = ROOT / script_name
    if not script.exists():
        return
    subprocess.Popen([PYTHON, str(script)], cwd=str(ROOT))


root = tk.Tk()
root.title("Audio Modem")
root.geometry("420x260")
root.resizable(False, False)

style = ttk.Style()
try:
    style.theme_use("clam")
except Exception:
    pass
style.configure("Title.TLabel", font=("Arial", 18, "bold"))
style.configure("Subtitle.TLabel", font=("Arial", 10))
style.configure("TButton", padding=(12, 8))

frame = ttk.Frame(root, padding=18)
frame.pack(fill=tk.BOTH, expand=True)

ttk.Label(frame, text="Audio Modem", style="Title.TLabel").pack(anchor="center", pady=(0, 6))
ttk.Label(
    frame,
    text="Choose a mode. Everything stays local.",
    style="Subtitle.TLabel",
).pack(anchor="center", pady=(0, 18))

ttk.Button(frame, text="Text to Voice", command=lambda: launch("sender.py")).pack(fill=tk.X, pady=6)
ttk.Button(frame, text="Voice to Text", command=lambda: launch("receiver.py")).pack(fill=tk.X, pady=6)

ttk.Label(frame, text="Tip: device selection appears when sounddevice/PortAudio is available.", style="Subtitle.TLabel").pack(
    anchor="center", pady=(18, 0)
)

root.mainloop()
