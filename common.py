"""Shared modem logic for the audio text ↔ voice demo."""
from __future__ import annotations

from dataclasses import dataclass
import math
import zlib

import numpy as np

SAMPLE_RATE = 44_100
BIT_DURATION = 0.020  # 20 ms per symbol -> 50 symbols/sec
SYMBOL_SAMPLES = max(1, int(round(SAMPLE_RATE * BIT_DURATION)))

# Two clean tones that fit an integer number of cycles in one symbol window.
FREQ_0 = 1200.0
FREQ_1 = 2200.0
AMPLITUDE = 0.72

# A sync word with decent bit balance.
PREAMBLE_BITS = "11010011101100101011001011100101"  # 32 bits
PREAMBLE_MIN_MATCH = 22  # tolerate a few errors in the sync word

LEAD_SILENCE_SEC = 0.16
TRAIL_SILENCE_SEC = 0.12

_WINDOW = np.hanning(SYMBOL_SAMPLES).astype(np.float64)
_TONE_CACHE: dict[float, np.ndarray] = {}
_DEMOD_CACHE: dict[float, np.ndarray] = {}


@dataclass(frozen=True)
class FrameDecodeResult:
    text: str | None
    error: str
    confidence: float = 0.0


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
    """Frame format: preamble + 16-bit length + payload + 32-bit CRC32."""
    length = len(payload).to_bytes(2, "big")
    crc = zlib.crc32(payload).to_bytes(4, "big")
    return PREAMBLE_BITS + bytes_to_bits(length) + bytes_to_bits(payload) + bytes_to_bits(crc)


def _tone(freq: float) -> np.ndarray:
    cached = _TONE_CACHE.get(freq)
    if cached is not None:
        return cached

    t = np.arange(SYMBOL_SAMPLES, dtype=np.float64) / SAMPLE_RATE
    tone = np.sin(2.0 * math.pi * freq * t)

    # Small fade at the edges reduces clicks and helps the capture chain.
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
_DEMOD_0 = (_WINDOW * _TONE_0.astype(np.float64)).astype(np.float64)
_DEMOD_1 = (_WINDOW * _TONE_1.astype(np.float64)).astype(np.float64)
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

    audio = audio / peak
    if audio.size < 1024:
        return audio.astype(np.float32, copy=False)

    envelope_window = max(128, SYMBOL_SAMPLES // 4)
    kernel = np.ones(envelope_window, dtype=np.float64) / envelope_window
    envelope = np.convolve(np.abs(audio), kernel, mode="same")

    threshold = 0.02
    active = np.flatnonzero(envelope > threshold)
    if active.size == 0:
        return audio.astype(np.float32, copy=False)

    # Keep a tiny pre-roll only. Too much silence pushes the sync word outside the
    # one-symbol search window, which makes decode look "dead" even when the tone is there.
    leading_margin = max(1, int(round(0.003 * SAMPLE_RATE)))
    trailing_margin = max(SYMBOL_SAMPLES * 2, int(round(0.060 * SAMPLE_RATE)))
    start = max(0, int(active[0]) - leading_margin)
    end = min(audio.size, int(active[-1]) + trailing_margin)
    return audio[start:end].astype(np.float32, copy=False)


def _symbol_energy(block: np.ndarray) -> tuple[float, float]:
    block = np.asarray(block, dtype=np.float64)
    if block.size == 0:
        return 0.0, 0.0

    block = block - np.mean(block)
    block *= _WINDOW[: block.size]

    # Vectorized dot products are fast and stable enough for this small modem.
    p0 = float(np.dot(block, _DEMOD_0[: block.size]))
    p1 = float(np.dot(block, _DEMOD_1[: block.size]))
    return p0 * p0, p1 * p1


def detect_bit(block: np.ndarray) -> tuple[str, float]:
    if block.size == 0:
        return "0", 0.0

    p0, p1 = _symbol_energy(block)
    if p0 <= 0.0 and p1 <= 0.0:
        return "0", 0.0

    winner = "1" if p1 > p0 else "0"
    confidence = abs(p1 - p0) / max(p0, p1, 1e-12)
    return winner, float(confidence)


def _best_symbol_offset(audio: np.ndarray) -> tuple[int, float]:
    preamble_len = len(PREAMBLE_BITS)
    max_offset = min(SYMBOL_SAMPLES, max(1, audio.size - preamble_len * SYMBOL_SAMPLES))

    best_offset = 0
    best_score = float("-inf")

    for offset in range(max_offset):
        pos = offset
        score = 0.0
        for expected in PREAMBLE_BITS:
            block = audio[pos : pos + SYMBOL_SAMPLES]
            if block.size < SYMBOL_SAMPLES:
                break
            bit, confidence = detect_bit(block)
            score += confidence if bit == expected else -confidence
            pos += SYMBOL_SAMPLES

        if score > best_score:
            best_score = score
            best_offset = offset

    return best_offset, best_score


def audio_to_bits(audio: np.ndarray) -> str:
    """Convert a waveform into a bit stream."""
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)

    audio = np.asarray(audio, dtype=np.float32)
    audio = np.nan_to_num(audio, copy=False)

    if audio.size == 0:
        return ""

    audio = _trim_silence(audio)
    if audio.size < SYMBOL_SAMPLES:
        return ""

    peak = float(np.max(np.abs(audio)))
    if peak > 0.0:
        audio = audio / peak

    best_offset, best_score = _best_symbol_offset(audio)
    if not np.isfinite(best_score):
        return ""

    # If the alignment is completely off, do not invent garbage.
    if best_score < (len(PREAMBLE_BITS) * 0.22):
        return ""

    bits: list[str] = []
    pos = best_offset
    while pos + SYMBOL_SAMPLES <= audio.size:
        bit, _confidence = detect_bit(audio[pos : pos + SYMBOL_SAMPLES])
        bits.append(bit)
        pos += SYMBOL_SAMPLES
    return "".join(bits)


def _find_frame_candidates(bits: str) -> list[tuple[int, int]]:
    preamble = PREAMBLE_BITS
    plen = len(preamble)
    if len(bits) < plen + 16 + 32:
        return []

    candidates: list[tuple[int, int]] = []
    search_end = len(bits) - (plen + 16 + 32)
    for start in range(search_end + 1):
        window = bits[start : start + plen]
        score = sum(1 for a, b in zip(window, preamble) if a == b)
        if score < PREAMBLE_MIN_MATCH:
            continue
        candidates.append((start, score))

    candidates.sort(key=lambda item: item[1], reverse=True)
    return candidates


def parse_frame_bits(bits: str) -> tuple[bytes, str]:
    """Return (payload, error_message). On success, error_message is empty."""
    if not bits:
        return b"", "No bits were decoded."

    candidates = _find_frame_candidates(bits)
    if not candidates:
        return b"", "Sync word not found. Check the selected device, gain, or alignment."

    max_reasonable_payload = 8192
    saw_sync = False
    saw_crc_problem = False
    saw_incomplete = False

    for start, _score in candidates:
        saw_sync = True
        sync_start = start + len(PREAMBLE_BITS)
        if len(bits) < sync_start + 16:
            saw_incomplete = True
            continue

        payload_len = int(bits[sync_start : sync_start + 16], 2)
        if payload_len <= 0 or payload_len > max_reasonable_payload:
            continue

        payload_start = sync_start + 16
        payload_end = payload_start + payload_len * 8
        crc_end = payload_end + 32

        if len(bits) < crc_end:
            saw_incomplete = True
            continue

        payload_bits = bits[payload_start:payload_end]
        crc_bits = bits[payload_end:crc_end]
        payload = bits_to_bytes(payload_bits)

        expected_crc = int(crc_bits, 2)
        actual_crc = zlib.crc32(payload) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            saw_crc_problem = True
            continue

        return payload, ""

    if saw_crc_problem:
        return b"", "CRC check failed. The capture is probably noisy or the device gain is off."
    if saw_incomplete:
        return b"", "Frame is incomplete. Keep recording a little longer and try again."
    if saw_sync:
        return b"", "Sync word found, but no valid frame could be parsed."
    return b"", "Sync word not found. Check the selected device, gain, or alignment."


def decode_audio_to_text(audio: np.ndarray) -> tuple[str | None, str]:
    bits = audio_to_bits(audio)
    payload, error = parse_frame_bits(bits)
    if error:
        return None, error
    return payload_to_text(payload), ""


def summarize_audio_length(audio: np.ndarray) -> str:
    seconds = audio.shape[0] / SAMPLE_RATE if audio.size else 0.0
    return f"{seconds:.2f} s"
