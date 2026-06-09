"""Shared audio modem logic."""
from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
import math
import zlib
import json

import numpy as np

DEFAULT_SAMPLE_RATE = 44_100


@dataclass(frozen=True)
class ModemSettings:
    sample_rate: int = DEFAULT_SAMPLE_RATE
    symbol_rate: float = 100.0
    freq_low: float = 1200.0
    freq_high: float = 2200.0
    amplitude: float = 0.72
    bit_repeat: int = 2
    sync_start_freq: float = 800.0
    sync_end_freq: float = 2800.0
    sync_ms: float = 180.0
    guard_silence_ms: float = 20.0
    lead_silence_ms: float = 120.0
    trail_silence_ms: float = 120.0
    max_payload_bytes: int = 65535
    search_tolerance_samples: int = 8  # small wiggle room after sync lock
    live_buffer_seconds: float = 12.0
    preview_hold_seconds: float = 0.8

    @property
    def symbol_samples(self) -> int:
        return max(1, int(round(self.sample_rate / self.symbol_rate)))

    @property
    def bit_repeat_factor(self) -> int:
        return max(1, int(self.bit_repeat))

    @property
    def sync_samples(self) -> int:
        return max(1, int(round(self.sample_rate * self.sync_ms / 1000.0)))

    @property
    def guard_silence_samples(self) -> int:
        return max(0, int(round(self.sample_rate * self.guard_silence_ms / 1000.0)))

    @property
    def lead_silence_samples(self) -> int:
        return max(0, int(round(self.sample_rate * self.lead_silence_ms / 1000.0)))

    @property
    def trail_silence_samples(self) -> int:
        return max(0, int(round(self.sample_rate * self.trail_silence_ms / 1000.0)))


def clamp_settings(settings: ModemSettings) -> ModemSettings:
    symbol_rate = float(min(max(settings.symbol_rate, 10.0), 250.0))
    f0 = float(min(max(settings.freq_low, 80.0), settings.sample_rate / 2.5))
    f1 = float(min(max(settings.freq_high, 80.0), settings.sample_rate / 2.5))
    if abs(f1 - f0) < 100.0:
        f1 = f0 + 100.0

    amp = float(min(max(settings.amplitude, 0.05), 0.95))
    repeat = int(min(max(settings.bit_repeat, 1), 8))
    start_freq = float(min(max(settings.sync_start_freq, 80.0), settings.sample_rate / 2.5))
    end_freq = float(min(max(settings.sync_end_freq, 80.0), settings.sample_rate / 2.5))
    sync_ms = float(min(max(settings.sync_ms, 40.0), 800.0))
    guard = float(min(max(settings.guard_silence_ms, 0.0), 300.0))
    lead = float(min(max(settings.lead_silence_ms, 0.0), 800.0))
    trail = float(min(max(settings.trail_silence_ms, 0.0), 800.0))
    search = int(min(max(settings.search_tolerance_samples, 0), 64))

    return replace(
        settings,
        symbol_rate=symbol_rate,
        freq_low=f0,
        freq_high=f1,
        amplitude=amp,
        bit_repeat=repeat,
        sync_start_freq=start_freq,
        sync_end_freq=end_freq,
        sync_ms=sync_ms,
        guard_silence_ms=guard,
        lead_silence_ms=lead,
        trail_silence_ms=trail,
        search_tolerance_samples=search,
    )


def text_to_payload(text: str) -> bytes:
    return text.encode("utf-8")


def payload_to_text(payload: bytes) -> str:
    return payload.decode("utf-8", errors="replace")


def bytes_to_bits(data: bytes) -> str:
    return "".join(f"{byte:08b}" for byte in data)


def bits_to_bytes(bits: str) -> bytes:
    usable = len(bits) - (len(bits) % 8)
    if usable <= 0:
        return b""
    out = bytearray()
    for pos in range(0, usable, 8):
        out.append(int(bits[pos : pos + 8], 2))
    return bytes(out)


def _collapse_repeated_bits(bits: str, repeat: int) -> str:
    repeat = max(1, int(repeat))
    if repeat <= 1:
        return bits
    usable = len(bits) - (len(bits) % repeat)
    out: list[str] = []
    for pos in range(0, usable, repeat):
        chunk = bits[pos : pos + repeat]
        out.append("1" if chunk.count("1") >= chunk.count("0") else "0")
    return "".join(out)


def build_frame_bits(payload: bytes, settings: ModemSettings) -> str:
    settings = clamp_settings(settings)
    length = len(payload).to_bytes(2, "big")
    crc = zlib.crc32(payload).to_bytes(4, "big")
    frame = bytes_to_bits(length) + bytes_to_bits(payload) + bytes_to_bits(crc)
    repeat = settings.bit_repeat_factor
    return "".join(bit * repeat for bit in frame)


@lru_cache(maxsize=64)
def _tone_cache(sample_rate: int, symbol_samples: int, freq: float, amplitude: float) -> np.ndarray:
    t = np.arange(symbol_samples, dtype=np.float64) / float(sample_rate)
    wave = np.sin(2.0 * math.pi * freq * t)

    fade_len = max(1, int(round(sample_rate * 0.002)))
    fade_len = min(fade_len, symbol_samples // 2)
    if fade_len > 1:
        fade = np.ones(symbol_samples, dtype=np.float64)
        ramp = np.linspace(0.0, 1.0, fade_len, endpoint=False)
        fade[:fade_len] = ramp
        fade[-fade_len:] = ramp[::-1]
        wave *= fade

    return (amplitude * wave).astype(np.float32)


def _template_for(settings: ModemSettings, freq: float) -> np.ndarray:
    settings = clamp_settings(settings)
    return _tone_cache(settings.sample_rate, settings.symbol_samples, float(freq), float(settings.amplitude))


@lru_cache(maxsize=32)
def _sync_chirp(sample_rate: int, duration_samples: int, amplitude: float, start_freq: float, end_freq: float) -> np.ndarray:
    duration_samples = max(1, int(duration_samples))
    t = np.arange(duration_samples, dtype=np.float64) / float(sample_rate)
    duration = duration_samples / float(sample_rate)
    slope = (end_freq - start_freq) / max(duration, 1e-9)
    phase = 2.0 * math.pi * (start_freq * t + 0.5 * slope * t * t)
    wave = np.sin(phase)

    fade_len = max(1, int(round(sample_rate * 0.004)))
    fade_len = min(fade_len, duration_samples // 2)
    if fade_len > 1:
        fade = np.ones(duration_samples, dtype=np.float64)
        ramp = np.linspace(0.0, 1.0, fade_len, endpoint=False)
        fade[:fade_len] = ramp
        fade[-fade_len:] = ramp[::-1]
        wave *= fade

    return (amplitude * wave).astype(np.float32)


def _sync_template(settings: ModemSettings) -> np.ndarray:
    settings = clamp_settings(settings)
    return _sync_chirp(
        settings.sample_rate,
        settings.sync_samples,
        settings.amplitude,
        settings.sync_start_freq,
        settings.sync_end_freq,
    )


def bits_to_audio(bits: str, settings: ModemSettings) -> np.ndarray:
    settings = clamp_settings(settings)
    low = _template_for(settings, settings.freq_low)
    high = _template_for(settings, settings.freq_high)
    sync = _sync_template(settings)

    parts: list[np.ndarray] = []
    if settings.lead_silence_samples:
        parts.append(np.zeros(settings.lead_silence_samples, dtype=np.float32))
    parts.append(sync)
    if settings.guard_silence_samples:
        parts.append(np.zeros(settings.guard_silence_samples, dtype=np.float32))

    for bit in bits:
        parts.append(high if bit == "1" else low)

    if settings.trail_silence_samples:
        parts.append(np.zeros(settings.trail_silence_samples, dtype=np.float32))

    return np.concatenate(parts).astype(np.float32, copy=False) if parts else np.zeros(0, dtype=np.float32)


def encode_text_to_audio(text: str, settings: ModemSettings) -> tuple[np.ndarray, str]:
    payload = text_to_payload(text)
    bits = build_frame_bits(payload, settings)
    return bits_to_audio(bits, settings), bits


def _as_mono(audio: np.ndarray) -> np.ndarray:
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)
    return np.nan_to_num(audio, copy=False)


def _fft_valid_correlate(x: np.ndarray, h: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    h = np.asarray(h, dtype=np.float64)
    if x.size < h.size:
        return np.empty(0, dtype=np.float64)
    n = x.size + h.size - 1
    size = 1 << (n - 1).bit_length()
    X = np.fft.rfft(x, size)
    H = np.fft.rfft(h[::-1], size)
    y = np.fft.irfft(X * H, size)[:n]
    start = h.size - 1
    stop = start + x.size - h.size + 1
    return y[start:stop]


def _moving_energy(audio: np.ndarray, window: int) -> np.ndarray:
    if audio.size < window:
        return np.zeros(0, dtype=np.float64)
    squared = np.square(audio.astype(np.float64, copy=False))
    cumsum = np.cumsum(np.insert(squared, 0, 0.0))
    return cumsum[window:] - cumsum[:-window]


def audio_to_bits(audio: np.ndarray, settings: ModemSettings) -> tuple[str, np.ndarray, np.ndarray]:
    settings = clamp_settings(settings)
    audio = _as_mono(audio)
    if audio.size < settings.symbol_samples:
        return "", np.zeros(0, dtype=np.float64), np.zeros(0, dtype=np.float64)

    peak = float(np.max(np.abs(audio)))
    if peak > 0.0:
        audio = audio / peak

    tone0 = _template_for(settings, settings.freq_low).astype(np.float64, copy=False)
    tone1 = _template_for(settings, settings.freq_high).astype(np.float64, copy=False)
    corr0 = _fft_valid_correlate(audio, tone0)
    corr1 = _fft_valid_correlate(audio, tone1)
    return _decode_raw_bits(corr0, corr1, settings), corr0, corr1


def _decode_raw_bits(corr0: np.ndarray, corr1: np.ndarray, settings: ModemSettings) -> str:
    diff = corr1 - corr0
    positions = np.arange(0, diff.size, settings.symbol_samples, dtype=np.int64)
    if positions.size == 0:
        return ""
    bits = np.where(diff[positions] >= 0.0, "1", "0")
    return "".join(bits.tolist())


def _trim_silence(audio: np.ndarray, *, settings: ModemSettings) -> np.ndarray:
    if audio.size == 0:
        return audio
    peak = float(np.max(np.abs(audio)))
    if peak <= 0.0:
        return np.empty(0, dtype=np.float32)

    audio = audio / peak
    if audio.size < settings.symbol_samples * 4:
        return audio.astype(np.float32, copy=False)

    window = max(128, settings.symbol_samples // 4)
    kernel = np.ones(window, dtype=np.float64) / window
    envelope = np.convolve(np.abs(audio), kernel, mode="same")

    threshold = 0.02
    active = np.flatnonzero(envelope > threshold)
    if active.size == 0:
        return audio.astype(np.float32, copy=False)

    margin = settings.symbol_samples * 2
    start = max(0, int(active[0]) - margin)
    end = min(audio.size, int(active[-1]) + margin)
    return audio[start:end].astype(np.float32, copy=False)


def parse_frame_bits(bits: str, settings: ModemSettings) -> tuple[bytes | None, str]:
    settings = clamp_settings(settings)
    if len(bits) < 16 + 32:
        return None, "Frame is too short to contain the header and CRC."

    payload_len = int(bits[:16], 2)
    if payload_len <= 0 or payload_len > settings.max_payload_bytes:
        return None, "Invalid payload length."

    payload_end = 16 + payload_len * 8
    crc_end = payload_end + 32
    if crc_end > len(bits):
        have = max(0, (len(bits) - 16) // 8)
        return None, f"Frame is incomplete. Expected {payload_len} byte(s), captured {have}."

    payload = bits_to_bytes(bits[16:payload_end])
    expected_crc = int(bits[payload_end:crc_end], 2)
    actual_crc = zlib.crc32(payload) & 0xFFFFFFFF
    if actual_crc != expected_crc:
        return None, "CRC check failed. The capture is probably noisy or the settings do not match."

    return payload, ""


def _find_sync_start(audio: np.ndarray, settings: ModemSettings) -> int | None:
    sync = _sync_template(settings).astype(np.float64, copy=False)
    corr = _fft_valid_correlate(audio, sync)
    if corr.size == 0:
        return None
    candidates = np.argpartition(corr, -8)[-8:]
    candidates = candidates[np.argsort(corr[candidates])[::-1]]
    return int(candidates[0])


def decode_audio_to_text(audio: np.ndarray, settings: ModemSettings) -> tuple[str | None, str]:
    settings = clamp_settings(settings)
    audio = _as_mono(audio)
    if audio.size < settings.symbol_samples:
        return None, "No bits were decoded from the selected audio."

    peak = float(np.max(np.abs(audio)))
    if peak > 0.0:
        audio = audio / peak

    tone0 = _template_for(settings, settings.freq_low).astype(np.float64, copy=False)
    tone1 = _template_for(settings, settings.freq_high).astype(np.float64, copy=False)
    corr0 = _fft_valid_correlate(audio, tone0)
    corr1 = _fft_valid_correlate(audio, tone1)
    diff = corr1 - corr0

    sync_start = _find_sync_start(audio, settings)
    if sync_start is None:
        return None, "No sync burst was found."

    base = sync_start + settings.sync_samples + settings.guard_silence_samples
    candidates = range(max(0, base - settings.search_tolerance_samples), base + settings.search_tolerance_samples + 1)

    tried: set[int] = set()
    for start in candidates:
        if start in tried:
            continue
        tried.add(start)
        raw_bits = _decode_raw_bits(
            corr0[start:],
            corr1[start:],
            settings,
        )
        bits = _collapse_repeated_bits(raw_bits, settings.bit_repeat_factor)
        payload, error = parse_frame_bits(bits, settings)
        if payload is not None and error == "":
            return payload_to_text(payload), ""

    return None, "No valid frame found. Check the device, frequencies, or gain."


def settings_to_dict(settings: ModemSettings) -> dict:
    """Convert ModemSettings to a JSON-serializable dict."""
    return {
        "sample_rate": settings.sample_rate,
        "symbol_rate": settings.symbol_rate,
        "freq_low": settings.freq_low,
        "freq_high": settings.freq_high,
        "amplitude": settings.amplitude,
        "bit_repeat": settings.bit_repeat,
        "sync_start_freq": settings.sync_start_freq,
        "sync_end_freq": settings.sync_end_freq,
        "sync_ms": settings.sync_ms,
        "guard_silence_ms": settings.guard_silence_ms,
        "lead_silence_ms": settings.lead_silence_ms,
        "trail_silence_ms": settings.trail_silence_ms,
        "max_payload_bytes": settings.max_payload_bytes,
        "search_tolerance_samples": settings.search_tolerance_samples,
        "live_buffer_seconds": settings.live_buffer_seconds,
        "preview_hold_seconds": settings.preview_hold_seconds,
    }

def dict_to_settings(data: dict) -> ModemSettings:
    """Create ModemSettings from a dict (with defaults for missing keys)."""
    defaults = ModemSettings()
    for key in defaults.__dataclass_fields__.keys():
        if key not in data:
            data[key] = getattr(defaults, key)
    return ModemSettings(**data)

def save_settings_to_file(settings: ModemSettings, path: str | Path) -> None:
    """Save settings to a JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings_to_dict(settings), f, indent=2)

def load_settings_from_file(path: str | Path) -> ModemSettings:
    """Load settings from a JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return dict_to_settings(data)


def decode_audio_file(path: str, settings: ModemSettings) -> tuple[str | None, str]:
    from audio_backend import read_wav_file
    audio = read_wav_file(path)
    return decode_audio_to_text(audio, settings)


def summarize_audio_length(audio: np.ndarray, sample_rate: int = DEFAULT_SAMPLE_RATE) -> str:
    seconds = float(len(audio)) / float(sample_rate) if sample_rate else 0.0
    if seconds < 1.0:
        return f"{len(audio)} samples"
    return f"{seconds:.2f} s"
