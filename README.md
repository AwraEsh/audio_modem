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

## ScreenShots

the launcher:

<img width="642" height="479" alt="image" src="https://github.com/user-attachments/assets/2e230deb-b4e9-41d8-98a9-8043817c769b" />

sender

<img width="962" height="973" alt="image" src="https://github.com/user-attachments/assets/58cf9726-e1e4-4be8-b0a0-9f4127d4337f" />

reciver

<img width="1082" height="963" alt="image" src="https://github.com/user-attachments/assets/e134bc9f-7eed-46bf-854c-3cf4d424f236" />



## Notes

- The live microphone features need `sounddevice` and PortAudio.
- The app can still decode WAV files even if live input is unavailable.
- Use the same modem settings on both sender and receiver.



Enjoy!
