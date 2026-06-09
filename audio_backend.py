"""Audio backends, device listing and safe fallbacks."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import wave

import numpy as np

from common import DEFAULT_SAMPLE_RATE, ModemSettings, clamp_settings


class AudioBackendError(RuntimeError):
    """Raised when an audio backend cannot be used."""


@dataclass(frozen=True)
class AudioDevice:
    id: int
    name: str
    hostapi: str
    max_input_channels: int
    max_output_channels: int

    @property
    def supports_input(self) -> bool:
        return self.max_input_channels > 0

    @property
    def supports_output(self) -> bool:
        return self.max_output_channels > 0

    def label(self) -> str:
        role = []
        if self.supports_input:
            role.append("in")
        if self.supports_output:
            role.append("out")
        role_text = "/".join(role) if role else "io"
        if self.hostapi:
            return f"{self.name} — {self.hostapi} ({role_text})"
        return f"{self.name} ({role_text})"


def _load_sounddevice():
    try:
        import sounddevice as sd
    except Exception:
        return None
    return sd


def sounddevice_available() -> bool:
    return _load_sounddevice() is not None


def _hostapi_name(sd, hostapi_index: int | None) -> str:
    if hostapi_index is None:
        return ""
    try:
        hostapis = sd.query_hostapis()
        if 0 <= hostapi_index < len(hostapis):
            return str(hostapis[hostapi_index].get("name", ""))
    except Exception:
        pass
    return ""


def _looks_like_junk_device(name: str, hostapi: str) -> bool:
    n = name.strip().lower()
    h = hostapi.strip().lower()

    if any(tag in h for tag in ("pipewire", "pulse", "core audio", "wasapi", "directsound", "mme", "alsa", "jack")):
        return False

    junk_prefixes = (
        "default",
        "sysdefault",
        "front:",
        "surround",
        "null",
        "pulse",
        "hw:",
        "plughw:",
        "dmix",
        "dsnoop",
        "jack",
        "loopback",
    )
    junk_terms = ("dummy", "monitor", "virtual", "blackhole")
    if n.startswith(junk_prefixes) or any(term in n for term in junk_terms):
        return True
    return False


def _device_is_usable(sd, device_index: int, kind: str, samplerate: int = DEFAULT_SAMPLE_RATE) -> bool:
    try:
        if kind == "input":
            sd.check_input_settings(device=device_index, channels=1, samplerate=samplerate, dtype="float32")
        else:
            sd.check_output_settings(device=device_index, channels=1, samplerate=samplerate, dtype="float32")
        return True
    except Exception:
        return False


def list_audio_devices(kind: str, *, advanced: bool = False, samplerate: int = DEFAULT_SAMPLE_RATE) -> list[AudioDevice]:
    """Return a cleaned list of devices for the requested direction."""
    sd = _load_sounddevice()
    if sd is None:
        return []

    if kind not in {"input", "output"}:
        raise ValueError("kind must be 'input' or 'output'")

    try:
        raw_devices = sd.query_devices()
    except Exception:
        return []

    devices: list[AudioDevice] = []
    for idx, info in enumerate(raw_devices):
        max_in = int(info.get("max_input_channels", 0) or 0)
        max_out = int(info.get("max_output_channels", 0) or 0)
        if kind == "input" and max_in <= 0:
            continue
        if kind == "output" and max_out <= 0:
            continue

        hostapi_index = info.get("hostapi")
        hostapi = _hostapi_name(sd, int(hostapi_index) if hostapi_index is not None else None)
        name = str(info.get("name", f"Device {idx}"))

        if not advanced and _looks_like_junk_device(name, hostapi):
            continue
        if not _device_is_usable(sd, idx, kind, samplerate=samplerate):
            continue

        devices.append(
            AudioDevice(
                id=idx,
                name=name,
                hostapi=hostapi,
                max_input_channels=max_in,
                max_output_channels=max_out,
            )
        )

    if not advanced:
        priority = {
            "pipewire": 0,
            "pulseaudio": 1,
            "core audio": 1,
            "wasapi": 1,
            "directsound": 2,
            "mme": 2,
            "alsa": 3,
            "jack": 4,
            "": 5,
        }
        chosen: dict[str, AudioDevice] = {}
        for dev in devices:
            key = dev.name.strip().lower()
            rank = priority.get(dev.hostapi.strip().lower(), 6)
            current = chosen.get(key)
            if current is None:
                chosen[key] = dev
                continue
            current_rank = priority.get(current.hostapi.strip().lower(), 6)
            if rank < current_rank:
                chosen[key] = dev
        devices = sorted(chosen.values(), key=lambda d: (priority.get(d.hostapi.strip().lower(), 6), d.name.lower()))
    else:
        devices = sorted(devices, key=lambda d: (d.name.lower(), d.hostapi.lower()))

    return devices


def create_input_stream(*, samplerate: int, device: int | None, callback):
    sd = _load_sounddevice()
    if sd is None:
        raise AudioBackendError(
            "Live input requires sounddevice / PortAudio. Install the system PortAudio package and sounddevice."
        )
    kwargs = {
        "channels": 1,
        "samplerate": samplerate,
        "dtype": "float32",
        "callback": callback,
        "blocksize": 0,
    }
    if device is not None:
        kwargs["device"] = device
    try:
        return sd.InputStream(**kwargs)
    except Exception as exc:
        raise AudioBackendError(
            f"Could not open the selected input device. {exc}\n\n"
            "If the app needs permission, allow microphone access and try another device."
        ) from exc


def play_audio(audio: np.ndarray, *, samplerate: int, device: int | None = None) -> str:
    sd = _load_sounddevice()
    if sd is not None:
        kwargs = {"samplerate": samplerate, "blocking": True}
        if device is not None:
            kwargs["device"] = device
        try:
            sd.play(audio, **kwargs)
            sd.wait()
            return "sounddevice"
        except Exception as exc:
            raise AudioBackendError(
                f"Playback failed on the selected output device. {exc}\n\n"
                "Choose another output device or use the system default."
            ) from exc

    if sys.platform.startswith("linux"):
        if shutil.which("ffplay") and shutil.which("ffmpeg"):
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                temp_path = Path(tmp.name)
            try:
                write_wav_file(temp_path, audio, samplerate=samplerate)
                subprocess.run(
                    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error", str(temp_path)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return "ffplay"
            except Exception as exc:
                raise AudioBackendError(f"Playback fallback failed: {exc}") from exc
            finally:
                temp_path.unlink(missing_ok=True)

    if sys.platform.startswith("win"):
        try:
            import winsound
        except Exception as exc:
            raise AudioBackendError(f"Winsound is unavailable: {exc}") from exc

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            temp_path = Path(tmp.name)
        try:
            write_wav_file(temp_path, audio, samplerate=samplerate)
            winsound.PlaySound(str(temp_path), winsound.SND_FILENAME)
            return "winsound"
        except Exception as exc:
            raise AudioBackendError(f"Playback fallback failed: {exc}") from exc
        finally:
            temp_path.unlink(missing_ok=True)

    raise AudioBackendError(
        "No playback backend could be found. Install sounddevice/PortAudio or Linux ffplay."
    )


def write_wav_file(path: str | Path, audio: np.ndarray, *, samplerate: int) -> None:
    path = Path(path)
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)
    audio = np.clip(np.nan_to_num(audio, copy=False), -1.0, 1.0)

    pcm = (audio * 32767.0).astype(np.int16)

    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(int(samplerate))
        wav.writeframes(pcm.tobytes())


def read_wav_file(path: str | Path) -> np.ndarray:
    path = Path(path)
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        frames = wav.readframes(wav.getnframes())
        rate = wav.getframerate()

    if width == 1:
        data = np.frombuffer(frames, dtype=np.uint8).astype(np.float32)
        data = (data - 128.0) / 128.0
    elif width == 2:
        data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif width == 4:
        data = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise AudioBackendError(f"Unsupported WAV sample width: {width} bytes")

    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)

    if rate != DEFAULT_SAMPLE_RATE:
        # Keep the app predictable. We do not resample silently.
        raise AudioBackendError(
            f"Audio file sample rate is {rate} Hz, but the modem expects {DEFAULT_SAMPLE_RATE} Hz WAV files."
        )

    return data.astype(np.float32, copy=False)


class Recorder:
    """Recorder wrapper that prefers sounddevice, with a Linux ffmpeg fallback."""

    def __init__(self, *, samplerate: int = DEFAULT_SAMPLE_RATE, device: int | None = None) -> None:
        self.samplerate = samplerate
        self.device = device
        self._sd = _load_sounddevice()
        self._mode = self._choose_mode()
        self._stream = None
        self._frames: list[np.ndarray] = []
        self._ffmpeg_proc: subprocess.Popen[str] | None = None
        self._temp_path: Path | None = None

    def _choose_mode(self) -> str:
        if self._sd is not None:
            return "sounddevice"
        if sys.platform.startswith("linux") and shutil.which("ffmpeg"):
            return "ffmpeg"
        raise AudioBackendError(
            "No usable recording backend found. Install sounddevice/PortAudio, or on Linux install ffmpeg."
        )

    @property
    def mode(self) -> str:
        return self._mode

    def start(self) -> None:
        if self._mode == "sounddevice":
            self._frames = []

            def _callback(indata, frames, time, status):  # noqa: ANN001
                del frames, time
                if status:
                    # Never crash on callback status warnings.
                    pass
                self._frames.append(indata.copy())

            kwargs = {
                "channels": 1,
                "samplerate": self.samplerate,
                "dtype": "float32",
                "callback": _callback,
            }
            if self.device is not None:
                kwargs["device"] = self.device

            try:
                self._stream = self._sd.InputStream(**kwargs)
                self._stream.start()
            except Exception as exc:
                raise AudioBackendError(
                    f"Could not open the selected input device. {exc}\n\n"
                    "Check microphone access and try another device."
                ) from exc
            return

        fd, name = tempfile.mkstemp(prefix="audio_modem_rec_", suffix=".wav")
        os.close(fd)
        self._temp_path = Path(name)

        candidates = [
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "pulse", "-i", "default",
             "-ac", "1", "-ar", str(self.samplerate), str(self._temp_path)],
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "alsa", "-i", "default",
             "-ac", "1", "-ar", str(self.samplerate), str(self._temp_path)],
        ]

        last_error: Exception | None = None
        for cmd in candidates:
            try:
                self._ffmpeg_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except Exception as exc:
                last_error = exc
        raise AudioBackendError(f"Recording fallback could not start: {last_error}") from last_error

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

        if self._ffmpeg_proc is None or self._temp_path is None:
            return np.empty(0, dtype=np.float32)

        try:
            try:
                self._ffmpeg_proc.terminate()
            except Exception:
                pass

            try:
                self._ffmpeg_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._ffmpeg_proc.kill()
                self._ffmpeg_proc.wait(timeout=5)

            if not self._temp_path.exists() or self._temp_path.stat().st_size == 0:
                raise AudioBackendError(
                    "The fallback recorder did not produce any audio. On Linux, make sure ffmpeg can see your microphone."
                )
            return read_wav_file(self._temp_path)
        finally:
            self._ffmpeg_proc = None
            if self._temp_path is not None:
                self._temp_path.unlink(missing_ok=True)
                self._temp_path = None
