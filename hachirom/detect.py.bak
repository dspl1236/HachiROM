"""
HachiROM — ROM detection engine.
Uses same fingerprinting strategy as ecu_profiles.py in audi90-teensy-ecu:
  1. CRC32 of native 32KB ROM against known stock hashes (HIGH confidence)
  2. Reset vector bytes at 0x7FFE                       (HIGH confidence)
  3. Blank EPROM region heuristic at 0x7E00             (MEDIUM confidence)
"""

import hashlib
import zlib
from pathlib import Path
from typing import Optional
from .roms import ROMVariant, ALL_VARIANTS, _CRC32_MAP, _RESET_VEC_MAP, unscramble_034


class DetectionResult:
    def __init__(self, variant: Optional[ROMVariant], sha256: str, crc32: int,
                 size: int, confidence: str, notes: list[str]):
        self.variant    = variant
        self.sha256     = sha256
        self.crc32      = crc32
        self.size       = size
        self.confidence = confidence   # "hash" | "reset_vector" | "heuristic" | "unknown"
        self.notes      = notes

    def __repr__(self):
        name = self.variant.name if self.variant else "Unknown"
        return f"<DetectionResult variant={name!r} confidence={self.confidence!r}>"


def detect(data: bytes) -> DetectionResult:
    """
    Identify the ROM variant from raw binary data.
    Input can be a raw .bin dump or a .034 file — .034 is auto-detected
    and unscrambled before fingerprinting.
    """
    notes: list[str] = []

    # Auto-detect and unscramble .034 files
    native = _ensure_native(data, notes)

    # Work on the first 32KB (native ROM is always 32KB even if chip is 64KB)
    rom32 = native[:32768]
    if len(rom32) < 32768:
        rom32 = rom32 + bytes(32768 - len(rom32))

    sha256 = hashlib.sha256(rom32).hexdigest()
    crc32  = zlib.crc32(rom32) & 0xFFFFFFFF

    # 1. CRC32 match
    if crc32 in _CRC32_MAP:
        v = _CRC32_MAP[crc32]
        return DetectionResult(v, sha256, crc32, len(data), "hash",
                               [f"CRC32 match: {v.name} ({v.part_number})"])

    # 2. Reset vector at 0x7FFE
    vec = (rom32[0x7FFE], rom32[0x7FFF])
    if vec in _RESET_VEC_MAP:
        v = _RESET_VEC_MAP[vec]
        notes.append(f"Reset vector {vec[0]:02X}{vec[1]:02X} @ 0x7FFE → {v.name}")
        return DetectionResult(v, sha256, crc32, len(data), "reset_vector", notes)

    # 3. Blank region heuristic (266B has 0xFF upper region, 266D has code)
    blank_count = sum(1 for b in rom32[0x7E00:0x7F00] if b == 0xFF)
    if blank_count > 200:
        v = next(x for x in ALL_VARIANTS if x.version_key == "266B")
        notes.append(f"Blank region @ 0x7E00 ({blank_count}/256 = 0xFF) → probably 266B")
        return DetectionResult(v, sha256, crc32, len(data), "heuristic", notes)
    elif blank_count < 20:
        v = next(x for x in ALL_VARIANTS if x.version_key == "266D")
        notes.append(f"Programmed region @ 0x7E00 ({blank_count}/256 = 0xFF) → probably 266D")
        return DetectionResult(v, sha256, crc32, len(data), "heuristic", notes)

    notes.append(f"No fingerprint matched. CRC32={crc32:#010x}, vec={vec[0]:02X}{vec[1]:02X}")
    return DetectionResult(None, sha256, crc32, len(data), "unknown", notes)


def _ensure_native(data: bytes, notes: list) -> bytes:
    """
    Detect if data is a .034 (scrambled) file and unscramble if needed.
    Heuristic: if entropy of first 32 bytes is very high and doesn't look
    like normal code/data, try unscrambling and check if it looks better.
    Simple approach: try to match CRC32 both ways.
    """
    import zlib as _z
    native_crc = _z.crc32(data[:32768]) & 0xFFFFFFFF
    if native_crc in _CRC32_MAP:
        return data

    from .roms import unscramble_034 as _unscramble
    unscrambled = _unscramble(data)
    unscrambled_crc = _z.crc32(unscrambled[:32768]) & 0xFFFFFFFF
    if unscrambled_crc in _CRC32_MAP:
        notes.append("Auto-detected .034 scrambled file — unscrambled for analysis")
        return unscrambled

    return data


def load_bin(path: str | Path) -> bytes:
    """Load a .bin or .034 file from disk."""
    return Path(path).read_bytes()

def save_bin(data: bytes, path: str | Path) -> None:
    """Save native binary data to a .bin file."""
    Path(path).write_bytes(data)
