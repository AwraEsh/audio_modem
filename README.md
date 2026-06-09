# Audio Modem

A small local-only text ↔ audio demo with a clean dark UI.

## Files
- `launcher.py` — mode chooser
- `sender.py` — text → voice
- `receiver.py` — voice → text
- `common.py` — modulation and decoding logic
- `audio_backend.py` — device enumeration and playback/recording backends
- `ui_theme.py` — dark theme helper
- `run.sh` — Linux/macOS launcher
- `run.bat` — Windows launcher

## Features
- Dark UI by default
- English-only UI strings
- Clean device list with an optional advanced view
- Output device selection in the sender
- Input device selection in the receiver
- Microphone preview with live level meter
- Optional live decode while listening
- Local-only processing
- CRC-protected frames for better stability
- Safe error handling instead of crashing on bad devices

## Notes
- Live preview and live decode need `sounddevice` plus PortAudio.
- On Linux, the launcher tries common system packages when possible.
- `tkinter` must exist in the system Python installation.

## Run
### Linux/macOS
```bash
chmod +x run.sh
./run.sh
```

### Windows
Double-click `run.bat` or run it from Command Prompt.
