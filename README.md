# Audio Modem (simple prototype)

A tiny local-only text ↔ audio demo.

## Files
- `launcher.py` — menu window
- `sender.py` — text → voice
- `receiver.py` — voice → text
- `common.py` — shared modem logic
- `audio_backend.py` — playback/recording backends
- `run.sh` — Linux/macOS launcher
- `run.bat` — Windows launcher

## Notes
- Uses `numpy`.
- `sounddevice` is optional now.
- On Linux, if `sounddevice` fails because PortAudio is missing, the app falls back to `ffmpeg/ffplay` when available.
- It is intentionally simple, not production-grade.

## Run
### Linux/macOS
```bash
chmod +x run.sh
./run.sh
```

### Windows
Double-click `run.bat` or run it from Command Prompt.
