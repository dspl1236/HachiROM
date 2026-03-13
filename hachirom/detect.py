"""
HachiROM — ROM detection engine.
Detection priority:
  1. CRC32 against known stock hashes              → confidence "hash"
  2. Reset vector at 0x7FFE                        → confidence "reset_vector"
  3. Structural scoring (byte sum, map markers)    → confidence "heuristic"
  4. Fallthrough                                   → confidence "unknown"

Edited ROMs will always fail CRC32 — that is expected. The structural
scorer is designed to remain stable across any edited or tuned ROM of a
given variant, since it tests byte-sum proximity to checksum target,
reset vector, and addresses that are never part of tunable maps.
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


# ---------------------------------------------------------------------------
# Structural scorer — stable across any edited ROM of a given variant
# ---------------------------------------------------------------------------

def _score_variant(rom32: bytes, variant: ROMVariant) -> int:
    """
    Score a ROM against a variant definition using stable structural markers.
    Returns an integer; 0 = no match evidence, ≥30 with ≥15 margin = confident.

    Markers used are deliberately outside tunable map regions so they survive
    any legitimate fuel/timing/knock edit.
    """
    score = 0
    vk    = variant.version_key
    vec   = (rom32[0x7FFE], rom32[0x7FFF])

    # ── Reset vector (high weight — unique per variant) ───────────────────
    if variant.reset_vector and tuple(variant.reset_vector) == vec:
        score += 50

    # ── Byte sum vs checksum target ───────────────────────────────────────
    # A correctly-checksummed edited ROM will hit the target exactly.
    # An uncorrected edit will be within ~a few thousand (one map cell = ±255).
    cs_target = variant.checksum.get("target", 0)
    cs_actual = sum(rom32)
    if cs_actual == cs_target:
        score += 35
    elif abs(cs_actual - cs_target) < 2000:
        score += 20
    elif abs(cs_actual - cs_target) < 20000:
        score += 5

    # ── Variant-specific structural markers ───────────────────────────────
    if vk == "AAH":
        # Injection scaler 0x077E — stock is always 100 (never in fuel map)
        if rom32[0x077E] == 100:
            score += 10
        # CL RPM limit 0x07E1 — AAH stock = 244 (high RPM range)
        if 200 <= rom32[0x07E1] <= 255:
            score += 5
        # AAH correction region 0x6700 has varied data (not blank, not code-dense)
        cs_region = rom32[0x6700:0x6720]
        if len(set(cs_region)) > 8:
            score += 5

    elif vk == "266D":
        # 266D has fully programmed upper region — few 0xFF bytes at 0x7E00
        blank_7e = sum(1 for b in rom32[0x7E00:0x7F00] if b == 0xFF)
        if blank_7e < 20:
            score += 15
        # 266D correction region 0x1600 has varied data
        if len(set(rom32[0x1600:0x1620])) > 6:
            score += 5

    elif vk == "266B":
        # 266B has large blank region at 0x7E00 (early ECU, less code)
        blank_7e = sum(1 for b in rom32[0x7E00:0x7F00] if b == 0xFF)
        if blank_7e > 180:
            score += 25
        # 266B has MAF linearisation at 0x02D0 — non-trivial data
        if len(set(rom32[0x02D0:0x02E0])) > 4:
            score += 5

    return score


# ---------------------------------------------------------------------------
# Main detection entry point
# ---------------------------------------------------------------------------

def detect(data: bytes) -> DetectionResult:
    """
    Identify the ROM variant. Accepts raw .bin or scrambled .034 files.
    Always returns a result — variant may be None for truly unrecognised ROMs,
    but the structural scorer will set variant to best guess when confident.
    """
    notes: list[str] = []
    native = _ensure_native(data, notes)

    rom32 = native[:32768]
    if len(rom32) < 32768:
        rom32 = rom32 + bytes(32768 - len(rom32))

    sha256 = hashlib.sha256(rom32).hexdigest()
    crc32  = zlib.crc32(rom32) & 0xFFFFFFFF
    vec    = (rom32[0x7FFE], rom32[0x7FFF])

    # 1. CRC32 exact match (stock ROMs only)
    if crc32 in _CRC32_MAP:
        v = _CRC32_MAP[crc32]
        return DetectionResult(v, sha256, crc32, len(data), "hash",
                               [f"CRC32 match: {v.name} ({v.part_number})"])

    # 2. Reset vector match
    if vec in _RESET_VEC_MAP:
        v = _RESET_VEC_MAP[vec]
        notes.append(f"Reset vector {vec[0]:02X} {vec[1]:02X} → {v.name}")
        return DetectionResult(v, sha256, crc32, len(data), "reset_vector", notes)

    # 3. Structural scoring
    scores = [(v, _score_variant(rom32, v)) for v in ALL_VARIANTS]
    scores.sort(key=lambda x: -x[1])
    best_v, best_score   = scores[0]
    second_score         = scores[1][1]
    margin               = best_score - second_score

    if best_score >= 30 and margin >= 15:
        notes.append(
            f"Structural match → {best_v.name} "
            f"(score {best_score}, margin +{margin} over next candidate)")
        notes.append(
            f"vec={vec[0]:02X}{vec[1]:02X}  "
            f"bytesum={sum(rom32):,}  "
            f"target={best_v.checksum.get('target', 0):,}")
        return DetectionResult(best_v, sha256, crc32, len(data), "heuristic", notes)

    # 4. Unknown — no confident match
    guess = f"{best_v.name} (score {best_score})" if best_score > 0 else "none"
    notes.append(
        f"No confident structural match. Best guess: {guess}. "
        f"vec={vec[0]:02X}{vec[1]:02X}  bytesum={sum(rom32):,}")
    return DetectionResult(None, sha256, crc32, len(data), "unknown", notes)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_native(data: bytes, notes: list) -> bytes:
    """Return native ROM bytes, unscrambling .034 if needed."""
    import zlib as _z
    if (_z.crc32(data[:32768]) & 0xFFFFFFFF) in _CRC32_MAP:
        return data
    unscrambled = unscramble_034(data)
    if (_z.crc32(unscrambled[:32768]) & 0xFFFFFFFF) in _CRC32_MAP:
        notes.append("Auto-detected .034 scrambled file — unscrambled for analysis")
        return unscrambled
    return data


def load_bin(path: str | Path) -> bytes:
    return Path(path).read_bytes()

def save_bin(data: bytes, path: str | Path) -> None:
    Path(path).write_bytes(data)
