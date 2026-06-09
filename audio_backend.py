from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

SAMPLE_RATE = 44100


class AudioBackendError(RuntimeError):
    pass


def _audio_to_int16(audio: np.ndarray) -> np.ndarray:
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)
    audio = np.clip(audio, -1.0, 1.0)
    return (audio * 32767.0).astype(np.int16)


def write_wav(path: str | Path, audio: np.ndarray, samplerate: int = SAMPLE_RATE) -> None:
    path = str(path)
    data = _audio_to_int16(audio)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(samplerate)
        wf.writeframes(data.tobytes())


def read_wav(path: str | Path) -> np.ndarray:
    path = str(path)
    with wave.open(path, "rb") as wf:
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())

    if sampwidth != 2:
        raise AudioBackendError(f"Unsupported sample width: {sampwidth * 8} bit")

    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32767.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return audio


def _have_sounddevice() -> bool:
    try:
        import sounddevice as _sd  # noqa: F401
        return True
    except Exception:
        return False


@dataclass
class Recorder:
    samplerate: int = SAMPLE_RATE

    def __post_init__(self) -> None:
        self._mode: str = ""
        self._sd = None
        self._stream = None
        self._frames: list[np.ndarray] = []
        self._proc: subprocess.Popen[str] | None = None
        self._temp_path: Path | None = None
        self._choose_backend()

    def _choose_backend(self) -> None:
        if _have_sounddevice():
            import sounddevice as sd

            self._mode = "sounddevice"
            self._sd = sd
            return

        if sys.platform.startswith("linux") and shutil.which("ffmpeg"):
            self._mode = "ffmpeg"
            return

        raise AudioBackendError(
            "No usable recording backend found. Install sounddevice with PortAudio, or use Linux with ffmpeg."
        )

    @property
    def mode(self) -> str:
        return self._mode

    def start(self) -> None:
        if self._mode == "sounddevice":
            self._frames = []

            def _callback(indata, frames, time, status):  # noqa: ANN001
                if status:
                    pass
                self._frames.append(indata.copy())

            self._stream = self._sd.InputStream(channels=1, samplerate=self.samplerate, callback=_callback)
            self._stream.start()
            return

        if self._mode == "ffmpeg":
            fd, temp_name = tempfile.mkstemp(suffix=".wav", prefix="audio_modem_rec_")
            os.close(fd)
            self._temp_path = Path(temp_name)

            # Prefer PulseAudio / PipeWire. If that fails, the process will later fail and we can report it.
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "pulse",
                "-i",
                "default",
                "-ac",
                "1",
                "-ar",
                str(self.samplerate),
                str(self._temp_path),
            ]
            self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return

        raise AudioBackendError(f"Unsupported recording backend: {self._mode}")

    def stop(self) -> np.ndarray:
        if self._mode == "sounddevice":
            if self._stream is None:
                return np.empty(0, dtype=np.float32)
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None
            if not self._frames:
                return np.empty(0, dtype=np.float32)
            return np.concatenate(self._frames, axis=0).reshape(-1).astype(np.float32)

        if self._mode == "ffmpeg":
            if self._proc is None or self._temp_path is None:
                return np.empty(0, dtype=np.float32)
            try:
                try:
                    self._proc.send_signal(signal.SIGINT)
                except Exception:
                    self._proc.terminate()
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=5)
            finally:
                self._proc = None

            if not self._temp_path.exists() or self._temp_path.stat().st_size == 0:
                path = self._temp_path
                self._temp_path = None
                raise AudioBackendError(
                    "Recording backend did not produce audio. On Linux, ffmpeg needs access to your default microphone source."
                )

            audio = read_wav(self._temp_path)
            try:
                self._temp_path.unlink(missing_ok=True)
            finally:
                self._temp_path = None
            return audio

        raise AudioBackendError(f"Unsupported recording backend: {self._mode}")


def play_audio(audio: np.ndarray, samplerate: int = SAMPLE_RATE) -> str:
    if _have_sounddevice():
        import sounddevice as sd

        sd.play(audio, samplerate=samplerate, blocking=True)
        return "sounddevice"

    if sys.platform.startswith("linux"):
        if shutil.which("ffplay"):
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                temp_path = Path(tmp.name)
            try:
                write_wav(temp_path, audio, samplerate=samplerate)
                subprocess.run(
                    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error", str(temp_path)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return "ffplay"
            finally:
                temp_path.unlink(missing_ok=True)

    if sys.platform.startswith("win"):
        try:
            import winsound

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                temp_path = Path(tmp.name)
            try:
                write_wav(temp_path, audio, samplerate=samplerate)
                winsound.PlaySound(str(temp_path), winsound.SND_FILENAME)
                return "winsound"
            finally:
                temp_path.unlink(missing_ok=True)
        except Exception as exc:
            raise AudioBackendError(str(exc)) from exc

    raise AudioBackendError(
        "No playback backend found. Install sounddevice with PortAudio, or on Linux install ffplay/ffmpeg."
    )
