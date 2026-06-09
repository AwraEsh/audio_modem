# Audio Modem (simple prototype)

A tiny local-only text ↔ audio demo.

## Files
- `launcher.py` — menu window
- `sender.py` — text → voice
- `receiver.py` — voice → text
- `common.py` — shared modem logic
- `run.sh` — Linux/macOS launcher
- `run.bat` — Windows launcher

## Notes
- Uses `numpy` and `sounddevice`.
- It is intentionally simple, not production-grade.
- On Linux, `tkinter` and audio backend packages may need to be installed by the system.

## Run
### Linux/macOS
```bash
chmod +x run.sh
./run.sh
```

### Windows
Double-click `run.bat` or run it from Command Prompt.
