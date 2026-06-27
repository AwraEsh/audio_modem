from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from ui_theme import configure_dark_theme

ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable

# defs
def launch(script_name: str) -> None:
    script = ROOT / script_name
    if script.exists():
        subprocess.Popen([PYTHON, str(script)], cwd=str(ROOT))


def main() -> None:
    root = tk.Tk()
    root.title("Audio Modem")
    root.geometry("520x320")
    root.resizable(False, False)

    configure_dark_theme(root)

    frame = ttk.Frame(root, padding=18)
    frame.pack(fill=tk.BOTH, expand=True)

    ttk.Label(frame, text="Audio Modem", style="Title.TLabel").pack(anchor="center", pady=(0, 8))
    ttk.Label(frame, text="Choose a mode. Everything stays local.", style="Subtitle.TLabel").pack(anchor="center")

    ttk.Button(frame, text="Text to Voice", command=lambda: launch("sender.py")).pack(fill=tk.X, pady=(24, 8))
    ttk.Button(frame, text="Voice to Text", command=lambda: launch("receiver.py")).pack(fill=tk.X, pady=8)

    ttk.Label(
        frame,
        text="Tip: use the same settings on both sides for the cleanest sync.\n\nMade by AwraEsh with Python and Tkinter.",
        style="Subtitle.TLabel",
        wraplength=450,
        justify="center",
    ).pack(anchor="center", pady=(20, 0))

    root.mainloop()


if __name__ == "__main__":
    main()
