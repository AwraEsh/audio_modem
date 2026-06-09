"""Shared modem logic for the audio text ↔ voice demo."""
from __future__ import annotations

from dataclasses import dataclass
import math
import zlib

import numpy as np

SAMPLE_RATE = 44_100
BIT_DURATION = 0.020  # 20 ms per symbol -> 50 symbols/sec
SYMBOL_SAMPLES = max(1, int(round(SAMPLE_RATE * BIT_DURATION)))

FREQ_0 = 1200.0
FREQ_1 = 2200.0
AMPLITUDE = 0.72

# A short, balanced sync word. It is intentionally not a pure alternating pattern.
PREAMBLE_BITS = "11010011101100101011001011100101"  # 32 bits

LEAD_SILENCE_SEC = 0.12
TRAIL_SILENCE_SEC = 0.12

_WINDOW = np.hanning(SYMBOL_SAMPLES).astype(np.float64)
_TONE_CACHE: dict[float, np.ndarray] = {}


def text_to_payload(text: str) -> bytes:
    return text.encode("utf-8")


def payload_to_text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


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


def build_frame_bits(payload: bytes) -> str:
    """
    Frame format:
        preamble + 16-bit length + payload + 32-bit CRC32
    """
    length = len(payload).to_bytes(2, "big")
    crc = zlib.crc32(payload).to_bytes(4, "big")
    return PREAMBLE_BITS + bytes_to_bits(length) + bytes_to_bits(payload) + bytes_to_bits(crc)


def parse_frame_bits(bits: str) -> tuple[bytes, str]:
    """
    Returns (payload, error_message). On success, error_message is empty.
    """
    if not bits:
        return b"", "No bits were decoded."

    preamble_index = bits.find(PREAMBLE_BITS)
    if preamble_index < 0:
        return b"", "Sync word not found. Check the selected device, gain, or alignment."

    start = preamble_index + len(PREAMBLE_BITS)
    if len(bits) < start + 16:
        return b"", "Frame is incomplete. The message length could not be read."

    payload_len = int(bits[start : start + 16], 2)
    payload_start = start + 16
    payload_end = payload_start + payload_len * 8
    crc_end = payload_end + 32

    if len(bits) < crc_end:
        have = max(0, (len(bits) - payload_start) // 8)
        return b"", f"Frame is incomplete. Expected {payload_len} byte(s), captured {have}."

    payload_bits = bits[payload_start:payload_end]
    crc_bits = bits[payload_end:crc_end]
    payload = bits_to_bytes(payload_bits)

    expected_crc = int(crc_bits, 2)
    actual_crc = zlib.crc32(payload) & 0xFFFFFFFF
    if actual_crc != expected_crc:
        return b"", "CRC check failed. The capture is probably noisy or the device gain is off."

    return payload, ""


def _tone(freq: float) -> np.ndarray:
    cached = _TONE_CACHE.get(freq)
    if cached is not None:
        return cached

    t = np.arange(SYMBOL_SAMPLES, dtype=np.float64) / SAMPLE_RATE
    tone = np.sin(2.0 * math.pi * freq * t)

    # Small fade at the edges to reduce clicks.
    fade_len = max(1, int(round(0.002 * SAMPLE_RATE)))
    fade_len = min(fade_len, SYMBOL_SAMPLES // 2)
    if fade_len > 1:
        fade = np.ones(SYMBOL_SAMPLES, dtype=np.float64)
        ramp = np.linspace(0.0, 1.0, fade_len, endpoint=False)
        fade[:fade_len] = ramp
        fade[-fade_len:] = ramp[::-1]
        tone *= fade

    tone = (AMPLITUDE * tone).astype(np.float32)
    _TONE_CACHE[freq] = tone
    return tone


_TONE_0 = _tone(FREQ_0)
_TONE_1 = _tone(FREQ_1)
_LEAD_SILENCE = np.zeros(int(round(LEAD_SILENCE_SEC * SAMPLE_RATE)), dtype=np.float32)
_TRAIL_SILENCE = np.zeros(int(round(TRAIL_SILENCE_SEC * SAMPLE_RATE)), dtype=np.float32)


def bits_to_audio(bits: str) -> np.ndarray:
    parts: list[np.ndarray] = [_LEAD_SILENCE]
    for bit in bits:
        parts.append(_TONE_1 if bit == "1" else _TONE_0)
    parts.append(_TRAIL_SILENCE)
    return np.concatenate(parts)


def _trim_silence(audio: np.ndarray) -> np.ndarray:
    if audio.size == 0:
        return audio

    peak = float(np.max(np.abs(audio)))
    if peak <= 0.0:
        return np.empty(0, dtype=np.float32)

    # Normalize first so the trim threshold behaves the same on every device.
    audio = audio / peak

    if audio.size < 1024:
        return audio.astype(np.float32, copy=False)

    envelope_window = max(128, SYMBOL_SAMPLES // 4)
    kernel = np.ones(envelope_window, dtype=np.float64) / envelope_window
    envelope = np.convolve(np.abs(audio), kernel, mode="same")

    threshold = 0.04
    active = np.flatnonzero(envelope > threshold)
    if active.size == 0:
        return audio.astype(np.float32, copy=False)

    margin = SYMBOL_SAMPLES * 2
    start = max(0, int(active[0]) - margin)
    end = min(audio.size, int(active[-1]) + margin)
    return audio[start:end].astype(np.float32, copy=False)


def goertzel_power(samples: np.ndarray, freq: float) -> float:
    samples = np.asarray(samples, dtype=np.float64)
    n = samples.size
    if n == 0:
        return 0.0

    k = int(0.5 + (n * freq) / SAMPLE_RATE)
    omega = (2.0 * math.pi * k) / n
    coeff = 2.0 * math.cos(omega)

    s_prev = 0.0
    s_prev2 = 0.0
    for sample in samples:
        s = sample + coeff * s_prev - s_prev2
        s_prev2 = s_prev
        s_prev = s

    return float(s_prev2 * s_prev2 + s_prev * s_prev - coeff * s_prev * s_prev2)


def detect_bit(block: np.ndarray) -> str:
    if block.size == 0:
        return "0"

    block = np.asarray(block, dtype=np.float64)
    block = block - np.mean(block)
    block *= _WINDOW[: block.size]

    p0 = goertzel_power(block, FREQ_0)
    p1 = goertzel_power(block, FREQ_1)
    return "1" if p1 > p0 else "0"


def audio_to_bits(audio: np.ndarray) -> str:
    """
    Convert a waveform into a bit stream.
    The algorithm trims silence, normalizes the signal, then searches for the sync word.
    """
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)

    audio = np.asarray(audio, dtype=np.float32)
    audio = np.nan_to_num(audio, copy=False)

    if audio.size == 0:
        return ""

    audio = _trim_silence(audio)
    if audio.size < SYMBOL_SAMPLES:
        return ""

    # Re-normalize after trimming to help the symbol detector across devices.
    peak = float(np.max(np.abs(audio)))
    if peak > 0.0:
        audio = audio / peak

    preamble_len = len(PREAMBLE_BITS)
    best_score = -1
    best_offset = 0

    # Search for the best symbol alignment by checking the sync word.
    max_offset = min(SYMBOL_SAMPLES, max(1, audio.size - preamble_len * SYMBOL_SAMPLES))
    for offset in range(max_offset):
        pos = offset
        score = 0
        for expected in PREAMBLE_BITS:
            block = audio[pos : pos + SYMBOL_SAMPLES]
            if block.size < SYMBOL_SAMPLES:
                break
            if detect_bit(block) == expected:
                score += 1
            pos += SYMBOL_SAMPLES

        if score > best_score:
            best_score = score
            best_offset = offset
            if score == preamble_len:
                break

    # If the sync word match is weak, return nothing instead of inventing garbage.
    if best_score < int(preamble_len * 0.70):
        return ""

    bits: list[str] = []
    pos = best_offset
    while pos + SYMBOL_SAMPLES <= audio.size:
        bits.append(detect_bit(audio[pos : pos + SYMBOL_SAMPLES]))
        pos += SYMBOL_SAMPLES
    return "".join(bits)


def decode_audio_to_text(audio: np.ndarray) -> tuple[str | None, str]:
    """
    Attempt to decode text directly from waveform.
    Returns (text, error_message). The error is empty on success.
    """
    bits = audio_to_bits(audio)
    payload, error = parse_frame_bits(bits)
    if error:
        return None, error
    return payload_to_text(payload), ""


def summarize_audio_length(audio: np.ndarray) -> str:
    seconds = audio.shape[0] / SAMPLE_RATE if audio.size else 0.0
    return f"{seconds:.2f} s"
