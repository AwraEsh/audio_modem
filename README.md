# Audio Modem

A tiny local-only text ↔ audio demo with a simple GUI.

## Files
- `launcher.py` — mode chooser
- `sender.py` — text → voice
- `receiver.py` — voice → text
- `common.py` — shared modem logic
- `audio_backend.py` — playback/recording backends and device enumeration
- `run.sh` — Linux/macOS launcher
- `run.bat` — Windows launcher

## Features
- English-only UI text
- Optional input/output device selection
- Local-only processing
- CRC-protected frames for more stable decoding
- Fallback playback/recording paths when `sounddevice` is unavailable

## Notes
- `sounddevice` needs PortAudio.
- On Linux, if PortAudio is missing, install the system package for it and rerun the app.
- `tkinter` must be available in the system Python installation.

## Run
### Linux/macOS
```bash
chmod +x run.sh
./run.sh
```

### Windows
Double-click `run.bat` or run it from Command Prompt.
