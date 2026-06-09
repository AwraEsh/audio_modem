# Audio Modem

A small local-only text ↔ voice demo built with Python, Tkinter, and a simple FSK modem.

## Notes
- `sounddevice` + PortAudio are required for live preview and live decode.
- On Linux, playback/recording can fall back to `ffplay` / `ffmpeg` when available.
- The receiver has two modes:
  - **Live decode**: the capture stays open and decodes while audio is coming in.
  - **Manual record**: record first, then decode when you stop.

## Run
- Linux/macOS: `./run.sh`
- Windows: `run.bat`
