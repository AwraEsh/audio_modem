"""Shared helpers for the simple audio modem."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple

import numpy as np

SAMPLE_RATE = 44100
BIT_DURATION = 0.02  # 20 ms per bit -> 50 bps
SYMBOL_SAMPLES = int(round(SAMPLE_RATE * BIT_DURATION))

FREQ_0 = 1200.0
FREQ_1 = 2200.0
AMPLITUDE = 0.75
PREAMBLE_BITS = "01010101010101010101010101010101"  # 32 bits
GUARD_SILENCE_SEC = 0.15


def text_to_payload(text: str) -> bytes:
    return text.encode("utf-8")


def payload_to_text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def bytes_to_bits(data: bytes) -> str:
    return "".join(f"{byte:08b}" for byte in data)


def bits_to_bytes(bits: str) -> bytes:
    usable = len(bits) - (len(bits) % 8)
    out = bytearray()
    for i in range(0, usable, 8):
        out.append(int(bits[i : i + 8], 2))
    return bytes(out)


def build_frame_bits(payload: bytes) -> str:
    length = len(payload).to_bytes(2, "big")
    framed = PREAMBLE_BITS + bytes_to_bits(length) + bytes_to_bits(payload)
    return framed


def parse_frame_bits(bits: str) -> tuple[bytes, str]:
    """Return (payload, error_message). On success, error_message is empty."""
    preamble_index = bits.find(PREAMBLE_BITS)
    if preamble_index < 0:
        return b"", "پیش‌دنباله پیدا نشد. احتمالاً صدا ضعیف بوده یا هم‌زمانی بیت‌ها به هم خورده."

    start = preamble_index + len(PREAMBLE_BITS)
    if len(bits) < start + 16:
        return b"", "فریم کامل نیست. طول پیام خوانده نشد."

    length_bits = bits[start : start + 16]
    payload_len = int(length_bits, 2)
    payload_start = start + 16
    payload_end = payload_start + payload_len * 8
    if len(bits) < payload_end:
        return b"", (
            f"فریم ناقص است. انتظار داشتم {payload_len} بایت داده باشد، "
            f"ولی فقط {max(0, (len(bits) - payload_start) // 8)} بایت دیده شد."
        )

    payload_bits = bits[payload_start:payload_end]
    return bits_to_bytes(payload_bits), ""


def _tone(symbol_freq: float, n: int = SYMBOL_SAMPLES) -> np.ndarray:
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    tone = np.sin(2.0 * math.pi * symbol_freq * t)

    # Gentle fade in/out to reduce clicks.
    fade_len = max(1, int(round(0.002 * SAMPLE_RATE)))
    fade_len = min(fade_len, n // 2)
    if fade_len > 1:
        fade = np.ones(n, dtype=np.float64)
        ramp = np.linspace(0.0, 1.0, fade_len, endpoint=False)
        fade[:fade_len] = ramp
        fade[-fade_len:] = ramp[::-1]
        tone *= fade

    return (AMPLITUDE * tone).astype(np.float32)


_TONE_0 = _tone(FREQ_0)
_TONE_1 = _tone(FREQ_1)
_SILENCE_GUARD = np.zeros(int(round(GUARD_SILENCE_SEC * SAMPLE_RATE)), dtype=np.float32)


def bits_to_audio(bits: str) -> np.ndarray:
    chunks: list[np.ndarray] = [_SILENCE_GUARD]
    for bit in bits:
        chunks.append(_TONE_1 if bit == "1" else _TONE_0)
    chunks.append(_SILENCE_GUARD)
    return np.concatenate(chunks)


def goertzel_power(samples: np.ndarray, freq: float) -> float:
    """Compute the magnitude-like power at a target frequency."""
    samples = np.asarray(samples, dtype=np.float64)
    n = samples.size
    if n == 0:
        return 0.0

    k = int(0.5 + (n * freq) / SAMPLE_RATE)
    omega = (2.0 * math.pi * k) / n
    coeff = 2.0 * math.cos(omega)
    s_prev = 0.0
    s_prev2 = 0.0
    for x in samples:
        s = x + coeff * s_prev - s_prev2
        s_prev2 = s_prev
        s_prev = s
    power = s_prev2 * s_prev2 + s_prev * s_prev - coeff * s_prev * s_prev2
    return float(power)


def detect_bit(block: np.ndarray) -> str:
    """Classify a symbol-sized block into '0' or '1'."""
    if block.size == 0:
        return "0"
    # Remove DC component.
    block = np.asarray(block, dtype=np.float64)
    block = block - np.mean(block)
    p0 = goertzel_power(block, FREQ_0)
    p1 = goertzel_power(block, FREQ_1)
    return "1" if p1 > p0 else "0"


def audio_to_bits(audio: np.ndarray) -> str:
    """Decode an audio recording into a bit string using fixed symbol windows."""
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)
    audio = np.asarray(audio, dtype=np.float32)

    if audio.size < SYMBOL_SAMPLES:
        return ""

    # Search for the best alignment by matching the known preamble.
    best_offset = 0
    best_score = -1
    preamble_len = len(PREAMBLE_BITS)

    # A simple brute-force phase search; fast enough for small recordings.
    max_offset = min(SYMBOL_SAMPLES, audio.size)
    for offset in range(max_offset):
        score = 0
        pos = offset
        for expected in PREAMBLE_BITS:
            if pos + SYMBOL_SAMPLES > audio.size:
                break
            bit = detect_bit(audio[pos : pos + SYMBOL_SAMPLES])
            if bit == expected:
                score += 1
            pos += SYMBOL_SAMPLES
        if score > best_score:
            best_score = score
            best_offset = offset
            if score == preamble_len:
                break

    # Decode from the best phase.
    bits: list[str] = []
    pos = best_offset
    while pos + SYMBOL_SAMPLES <= audio.size:
        bits.append(detect_bit(audio[pos : pos + SYMBOL_SAMPLES]))
        pos += SYMBOL_SAMPLES
    return "".join(bits)


def summarize_audio_length(audio: np.ndarray) -> str:
    seconds = audio.shape[0] / SAMPLE_RATE if audio.size else 0.0
    return f"{seconds:.2f} s"
