"""Shared helpers for the simple audio modem."""
from __future__ import annotations

import math
import zlib

import numpy as np

SAMPLE_RATE = 44100
BIT_DURATION = 0.025  # 25 ms per bit -> 40 bps
SYMBOL_SAMPLES = int(round(SAMPLE_RATE * BIT_DURATION))

FREQ_0 = 1200.0
FREQ_1 = 2200.0
AMPLITUDE = 0.75
PREAMBLE_BITS = "101010101010101010101010101010101010101010101010"  # 48 bits
GUARD_SILENCE_SEC = 0.20


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
    """Frame layout: preamble + length(2 bytes) + payload + crc32(4 bytes)."""
    length = len(payload).to_bytes(2, "big")
    crc = zlib.crc32(payload).to_bytes(4, "big")
    framed = PREAMBLE_BITS + bytes_to_bits(length) + bytes_to_bits(payload) + bytes_to_bits(crc)
    return framed


def parse_frame_bits(bits: str) -> tuple[bytes, str]:
    """Return (payload, error_message). On success, error_message is empty."""
    preamble_index = bits.find(PREAMBLE_BITS)
    if preamble_index < 0:
        return b"", "Preamble not found. The audio may be too quiet, clipped, or misaligned."

    start = preamble_index + len(PREAMBLE_BITS)
    if len(bits) < start + 16:
        return b"", "Incomplete frame. Could not read the message length."

    length_bits = bits[start : start + 16]
    payload_len = int(length_bits, 2)
    payload_start = start + 16
    payload_end = payload_start + payload_len * 8
    crc_end = payload_end + 32
    if len(bits) < crc_end:
        available_bytes = max(0, (len(bits) - payload_start) // 8)
        return b"", (
            f"Incomplete frame. Expected {payload_len} payload bytes, "
            f"but only {available_bytes} bytes were captured."
        )

    payload_bits = bits[payload_start:payload_end]
    crc_bits = bits[payload_end:crc_end]
    payload = bits_to_bytes(payload_bits)
    expected_crc = int(crc_bits, 2)
    actual_crc = zlib.crc32(payload) & 0xFFFFFFFF
    if actual_crc != expected_crc:
        return b"", (
            "CRC check failed. The recording likely contains noise, "
            "clock drift, or a mismatched device selection."
        )
    return payload, ""


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

    # Normalize lightly to improve the chance of decoding across different device gains.
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak > 0:
        audio = audio / peak

    # Search for the best alignment by matching the known preamble.
    best_offset = 0
    best_score = -1
    preamble_len = len(PREAMBLE_BITS)

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

    bits: list[str] = []
    pos = best_offset
    while pos + SYMBOL_SAMPLES <= audio.size:
        bits.append(detect_bit(audio[pos : pos + SYMBOL_SAMPLES]))
        pos += SYMBOL_SAMPLES
    return "".join(bits)


def summarize_audio_length(audio: np.ndarray) -> str:
    seconds = audio.shape[0] / SAMPLE_RATE if audio.size else 0.0
    return f"{seconds:.2f} s"
