# Audio Modem

A small local text ↔ audio modem built with Tkinter, NumPy, and SoundDevice.

## Features

- Text to WAV / speaker output
- WAV / microphone to text
- Dark-mode UI
- Output and input device selection
- Settings popups with short explanations
- Live preview for the selected microphone
- Live decode mode or manual record mode
- Save the generated waveform as a WAV file
- Decode from an audio file

## Run

### Linux
open a terminal on projects folder than:
```bash
sudo chmod +x .
```
than
```bash
./run.sh
```

### Windows
```bat
run.bat
```

## Notes

- The live microphone features need `sounddevice` and PortAudio.
- The app can still decode WAV files even if live input is unavailable.
- Use the same modem settings on both sender and receiver.



Enjoy!