from __future__ import annotations

import subprocess
import sys
import tkinter as tk
from tkinter import messagebox
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable


def launch(script_name: str) -> None:
    script = ROOT / script_name
    if not script.exists():
        messagebox.showerror("Missing file", f"{script_name} not found.")
        return
    try:
        subprocess.Popen([PYTHON, str(script)], cwd=str(ROOT))
    except Exception as exc:  # pragma: no cover
        messagebox.showerror("Launch failed", str(exc))


root = tk.Tk()
root.title("Audio Modem Launcher")
root.geometry("360x200")
root.resizable(False, False)

frame = tk.Frame(root, padx=18, pady=18)
frame.pack(fill=tk.BOTH, expand=True)

tk.Label(frame, text="Audio Modem", font=("Arial", 18, "bold")).pack(pady=(0, 10))
tk.Label(frame, text="Choose a mode:", font=("Arial", 11)).pack(pady=(0, 12))

tk.Button(frame, text="Text → Voice", width=18, command=lambda: launch("sender.py")).pack(pady=4)
tk.Button(frame, text="Voice → Text", width=18, command=lambda: launch("receiver.py")).pack(pady=4)

tk.Label(frame, text="Everything stays local.", font=("Arial", 9)).pack(pady=(14, 0))

root.mainloop()
